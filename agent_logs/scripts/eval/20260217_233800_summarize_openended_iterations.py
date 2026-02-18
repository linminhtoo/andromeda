#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class IterationRun:
    iteration: str
    strategy: str
    run_dir: Path


RUNS: list[IterationRun] = [
    IterationRun(
        iteration="iter1",
        strategy="baseline diverse open-ended set",
        run_dir=Path(
            "eval/results_revamp/open/"
            "eval_run.open_diverse_iter1_baseline_normal_tools12_norefine_qt350_jt350.20260217_220205"
        ),
    ),
    IterationRun(
        iteration="iter2",
        strategy="period-scope guardrail prompt additions",
        run_dir=Path(
            "eval/results_revamp/open/"
            "eval_run.open_diverse_iter2_periodscope_normal_tools12_norefine_qt350_jt350.20260217_222053"
        ),
    ),
    IterationRun(
        iteration="iter3",
        strategy="expanded narrative intent + diversified retrieval queries",
        run_dir=Path(
            "eval/results_revamp/open/"
            "eval_run.open_diverse_iter3_narrativecoverage_normal_tools12_norefine_qt350_jt350.20260217_223936"
        ),
    ),
    IterationRun(
        iteration="iter4",
        strategy="narrative draft temperature=0 (ablation)",
        run_dir=Path(
            "eval/results_revamp/open/"
            "eval_run.open_diverse_iter4_narrativetemp0_normal_tools12_norefine_qt350_jt350.20260217_225755"
        ),
    ),
]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{100.0 * float(value):.2f}%"


def main() -> None:
    rows: list[dict[str, str]] = []
    for item in RUNS:
        generation = _read_json(item.run_dir / "generation_summary.json")
        summary = _read_json(item.run_dir / "score_summary.json")
        open_rates = summary.get("open_ended_judge_fail_rates") or {}
        faith = open_rates.get("faithfulness_v1")
        helpf = open_rates.get("helpfulness_v1")

        rows.append(
            {
                "iteration": item.iteration,
                "strategy": item.strategy,
                "run_dir": str(item.run_dir),
                "n": str(generation.get("n", "")),
                "n_ok": str(generation.get("n_ok", "")),
                "n_err": str(generation.get("n_err", "")),
                "avg_total_ms": f"{float(generation.get('avg_total_ms', 0.0)):.2f}",
                "wall_total_ms": f"{float(generation.get('wall_total_ms', 0.0)):.2f}",
                "faithfulness_fail_rate": f"{float(faith):.12f}" if faith is not None else "",
                "helpfulness_fail_rate": f"{float(helpf):.12f}" if helpf is not None else "",
                "faithfulness_fail_pct": _fmt_pct(faith),
                "helpfulness_fail_pct": _fmt_pct(helpf),
            }
        )

    out_csv = Path("agent_logs/openended_iteration_metrics_20260217.csv")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    lines: list[str] = []
    lines.append("# Open-Ended Iteration Summary (2026-02-17)")
    lines.append("")
    lines.append(
        "| Iteration | Strategy | n_ok | n_err | Faithfulness Fail | Helpfulness Fail | Avg Total ms | Wall ms |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for row in rows:
        lines.append(
            "| "
            + f"{row['iteration']}"
            + " | "
            + f"{row['strategy']}"
            + " | "
            + f"{row['n_ok']}"
            + " | "
            + f"{row['n_err']}"
            + " | "
            + f"{row['faithfulness_fail_pct']}"
            + " | "
            + f"{row['helpfulness_fail_pct']}"
            + " | "
            + f"{float(row['avg_total_ms']):.0f}"
            + " | "
            + f"{float(row['wall_total_ms']):.0f}"
            + " |"
        )
    lines.append("")
    lines.append("Best faithfulness in this series: `iter3`.")

    out_md = Path("agent_logs/openended_iteration_summary_20260217.md")
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {out_csv}")
    print(f"Wrote {out_md}")


if __name__ == "__main__":
    main()
