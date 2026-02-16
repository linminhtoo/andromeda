#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from andromeda.generation_controls import resolve_generation_settings

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

RUN_NAME_RE = re.compile(r"^eval_run\.(?:(?P<name>.+)\.)?(?P<stamp>\d{8}_\d{6})$")

CSV_FIELDS = [
    "scope",
    "run_id",
    "run_name",
    "timestamp",
    "status",
    "mode",
    "concurrency",
    "parallel_backend",
    "enable_rerank",
    "enable_refine",
    "top_k_retrieve",
    "top_k_rerank",
    "draft_max_tokens",
    "final_max_tokens",
    "query_timeout_s",
    "n_queries",
    "n_generated_rows",
    "n_ok",
    "n_err",
    "generation_progress",
    "avg_total_ms",
    "wall_total_ms",
    "throughput_qps",
    "factual_n_ok",
    "factual_gold_chunk_hit_rate",
    "factual_numeric_accuracy",
    "factual_correctness_fail_rate",
    "factual_helpfulness_fail_rate",
    "open_ended_n_ok",
    "open_ended_faithfulness_fail_rate",
    "open_ended_helpfulness_fail_rate",
    "comparison_n_ok",
    "comparison_fail_rate",
    "comparison_helpfulness_fail_rate",
    "refusal_fail_rate",
    "distractor_focus_fail_rate",
    "distractor_helpfulness_fail_rate",
    "run_dir",
]


@dataclass(frozen=True)
class RunIdentity:
    run_id: str
    run_name: str
    timestamp: str | None
    timestamp_dt: datetime | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate eval runs into dashboard CSV + HTML.")
    parser.add_argument(
        "--runs-root",
        action="append",
        default=[],
        help="Root directory containing eval_run.* directories. Can be passed multiple times.",
    )
    parser.add_argument("--out-dir", required=True, help="Output directory for dashboard artifacts.")
    parser.add_argument(
        "--include-incomplete", action="store_true", help="Include runs missing score_summary.json in dashboard rows."
    )
    return parser.parse_args()


def parse_run_identity(run_dir: Path) -> RunIdentity:
    name = run_dir.name
    m = RUN_NAME_RE.match(name)
    if m is None:
        return RunIdentity(run_id=name, run_name=name, timestamp=None, timestamp_dt=None)
    run_name = (m.group("name") or "").strip() or "unnamed"
    stamp = m.group("stamp")
    dt: datetime | None = None
    if stamp:
        try:
            dt = datetime.strptime(stamp, "%Y%m%d_%H%M%S")
        except ValueError:
            dt = None
    return RunIdentity(run_id=name, run_name=run_name, timestamp=stamp, timestamp_dt=dt)


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        try:
            value = json.load(handle, parse_constant=lambda _token: float("nan"))
        except json.JSONDecodeError:
            return None
    if isinstance(value, dict):
        return value
    return None


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def normalize_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def normalize_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def metric_from_map(summary: dict[str, Any], key: str, metric: str) -> float | None:
    raw = summary.get(key)
    if isinstance(raw, dict):
        return normalize_float(raw.get(metric))
    return None


def bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return None


def resolved_generation_config(run_cfg: dict[str, Any] | None, gen_summary: dict[str, Any] | None) -> dict[str, Any]:
    """
    Reconstruct effective generation knobs using run config + preset defaults.
    """

    rc = run_cfg or {}
    settings = gen_summary.get("settings") if isinstance(gen_summary, dict) else {}
    if not isinstance(settings, dict):
        settings = {}

    mode = str(rc.get("mode") or settings.get("mode") or "normal")
    controls = resolve_generation_settings(
        mode=mode,
        top_k_retrieve=normalize_int(rc.get("top_k_retrieve", settings.get("top_k_retrieve"))),
        top_k_rerank=normalize_int(rc.get("top_k_rerank", settings.get("top_k_rerank"))),
        draft_max_tokens=normalize_int(rc.get("draft_max_tokens", settings.get("draft_max_tokens"))),
        final_max_tokens=normalize_int(rc.get("final_max_tokens", settings.get("final_max_tokens"))),
        enable_rerank=bool_or_none(rc.get("enable_rerank", settings.get("enable_rerank"))),
        enable_refine=bool_or_none(rc.get("enable_refine", settings.get("enable_refine"))),
        draft_temperature=normalize_float(rc.get("draft_temperature", settings.get("draft_temperature"))),
    )
    return {
        "mode": controls.mode,
        "top_k_retrieve": controls.top_k_retrieve,
        "top_k_rerank": controls.top_k_rerank,
        "draft_max_tokens": controls.draft_max_tokens,
        "final_max_tokens": controls.final_max_tokens,
        "enable_rerank": controls.enable_rerank,
        "enable_refine": controls.enable_refine,
    }


def classify_status(
    *,
    has_generation_summary: bool,
    has_score_summary: bool,
    n_queries: int,
    n_generated_rows: int,
    n_ok: int | None,
    n_err: int | None,
) -> str:
    if has_score_summary:
        return "scored"
    if has_generation_summary:
        expected = n_ok + n_err if n_ok is not None and n_err is not None else n_queries
        if expected > 0 and n_generated_rows >= expected:
            return "generated_unscored"
        return "partial_generation"
    if n_generated_rows > 0:
        return "partial_generation"
    return "empty"


def collect_row(run_dir: Path, *, scope: str) -> dict[str, Any]:
    identity = parse_run_identity(run_dir)
    run_cfg = load_json(run_dir / "run_config.json")
    gen_summary = load_json(run_dir / "generation_summary.json")
    score_summary = load_json(run_dir / "score_summary.json")

    n_queries = count_lines(run_dir / "eval_queries.jsonl")
    n_generated_rows = count_lines(run_dir / "generations.jsonl")
    n_ok = normalize_int((gen_summary or {}).get("n_ok"))
    n_err = normalize_int((gen_summary or {}).get("n_err"))
    n_total = normalize_int((gen_summary or {}).get("n"))
    avg_total_ms = normalize_float((gen_summary or {}).get("avg_total_ms"))
    wall_total_ms = normalize_float((gen_summary or {}).get("wall_total_ms"))
    throughput_qps: float | None = None
    if wall_total_ms and wall_total_ms > 0 and n_ok is not None:
        throughput_qps = n_ok / (wall_total_ms / 1000.0)

    status = classify_status(
        has_generation_summary=gen_summary is not None,
        has_score_summary=score_summary is not None,
        n_queries=n_queries,
        n_generated_rows=n_generated_rows,
        n_ok=n_ok,
        n_err=n_err,
    )

    controls = resolved_generation_config(run_cfg, gen_summary)
    run_settings = (gen_summary or {}).get("settings")
    if not isinstance(run_settings, dict):
        run_settings = {}
    query_timeout = normalize_float((run_cfg or {}).get("query_timeout_s", run_settings.get("query_timeout_s")))
    concurrency = normalize_int((run_cfg or {}).get("concurrency", run_settings.get("concurrency")))
    backend = (run_cfg or {}).get("parallel_backend", run_settings.get("parallel_backend"))
    backend_s = str(backend) if backend is not None else ""

    factual_judges = (score_summary or {}).get("factual_judge_fail_rates")
    open_ended_judges = (score_summary or {}).get("open_ended_judge_fail_rates")
    refusal_judges = (score_summary or {}).get("refusal_judge_fail_rates")
    distractor_judges = (score_summary or {}).get("distractor_judge_fail_rates")

    factual_n_ok = normalize_int((score_summary or {}).get("factual_n_ok"))
    factual_gold_chunk_hit_rate = normalize_float((score_summary or {}).get("factual_gold_chunk_hit_rate"))
    factual_numeric_accuracy = normalize_float((score_summary or {}).get("factual_numeric_accuracy"))
    factual_correctness_fail_rate = metric_from_map(
        {"factual_judge_fail_rates": factual_judges}, "factual_judge_fail_rates", "factual_correctness_v1"
    )
    factual_helpfulness_fail_rate = metric_from_map(
        {"factual_judge_fail_rates": factual_judges}, "factual_judge_fail_rates", "helpfulness_v1"
    )
    if factual_helpfulness_fail_rate is None:
        factual_helpfulness_fail_rate = normalize_float((score_summary or {}).get("factual_helpfulness_fail_rate"))

    open_ended_n_ok = normalize_int((score_summary or {}).get("open_ended_n_ok"))
    open_ended_faithfulness_fail_rate = metric_from_map(
        {"open_ended_judge_fail_rates": open_ended_judges}, "open_ended_judge_fail_rates", "faithfulness_v1"
    )
    if open_ended_faithfulness_fail_rate is None:
        open_ended_faithfulness_fail_rate = normalize_float((score_summary or {}).get("open_ended_judge_fail_rate"))
    open_ended_helpfulness_fail_rate = metric_from_map(
        {"open_ended_judge_fail_rates": open_ended_judges}, "open_ended_judge_fail_rates", "helpfulness_v1"
    )
    if open_ended_helpfulness_fail_rate is None:
        open_ended_helpfulness_fail_rate = normalize_float(
            (score_summary or {}).get("open_ended_helpfulness_fail_rate")
        )

    refusal_fail_rate = metric_from_map(
        {"refusal_judge_fail_rates": refusal_judges}, "refusal_judge_fail_rates", "refusal_v1"
    )
    if refusal_fail_rate is None:
        refusal_fail_rate = normalize_float((score_summary or {}).get("refusal_judge_fail_rate"))

    distractor_focus_fail_rate = metric_from_map(
        {"distractor_judge_fail_rates": distractor_judges}, "distractor_judge_fail_rates", "focus_v1"
    )
    if distractor_focus_fail_rate is None:
        distractor_focus_fail_rate = normalize_float((score_summary or {}).get("distractor_judge_fail_rate"))

    distractor_helpfulness_fail_rate = metric_from_map(
        {"distractor_judge_fail_rates": distractor_judges}, "distractor_judge_fail_rates", "helpfulness_v1"
    )
    if distractor_helpfulness_fail_rate is None:
        distractor_helpfulness_fail_rate = normalize_float(
            (score_summary or {}).get("distractor_helpfulness_fail_rate")
        )

    comparison_judges = (score_summary or {}).get("comparison_judge_fail_rates")
    comparison_n_ok = normalize_int((score_summary or {}).get("comparison_n_ok"))
    comparison_fail_rate = metric_from_map(
        {"comparison_judge_fail_rates": comparison_judges}, "comparison_judge_fail_rates", "comparison_v1"
    )
    if comparison_fail_rate is None:
        comparison_fail_rate = normalize_float((score_summary or {}).get("comparison_judge_fail_rate"))

    comparison_helpfulness_fail_rate = metric_from_map(
        {"comparison_judge_fail_rates": comparison_judges}, "comparison_judge_fail_rates", "helpfulness_v1"
    )
    if comparison_helpfulness_fail_rate is None:
        comparison_helpfulness_fail_rate = normalize_float(
            (score_summary or {}).get("comparison_helpfulness_fail_rate")
        )

    def cell(value: Any) -> Any:
        return "" if value is None else value

    row = {
        "scope": scope,
        "run_id": identity.run_id,
        "run_name": identity.run_name,
        "timestamp": identity.timestamp or "",
        "status": status,
        "mode": controls["mode"],
        "concurrency": concurrency if concurrency is not None else "",
        "parallel_backend": backend_s,
        "enable_rerank": controls["enable_rerank"],
        "enable_refine": controls["enable_refine"],
        "top_k_retrieve": controls["top_k_retrieve"],
        "top_k_rerank": controls["top_k_rerank"],
        "draft_max_tokens": controls["draft_max_tokens"],
        "final_max_tokens": controls["final_max_tokens"],
        "query_timeout_s": query_timeout if query_timeout is not None else "",
        "n_queries": n_queries,
        "n_generated_rows": n_generated_rows,
        "n_ok": cell(n_ok),
        "n_err": cell(n_err),
        "generation_progress": (n_generated_rows / n_queries) if n_queries > 0 else 0.0,
        "avg_total_ms": cell(avg_total_ms),
        "wall_total_ms": cell(wall_total_ms),
        "throughput_qps": cell(throughput_qps),
        "factual_n_ok": cell(factual_n_ok),
        "factual_gold_chunk_hit_rate": cell(factual_gold_chunk_hit_rate),
        "factual_numeric_accuracy": cell(factual_numeric_accuracy),
        "factual_correctness_fail_rate": cell(factual_correctness_fail_rate),
        "factual_helpfulness_fail_rate": cell(factual_helpfulness_fail_rate),
        "open_ended_n_ok": cell(open_ended_n_ok),
        "open_ended_faithfulness_fail_rate": cell(open_ended_faithfulness_fail_rate),
        "open_ended_helpfulness_fail_rate": cell(open_ended_helpfulness_fail_rate),
        "comparison_n_ok": cell(comparison_n_ok),
        "comparison_fail_rate": cell(comparison_fail_rate),
        "comparison_helpfulness_fail_rate": cell(comparison_helpfulness_fail_rate),
        "refusal_fail_rate": cell(refusal_fail_rate),
        "distractor_focus_fail_rate": cell(distractor_focus_fail_rate),
        "distractor_helpfulness_fail_rate": cell(distractor_helpfulness_fail_rate),
        "run_dir": str(run_dir.resolve()),
        "_timestamp_dt": identity.timestamp_dt.isoformat() if identity.timestamp_dt is not None else "",
        "_n_total": n_total if n_total is not None else "",
    }
    return row


def discover_run_dirs(root: Path) -> list[Path]:
    return sorted([path for path in root.glob("eval_run.*") if path.is_dir()], key=lambda path: path.name)


def as_float(row: dict[str, Any], key: str) -> float | None:
    return normalize_float(row.get(key))


def format_ratio(value: Any) -> str:
    num = normalize_float(value)
    if num is None:
        return "n/a"
    return f"{num * 100:.1f}%"


def format_number(value: Any, digits: int = 3) -> str:
    num = normalize_float(value)
    if num is None:
        return "n/a"
    return f"{num:.{digits}f}"


def format_ms(value: Any) -> str:
    num = normalize_float(value)
    if num is None:
        return "n/a"
    if num >= 1000.0:
        return f"{num / 1000.0:.2f}s"
    return f"{num:.0f}ms"


def percent_class(value: Any, *, invert: bool = False) -> str:
    num = normalize_float(value)
    if num is None:
        return "na"
    score = 1.0 - num if invert else num
    if score >= 0.75:
        return "good"
    if score >= 0.5:
        return "warn"
    return "bad"


def format_bool(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "n/a"


def build_series(rows: list[dict[str, Any]], key: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for row in rows:
        value = as_float(row, key)
        if value is None:
            continue
        label = f"{row.get('run_name', 'run')} ({row.get('timestamp', '')})"
        out.append((label, value))
    return out


def render_line_chart(series: list[tuple[str, float]], *, title: str, lower_is_better: bool) -> str:
    width = 980
    height = 220
    margin = 30
    if not series:
        return (
            f"<div class='chart'>"
            f"<div class='chart-title'>{escape(title)}</div>"
            "<div class='chart-empty'>No data</div>"
            "</div>"
        )

    values = [point[1] for point in series]
    min_v = min(values)
    max_v = max(values)
    if math.isclose(min_v, max_v):
        min_v -= 0.01
        max_v += 0.01

    def x_for(i: int) -> float:
        if len(series) == 1:
            return width / 2.0
        return margin + ((width - 2 * margin) * i / (len(series) - 1))

    def y_for(v: float) -> float:
        ratio = (v - min_v) / (max_v - min_v)
        if lower_is_better:
            ratio = 1.0 - ratio
        return height - margin - ratio * (height - 2 * margin)

    points = " ".join(f"{x_for(i):.1f},{y_for(v):.1f}" for i, (_label, v) in enumerate(series))
    circles = []
    for i, (label, value) in enumerate(series):
        circles.append(
            "<circle "
            f"cx='{x_for(i):.1f}' cy='{y_for(value):.1f}' r='3.5'>"
            f"<title>{escape(label)}: {value:.3f}</title>"
            "</circle>"
        )

    return (
        "<div class='chart'>"
        f"<div class='chart-title'>{escape(title)}</div>"
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='{escape(title)}'>"
        f"<line x1='{margin}' y1='{margin}' x2='{margin}' y2='{height - margin}' class='axis' />"
        f"<line x1='{margin}' y1='{height - margin}' x2='{width - margin}' y2='{height - margin}' class='axis' />"
        f"<polyline points='{points}' class='series' />"
        f"{''.join(circles)}"
        f"<text x='{margin}' y='20' class='caption'>range: {min(values):.3f} - {max(values):.3f}</text>"
        "</svg>"
        "</div>"
    )


def render_table_rows(rows: list[dict[str, Any]]) -> str:
    rendered_rows: list[str] = []
    for row in rows:
        rendered_rows.append(
            "<tr>"
            f"<td>{escape(str(row.get('run_name', '')))}</td>"
            f"<td>{escape(str(row.get('timestamp', '')))}</td>"
            f"<td>{escape(str(row.get('scope', '')))}</td>"
            f"<td>{escape(str(row.get('status', '')))}</td>"
            f"<td>{escape(str(row.get('mode', '')))}</td>"
            f"<td>{escape(str(row.get('concurrency', '')))}</td>"
            f"<td>{escape(str(row.get('parallel_backend', '')))}</td>"
            f"<td>{format_bool(row.get('enable_refine'))}</td>"
            f"<td>{format_bool(row.get('enable_rerank'))}</td>"
            f"<td>{escape(str(row.get('top_k_retrieve', '')))}</td>"
            f"<td>{escape(str(row.get('top_k_rerank', '')))}</td>"
            f"<td>{escape(str(row.get('draft_max_tokens', '')))}</td>"
            f"<td>{escape(str(row.get('final_max_tokens', '')))}</td>"
            f"<td>{format_ms(row.get('wall_total_ms'))}</td>"
            f"<td>{format_number(row.get('throughput_qps'), 3)}</td>"
            f"<td class='{percent_class(row.get('factual_numeric_accuracy'))}'>{format_ratio(row.get('factual_numeric_accuracy'))}</td>"
            f"<td class='{percent_class(row.get('open_ended_faithfulness_fail_rate'), invert=True)}'>{format_ratio(row.get('open_ended_faithfulness_fail_rate'))}</td>"
            f"<td class='{percent_class(row.get('factual_correctness_fail_rate'), invert=True)}'>{format_ratio(row.get('factual_correctness_fail_rate'))}</td>"
            f"<td class='{percent_class(row.get('factual_helpfulness_fail_rate'), invert=True)}'>{format_ratio(row.get('factual_helpfulness_fail_rate'))}</td>"
            f"<td class='{percent_class(row.get('open_ended_helpfulness_fail_rate'), invert=True)}'>{format_ratio(row.get('open_ended_helpfulness_fail_rate'))}</td>"
            f"<td class='{percent_class(row.get('comparison_fail_rate'), invert=True)}'>{format_ratio(row.get('comparison_fail_rate'))}</td>"
            f"<td class='{percent_class(row.get('refusal_fail_rate'), invert=True)}'>{format_ratio(row.get('refusal_fail_rate'))}</td>"
            f"<td class='{percent_class(row.get('distractor_focus_fail_rate'), invert=True)}'>{format_ratio(row.get('distractor_focus_fail_rate'))}</td>"
            f"<td class='path'>{escape(str(row.get('run_dir', '')))}</td>"
            "</tr>"
        )
    return "".join(rendered_rows)


def render_html(rows: list[dict[str, Any]]) -> str:
    scored = [row for row in rows if str(row.get("status", "")).startswith("scored")]
    best_faithfulness = (
        min(
            (as_float(row, "open_ended_faithfulness_fail_rate"), row)
            for row in scored
            if as_float(row, "open_ended_faithfulness_fail_rate") is not None
        )
        if any(as_float(row, "open_ended_faithfulness_fail_rate") is not None for row in scored)
        else None
    )
    best_numeric = (
        max(
            (as_float(row, "factual_numeric_accuracy"), row)
            for row in scored
            if as_float(row, "factual_numeric_accuracy") is not None
        )
        if any(as_float(row, "factual_numeric_accuracy") is not None for row in scored)
        else None
    )
    best_throughput = (
        max((as_float(row, "throughput_qps"), row) for row in rows if as_float(row, "throughput_qps") is not None)
        if any(as_float(row, "throughput_qps") is not None for row in rows)
        else None
    )

    faith_chart = render_line_chart(
        build_series(rows, "open_ended_faithfulness_fail_rate"),
        title="Open-ended Faithfulness Fail Rate (lower is better)",
        lower_is_better=True,
    )
    numeric_chart = render_line_chart(
        build_series(rows, "factual_numeric_accuracy"),
        title="Factual Numeric Accuracy (higher is better)",
        lower_is_better=False,
    )
    throughput_chart = render_line_chart(
        build_series(rows, "throughput_qps"),
        title="Generation Throughput QPS (higher is better)",
        lower_is_better=False,
    )

    best_faithfulness_text = (
        f"{format_ratio(best_faithfulness[0])} ({best_faithfulness[1]['run_name']})" if best_faithfulness else "n/a"
    )
    best_numeric_text = f"{format_ratio(best_numeric[0])} ({best_numeric[1]['run_name']})" if best_numeric else "n/a"
    best_throughput_text = (
        f"{format_number(best_throughput[0], 3)} qps ({best_throughput[1]['run_name']})" if best_throughput else "n/a"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Eval Dashboard</title>
  <style>
    :root {{
      --bg: #f5f6f7;
      --text: #111827;
      --muted: #4b5563;
      --card: #ffffff;
      --line: #d1d5db;
      --good: #e6ffed;
      --warn: #fff7d6;
      --bad: #ffe5e5;
      --accent: #0f766e;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "IBM Plex Sans", "Segoe UI", Helvetica, Arial, sans-serif;
    }}
    .container {{
      max-width: 1600px;
      margin: 0 auto;
      padding: 24px;
    }}
    h1 {{
      margin: 0 0 10px 0;
      font-size: 28px;
      letter-spacing: -0.02em;
    }}
    .sub {{
      color: var(--muted);
      margin-bottom: 18px;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 12px 14px;
    }}
    .card .k {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 4px;
    }}
    .card .v {{
      font-size: 18px;
      font-weight: 700;
    }}
    .charts {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
      margin-bottom: 16px;
    }}
    .chart {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
    }}
    .chart-title {{
      font-weight: 600;
      font-size: 14px;
      margin-bottom: 8px;
    }}
    .chart-empty {{
      color: var(--muted);
      font-size: 13px;
      padding: 8px 2px;
    }}
    svg {{
      width: 100%;
      height: auto;
      display: block;
    }}
    .axis {{
      stroke: #9ca3af;
      stroke-width: 1;
    }}
    .series {{
      fill: none;
      stroke: var(--accent);
      stroke-width: 2.5;
    }}
    circle {{
      fill: var(--accent);
    }}
    .caption {{
      fill: var(--muted);
      font-size: 11px;
    }}
    .table-wrap {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 10px;
      overflow: auto;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 1500px;
    }}
    thead th {{
      position: sticky;
      top: 0;
      background: #f8fafc;
      border-bottom: 1px solid var(--line);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--muted);
      padding: 8px;
      text-align: left;
      white-space: nowrap;
    }}
    tbody td {{
      border-bottom: 1px solid #edf2f7;
      font-size: 12px;
      padding: 7px 8px;
      white-space: nowrap;
      vertical-align: top;
    }}
    tbody tr:hover {{
      background: #f9fafb;
    }}
    td.good {{ background: var(--good); }}
    td.warn {{ background: var(--warn); }}
    td.bad {{ background: var(--bad); }}
    td.na {{ color: #9ca3af; }}
    td.path {{
      max-width: 640px;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
  </style>
</head>
<body>
  <div class="container">
    <h1>Eval Dashboard</h1>
    <div class="sub">Generated at {escape(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))}. Total runs: {len(rows)}.</div>
    <div class="cards">
      <div class="card"><div class="k">Best Faithfulness Fail</div><div class="v">{escape(best_faithfulness_text)}</div></div>
      <div class="card"><div class="k">Best Numeric Accuracy</div><div class="v">{escape(best_numeric_text)}</div></div>
      <div class="card"><div class="k">Best Throughput</div><div class="v">{escape(best_throughput_text)}</div></div>
      <div class="card"><div class="k">Artifacts</div><div class="v">metrics_runs.csv / metrics_runs.json</div></div>
    </div>
    <div class="charts">
      {faith_chart}
      {numeric_chart}
      {throughput_chart}
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>run_name</th>
            <th>timestamp</th>
            <th>scope</th>
            <th>status</th>
            <th>mode</th>
            <th>workers</th>
            <th>backend</th>
            <th>refine</th>
            <th>rerank</th>
            <th>top_k_retrieve</th>
            <th>top_k_rerank</th>
            <th>draft_max_tokens</th>
            <th>final_max_tokens</th>
            <th>wall</th>
            <th>qps</th>
            <th>numeric_acc</th>
            <th>open_faith_fail</th>
            <th>factual_fail</th>
            <th>factual_help_fail</th>
            <th>open_help_fail</th>
            <th>comparison_fail</th>
            <th>refusal_fail</th>
            <th>distractor_focus_fail</th>
            <th>run_dir</th>
          </tr>
        </thead>
        <tbody>
          {render_table_rows(rows)}
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>
"""


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            payload = {key: row.get(key, "") for key in CSV_FIELDS}
            writer.writerow(payload)


def write_json(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [{key: row.get(key, "") for key in CSV_FIELDS} for row in rows]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def default_roots() -> list[Path]:
    candidates = [
        Path("eval/results_revamp/single"),
        Path("eval/results_revamp/multi"),
        Path("eval/results/single"),
        Path("eval/results/multi"),
    ]
    return [path for path in candidates if path.exists()]


def main() -> None:
    args = parse_args()

    roots = [Path(raw).expanduser().resolve() for raw in args.runs_root] if args.runs_root else default_roots()
    if not roots:
        raise SystemExit("No run roots found. Pass --runs-root explicitly.")

    rows: list[dict[str, Any]] = []
    for root in roots:
        scope = root.name
        for run_dir in discover_run_dirs(root):
            row = collect_row(run_dir, scope=scope)
            if not args.include_incomplete and not str(row.get("status", "")).startswith("scored"):
                continue
            rows.append(row)

    rows.sort(key=lambda row: (str(row.get("timestamp", "")), str(row.get("run_name", "")), str(row.get("run_id", ""))))

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "metrics_runs.csv"
    json_path = out_dir / "metrics_runs.json"
    html_path = out_dir / "index.html"

    write_csv(rows, csv_path)
    write_json(rows, json_path)
    html_path.write_text(render_html(rows), encoding="utf-8")

    print(f"Wrote {len(rows)} runs")
    print(f"CSV:  {csv_path}")
    print(f"JSON: {json_path}")
    print(f"HTML: {html_path}")


if __name__ == "__main__":
    main()
