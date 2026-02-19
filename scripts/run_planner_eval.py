#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import shutil
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from tqdm import tqdm

from andromeda.eval.io import dump_jsonl, load_jsonl
from andromeda.eval.planner_schema import (
    PlannerEvalAction,
    PlannerEvalCharacteristic,
    PlannerEvalPrediction,
    PlannerEvalQuery,
)
from andromeda.eval.runner import save_json

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _timestamp() -> str:
    """
    Return a filesystem-safe local timestamp token.
    """

    return datetime.now().strftime("%Y%m%d_%H%M%S")


@dataclass(frozen=True)
class PlannerRunConfig:
    concurrency: int = 8
    query_timeout_s: float | None = 180.0
    query_max_retries: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_retryable_error(exc: Exception) -> bool:
    """
    Return whether a planner exception should trigger one retry attempt.
    """

    if isinstance(exc, TimeoutError):
        return True
    message = str(exc).strip().lower()
    if not message:
        return False
    markers = (
        "timed out",
        "timeout",
        "rate limit",
        "429",
        "500",
        "502",
        "503",
        "504",
        "connection",
        "temporarily unavailable",
        "bad gateway",
        "gateway timeout",
    )
    return any(token in message for token in markers)


def _call_with_timeout(fn: Callable[[], Any], *, timeout_s: float) -> Any:
    """
    Execute a callable with a wall-clock timeout using a daemon thread.
    """

    payload: dict[str, Any] = {}
    done = threading.Event()

    def _target() -> None:
        try:
            payload["result"] = fn()
        except Exception as exc:  # noqa: BLE001
            payload["error"] = exc
        finally:
            done.set()

    worker = threading.Thread(target=_target, daemon=True, name="planner-eval-timeout-worker")
    worker.start()

    if not done.wait(timeout_s):
        raise TimeoutError(f"Timed out after {timeout_s:.1f}s")
    if "error" in payload:
        raise payload["error"]
    return payload.get("result")


def _map_characteristics(raw: list[Any]) -> list[PlannerEvalCharacteristic]:
    """
    Normalize planner characteristic payloads into enum values.
    """

    seen: set[PlannerEvalCharacteristic] = set()
    out: list[PlannerEvalCharacteristic] = []
    for item in raw:
        value = str(getattr(item, "value", item)).strip()
        if not value:
            continue
        try:
            mapped = PlannerEvalCharacteristic(value)
        except ValueError:
            continue
        if mapped in seen:
            continue
        seen.add(mapped)
        out.append(mapped)
    return out


def _map_action(raw: Any) -> PlannerEvalAction | None:
    """
    Normalize planner action payload into a planner-eval action enum.
    """

    value = str(getattr(raw, "value", raw)).strip()
    if not value:
        return None
    try:
        return PlannerEvalAction(value)
    except ValueError:
        return None


def run_one(service: Any, query: PlannerEvalQuery, cfg: PlannerRunConfig) -> tuple[PlannerEvalPrediction, float, bool]:
    """
    Execute one planner evaluation query with timeout and retry controls.
    """

    t0 = time.perf_counter()
    attempts = 0
    try:
        max_attempts = max(1, int(cfg.query_max_retries) + 1)
        planned = None
        for attempt_idx in range(max_attempts):
            attempts = attempt_idx + 1
            try:
                timeout_s = cfg.query_timeout_s
                if timeout_s is None or timeout_s <= 0:
                    planned = service.plan_query(
                        question=query.question,
                        tickers=(query.explicit_tickers if query.explicit_tickers else None),
                        filing_date_from=query.filing_date_from,
                        filing_date_to=query.filing_date_to,
                    )
                else:
                    planned = _call_with_timeout(
                        lambda: service.plan_query(
                            question=query.question,
                            tickers=(query.explicit_tickers if query.explicit_tickers else None),
                            filing_date_from=query.filing_date_from,
                            filing_date_to=query.filing_date_to,
                        ),
                        timeout_s=timeout_s,
                    )
                break
            except Exception as exc:  # noqa: BLE001
                can_retry = attempt_idx < (max_attempts - 1) and _is_retryable_error(exc)
                if not can_retry:
                    raise
                backoff_s = min(2.0, 0.5 * (2**attempt_idx))
                time.sleep(backoff_s)

        if planned is None:
            raise RuntimeError("Internal error: planner output is None after retries")

        prediction = PlannerEvalPrediction(
            query_id=query.id,
            question=query.question,
            predicted_characteristics=_map_characteristics(list(planned.characteristics or [])),
            predicted_action=_map_action(planned.status),
            predicted_tickers=list(planned.tickers or []),
            use_rag=planned.use_rag,
            use_yfinance=planned.use_yfinance,
            use_edgar_financials=planned.use_edgar_financials,
            use_per_ticker_retrieval=planned.use_per_ticker_retrieval,
            use_multi_ticker_briefs=planned.use_multi_ticker_briefs,
            attempts=attempts,
        )
        ok = True
    except Exception as exc:  # noqa: BLE001
        prediction = PlannerEvalPrediction(
            query_id=query.id,
            question=query.question,
            predicted_characteristics=[],
            predicted_action=None,
            predicted_tickers=[],
            attempts=attempts,
            error=str(exc),
        )
        ok = False

    total_ms = (time.perf_counter() - t0) * 1000.0
    prediction.timing_ms["total_ms"] = total_ms
    return prediction, total_ms, ok


def main() -> None:
    """
    CLI entrypoint for planner-characteristics eval execution.
    """

    parser = argparse.ArgumentParser(description="Run planner-characteristics evaluation queries.")
    parser.add_argument("--eval-queries", required=True, help="Planner eval queries JSONL path.")
    parser.add_argument("--out-dir", required=True, help="Output directory for run artifacts.")
    parser.add_argument("--run-name", default=None, help="Optional run name prefix.")
    parser.add_argument("--concurrency", type=int, default=8, help="Thread parallelism.")
    parser.add_argument(
        "--query-timeout-s",
        type=float,
        default=180.0,
        help="Per-query planner timeout in seconds (set <=0 to disable).",
    )
    parser.add_argument(
        "--query-max-retries", type=int, default=1, help="Retry count after first transient/timeout planner failure."
    )
    parser.add_argument("--max-items", type=int, default=None, help="Optional cap on query count.")
    args = parser.parse_args()

    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")

    queries = load_jsonl(args.eval_queries, PlannerEvalQuery)
    if args.max_items is not None:
        queries = queries[: max(0, int(args.max_items))]
    if not queries:
        raise SystemExit("No planner eval queries to run.")

    run_root = Path(args.out_dir).expanduser().resolve()
    run_root.mkdir(parents=True, exist_ok=True)

    stamp = _timestamp()
    run_name = (args.run_name.strip() + ".") if isinstance(args.run_name, str) and args.run_name.strip() else ""
    run_dir = run_root / f"planner_eval_run.{run_name}{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(args.eval_queries, run_dir / "eval_queries.jsonl")

    cfg = PlannerRunConfig(
        concurrency=max(1, int(args.concurrency)),
        query_timeout_s=(float(args.query_timeout_s) if args.query_timeout_s is not None else None),
        query_max_retries=max(0, int(args.query_max_retries)),
    )

    import andromeda.main as main_mod

    service = main_mod.get_rag_service()

    n = 0
    n_ok = 0
    n_err = 0
    total_ms = 0.0
    wall_t0 = time.perf_counter()

    predictions: list[PlannerEvalPrediction | None] = [None] * len(queries)
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(cfg.concurrency, len(queries))) as executor:
        futures = {executor.submit(run_one, service, query, cfg): idx for idx, query in enumerate(queries)}
        for future in tqdm(
            concurrent.futures.as_completed(futures),
            total=len(futures),
            desc=f"Planner eval with {cfg.concurrency} workers",
        ):
            idx = futures[future]
            prediction, item_ms, ok = future.result()
            predictions[idx] = prediction

            n += 1
            total_ms += item_ms
            if ok:
                n_ok += 1
            else:
                n_err += 1

    if any(item is None for item in predictions):
        raise RuntimeError("Internal error: missing planner prediction")

    dump_jsonl([item for item in predictions if item is not None], run_dir / "planner_predictions.jsonl")

    summary = {
        "n": n,
        "n_ok": n_ok,
        "n_err": n_err,
        "avg_total_ms": (total_ms / n) if n > 0 else 0.0,
        "wall_total_ms": (time.perf_counter() - wall_t0) * 1000.0,
        "settings": cfg.to_dict(),
    }

    save_json(cfg.to_dict(), run_dir / "run_config.json")
    save_json(summary, run_dir / "planner_prediction_summary.json")

    print(f"Wrote run dir: {run_dir}")
    print(f"Summary: {json.dumps(summary, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
