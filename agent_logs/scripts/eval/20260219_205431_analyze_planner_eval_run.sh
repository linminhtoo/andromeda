#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <planner_run_dir>" >&2
  exit 1
fi

run_dir="$1"
repo_root="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." >/dev/null 2>&1
  pwd
)"
cd "$repo_root"

source .venv/bin/activate

python - "$run_dir" <<'PY'
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

run_dir = Path(sys.argv[1]).expanduser().resolve()
review_path = run_dir / "planner_review.csv"
summary_path = run_dir / "planner_score_summary.json"
if not review_path.exists():
    raise SystemExit(f"Missing: {review_path}")
if not summary_path.exists():
    raise SystemExit(f"Missing: {summary_path}")

summary = json.loads(summary_path.read_text(encoding="utf-8"))

rows: list[dict[str, str]] = []
with review_path.open("r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle)
    for row in reader:
        rows.append({k: str(v or "") for k, v in row.items()})

group_stats: dict[str, dict[str, float]] = defaultdict(lambda: {"n": 0.0, "exact": 0.0, "subset": 0.0})
missing_counts: Counter[str] = Counter()
extra_counts: Counter[str] = Counter()
pair_counts: Counter[str] = Counter()
action_errors: list[dict[str, str]] = []

for row in rows:
    tags = row["tags"].strip() or "untagged"
    group_stats[tags]["n"] += 1.0
    group_stats[tags]["exact"] += float(int(row["characteristic_exact_match"] or "0"))
    group_stats[tags]["subset"] += float(int(row["expected_subset_recalled"] or "0"))

    missing = [item for item in row["missing_characteristics"].split() if item]
    extra = [item for item in row["extra_characteristics"].split() if item]
    for item in missing:
        missing_counts[item] += 1
    for item in extra:
        extra_counts[item] += 1

    if missing or extra:
        pair_counts[
            f"missing={','.join(missing) if missing else '-'} | extra={','.join(extra) if extra else '-'}"
        ] += 1

    expected_action = row["expected_action"].strip()
    predicted_action = row["predicted_action"].strip()
    if expected_action and expected_action != predicted_action:
        action_errors.append(
            {
                "query_id": row["query_id"],
                "question": row["question"],
                "expected_action": expected_action,
                "predicted_action": predicted_action or "none",
                "expected_characteristics": row["expected_characteristics"],
                "predicted_characteristics": row["predicted_characteristics"],
            }
        )

normalized_groups: dict[str, dict[str, float]] = {}
for group, stats in sorted(group_stats.items()):
    n = max(stats["n"], 1.0)
    normalized_groups[group] = {
        "n": int(stats["n"]),
        "exact_match_rate": stats["exact"] / n,
        "subset_recall_rate": stats["subset"] / n,
    }

analysis = {
    "run_dir": str(run_dir),
    "topline": summary,
    "group_breakdown": normalized_groups,
    "missing_characteristics": dict(missing_counts.most_common()),
    "extra_characteristics": dict(extra_counts.most_common()),
    "mismatch_patterns": [{"pattern": k, "count": v} for k, v in pair_counts.most_common(20)],
    "action_errors": action_errors,
}

reports_dir = Path("agent_logs/reports/planner_eval_20260219").resolve()
reports_dir.mkdir(parents=True, exist_ok=True)
stamp = run_dir.name.split(".")[-1]
out_json = reports_dir / f"planner_eval_analysis_{stamp}.json"
out_json.write_text(json.dumps(analysis, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Wrote analysis: {out_json}")
PY
