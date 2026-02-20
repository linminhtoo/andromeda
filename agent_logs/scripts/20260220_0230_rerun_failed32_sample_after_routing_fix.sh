#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/_env.sh"

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
project_root="$(cd -- "$script_dir/../.." >/dev/null 2>&1 && pwd)"
cd "$project_root"

source .venv/bin/activate

BASELINE_RUN="eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_001447.baseline_best.open200.normal.tools12.norefine.20260220_003443"
SOURCE_QUERIES="eval/eval_queries_openended200_diverse_20260217_v1.jsonl"
OUT_DIR="eval/results_revamp/full_suite_ablation"
RUN_NAME="routing_fix_failed32_sample10_20260220"
SAMPLE_IDS_JSON="${OUT_DIR}/${RUN_NAME}.ids.json"
SAMPLE_QUERIES_JSONL="${OUT_DIR}/${RUN_NAME}.queries.jsonl"

INGEST_PROFILE="${INGEST_PROFILE:-exp__chunk_1024_o128_tokenizer__ctx_none__index_m24_ef200}"
CHUNK_DIR="${CHUNK_DIR:-}"
POSTGRES_SCHEMA="${POSTGRES_SCHEMA:-$INGEST_PROFILE}"
if [[ -z "$CHUNK_DIR" ]]; then
  DOC_INDEX_PATH="${DOC_INDEX_PATH:-${FINRAG_DOC_INDEX_PATH_OVERRIDE:-${project_root}/data/ingest_profiles/${INGEST_PROFILE}/sec_filings_md_secparser/doc_index.jsonl}}"
else
  DOC_INDEX_PATH="$(resolve_eval_doc_index_path "$project_root" "$INGEST_PROFILE" "$CHUNK_DIR")"
fi
export FINRAG_INGEST_PROFILE="${FINRAG_INGEST_PROFILE:-$INGEST_PROFILE}"
export FINRAG_DOC_INDEX_PATH="$DOC_INDEX_PATH"

if [[ ! -f "$DOC_INDEX_PATH" ]]; then
  echo "Missing doc index path: $DOC_INDEX_PATH" >&2
  exit 1
fi

if [[ "$DOC_INDEX_PATH" != *"/data/ingest_profiles/${INGEST_PROFILE}/"* ]]; then
  echo "Doc index path/profile mismatch detected." >&2
  echo "  INGEST_PROFILE=${INGEST_PROFILE}" >&2
  echo "  DOC_INDEX_PATH=${DOC_INDEX_PATH}" >&2
  echo "Set DOC_INDEX_PATH explicitly if this is intentional." >&2
  exit 1
fi

echo "Resolved eval profile: ${INGEST_PROFILE}"
echo "Resolved doc index path: ${DOC_INDEX_PATH}"
echo "Resolved postgres schema: ${POSTGRES_SCHEMA}"

python - <<'PY'
import json
from pathlib import Path

baseline = Path("eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_001447.baseline_best.open200.normal.tools12.norefine.20260220_003443/generations.jsonl")
source = Path("eval/eval_queries_openended200_diverse_20260217_v1.jsonl")
out_ids = Path("eval/results_revamp/full_suite_ablation/routing_fix_failed32_sample10_20260220.ids.json")
out_queries = Path("eval/results_revamp/full_suite_ablation/routing_fix_failed32_sample10_20260220.queries.jsonl")

failed_ids: list[str] = []
for line in baseline.read_text(encoding="utf-8").splitlines():
    rec = json.loads(line)
    action = None
    has_refuse = False
    for ev in rec.get("tool_trace") or []:
        if ev.get("tool") == "planner_llm":
            action = (ev.get("args") or {}).get("raw_action")
        if ev.get("tool") == "refuse_unindexed_ticker_candidates":
            has_refuse = True
    if action == "clarification_required" and has_refuse:
        failed_ids.append(str(rec.get("query_id")))

sample_ids = failed_ids[:10]
out_ids.write_text(json.dumps(sample_ids, indent=2) + "\n", encoding="utf-8")

selected = []
for line in source.read_text(encoding="utf-8").splitlines():
    rec = json.loads(line)
    rec_id = rec.get("query_id")
    if rec_id is None:
        rec_id = rec.get("id")
    if str(rec_id) in sample_ids:
        selected.append(rec)

selected_by_id = {}
for rec in selected:
    rec_id = rec.get("query_id")
    if rec_id is None:
        rec_id = rec.get("id")
    selected_by_id[str(rec_id)] = rec
ordered = [selected_by_id[qid] for qid in sample_ids if qid in selected_by_id]
out_queries.write_text("\n".join(json.dumps(rec, ensure_ascii=False) for rec in ordered) + "\n", encoding="utf-8")
print(f"Selected {len(ordered)} queries -> {out_queries}")
print("Sample IDs:", sample_ids)
PY

python -m scripts.run_eval \
  --eval-queries "$SAMPLE_QUERIES_JSONL" \
  --out-dir "$OUT_DIR" \
  --run-name "$RUN_NAME" \
  --mode normal \
  --concurrency 12 \
  --parallel-backend thread \
  --doc-index-path "$DOC_INDEX_PATH" \
  --query-timeout-s 350 \
  --query-max-retries 1

RUN_DIR=$(ls -td "${OUT_DIR}/eval_run.${RUN_NAME}."* | head -n 1)

python -m scripts.score_eval \
  --run-dir "$RUN_DIR" \
  --kinds open_ended \
  --judge-workers 12 \
  --judge-context-chars 80000 \
  --judge-timeout-s 350 \
  --judge-max-retries 1

python - <<'PY'
import csv
import json
from pathlib import Path

out_root = Path("eval/results_revamp/full_suite_ablation")
run_dirs = sorted(out_root.glob("eval_run.routing_fix_failed32_sample10_20260220.*"), key=lambda p: p.stat().st_mtime)
run_dir = run_dirs[-1]

refuse_hits = 0
clarify_hits = 0
answer_hits = 0
for line in (run_dir / "generations.jsonl").read_text(encoding="utf-8").splitlines():
    rec = json.loads(line)
    action = None
    has_refuse = False
    for ev in rec.get("tool_trace") or []:
        if ev.get("tool") == "planner_llm":
            action = (ev.get("args") or {}).get("raw_action")
        if ev.get("tool") == "refuse_unindexed_ticker_candidates":
            has_refuse = True
    if has_refuse:
        refuse_hits += 1
    if action == "clarification_required":
        clarify_hits += 1
    if action == "answer":
        answer_hits += 1

print("run_dir", run_dir)
print("refuse_unindexed_ticker_candidates", refuse_hits)
print("planner_action_clarification_required", clarify_hits)
print("planner_action_answer", answer_hits)

review = run_dir / "review.csv"
if review.exists():
    rows = list(csv.DictReader(review.open(encoding="utf-8")))
    help_fail = sum(1 for r in rows if r.get("helpfulness_prediction") == "1")
    faith_fail = sum(1 for r in rows if r.get("judge_prediction") == "1")
    print("helpfulness_fails", help_fail, "of", len(rows))
    print("faithfulness_fails", faith_fail, "of", len(rows))
PY
