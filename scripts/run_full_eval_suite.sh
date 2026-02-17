#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

script_dir="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
  pwd
)"
project_root="$(
  cd -- "$script_dir/.." >/dev/null 2>&1
  pwd
)"
cd "$project_root"

if [[ -d ".venv" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

POSTGRES_SCHEMA="${POSTGRES_SCHEMA:-eval_revamp_combined_512_20260217}"
DOC_INDEX_PATH="${FINRAG_DOC_INDEX_PATH:-$project_root/data/ingest_profiles/eval_revamp_combined_512_20260217/sec_filings_md_secparser/chunked_512_64/doc_index.jsonl}"

SINGLE_QUERIES="${SINGLE_QUERIES:-eval/eval_queries_combined512_single_balanced100_validated_tol05_20260217.jsonl}"
MULTI_QUERIES="${MULTI_QUERIES:-eval/eval_queries_combined512_multi_comparison60_validated_tol05_20260217.jsonl}"
OPEN_QUERIES="${OPEN_QUERIES:-eval/eval_queries_openended200_diverse_20260217_v1.jsonl}"

MODE="${MODE:-normal}"
GEN_WORKERS="${GEN_WORKERS:-12}"
JUDGE_WORKERS="${JUDGE_WORKERS:-12}"
QUERY_TIMEOUT_S="${QUERY_TIMEOUT_S:-350}"
QUERY_MAX_RETRIES="${QUERY_MAX_RETRIES:-1}"
JUDGE_CONTEXT_CHARS="${JUDGE_CONTEXT_CHARS:-80000}"
JUDGE_TIMEOUT_S="${JUDGE_TIMEOUT_S:-350}"
JUDGE_MAX_RETRIES="${JUDGE_MAX_RETRIES:-1}"
PARALLEL_BACKEND="${PARALLEL_BACKEND:-thread}"

RUN_OPEN_STRESS="${RUN_OPEN_STRESS:-1}"
PREPARE_ASSETS="${PREPARE_ASSETS:-0}"
OUT_ROOT="${OUT_ROOT:-eval/results_revamp/full_suite}"
RUN_PREFIX="${RUN_PREFIX:-full_suite}"
STAMP="$(date +"%Y%m%d_%H%M%S")"
RUN_GROUP="${RUN_PREFIX}_${STAMP}"

if [[ ! -f "$DOC_INDEX_PATH" ]]; then
  echo "Missing doc index path: $DOC_INDEX_PATH" >&2
  exit 1
fi

if [[ -z "${POSTGRES_DSN:-${DATABASE_URL:-}}" ]]; then
  echo "Missing POSTGRES_DSN (or DATABASE_URL)." >&2
  exit 1
fi

for path in "$SINGLE_QUERIES" "$MULTI_QUERIES"; do
  if [[ ! -f "$path" ]]; then
    echo "Missing eval query file: $path" >&2
    exit 1
  fi
done
if [[ "$RUN_OPEN_STRESS" == "1" && ! -f "$OPEN_QUERIES" ]]; then
  echo "Missing open stress query file: $OPEN_QUERIES" >&2
  exit 1
fi

mkdir -p "$OUT_ROOT" logs

export POSTGRES_SCHEMA
export FINRAG_DOC_INDEX_PATH="$DOC_INDEX_PATH"
export OUT_ROOT
export RUN_GROUP
export MODE
export GEN_WORKERS
export JUDGE_WORKERS
export QUERY_TIMEOUT_S
export QUERY_MAX_RETRIES
export JUDGE_CONTEXT_CHARS
export JUDGE_TIMEOUT_S
export JUDGE_MAX_RETRIES
export DOC_INDEX_PATH

if [[ "$PREPARE_ASSETS" == "1" ]]; then
  bash scripts/prepare_eval_assets.sh
fi

run_and_score() {
  local suite_name="$1"
  local eval_queries="$2"
  local kinds="${3:-}"

  local run_name="${RUN_GROUP}.${suite_name}.${MODE}.tools${GEN_WORKERS}.norefine"

  echo "=== Running generation for ${suite_name} (${run_name}) ==="
  python -m scripts.run_eval \
    --eval-queries "$eval_queries" \
    --out-dir "$OUT_ROOT" \
    --run-name "$run_name" \
    --mode "$MODE" \
    --concurrency "$GEN_WORKERS" \
    --parallel-backend "$PARALLEL_BACKEND" \
    --doc-index-path "$DOC_INDEX_PATH" \
    --query-timeout-s "$QUERY_TIMEOUT_S" \
    --query-max-retries "$QUERY_MAX_RETRIES"

  local run_dir
  run_dir="$(ls -td "${OUT_ROOT}/eval_run.${run_name}."* | head -n 1)"
  if [[ -z "$run_dir" ]]; then
    echo "Failed to resolve run dir for ${suite_name}" >&2
    exit 1
  fi

  echo "=== Scoring ${suite_name} (${run_dir}) ==="
  local score_cmd=(
    python -m scripts.score_eval
    --run-dir "$run_dir"
    --judge-workers "$JUDGE_WORKERS"
    --judge-context-chars "$JUDGE_CONTEXT_CHARS"
    --judge-timeout-s "$JUDGE_TIMEOUT_S"
    --judge-max-retries "$JUDGE_MAX_RETRIES"
  )
  if [[ -n "$kinds" ]]; then
    score_cmd+=(--kinds "$kinds")
  fi
  "${score_cmd[@]}"

  echo "${suite_name}=${run_dir}" >> "${OUT_ROOT}/${RUN_GROUP}.run_paths"
  echo "=== Summary: ${run_dir}/score_summary.json ==="
  cat "${run_dir}/score_summary.json"
  echo
}

run_and_score "single100" "$SINGLE_QUERIES"
run_and_score "multi60" "$MULTI_QUERIES"
if [[ "$RUN_OPEN_STRESS" == "1" ]]; then
  run_and_score "open200" "$OPEN_QUERIES" "open_ended"
fi

python - <<'PY'
import json
import os
from pathlib import Path

out_root = Path(os.environ["OUT_ROOT"])
run_group = os.environ["RUN_GROUP"]
paths_file = out_root / f"{run_group}.run_paths"
manifest = {
    "run_group": run_group,
    "out_root": str(out_root),
    "settings": {
        "mode": os.environ["MODE"],
        "gen_workers": int(os.environ["GEN_WORKERS"]),
        "judge_workers": int(os.environ["JUDGE_WORKERS"]),
        "query_timeout_s": float(os.environ["QUERY_TIMEOUT_S"]),
        "query_max_retries": int(os.environ["QUERY_MAX_RETRIES"]),
        "judge_context_chars": int(os.environ["JUDGE_CONTEXT_CHARS"]),
        "judge_timeout_s": float(os.environ["JUDGE_TIMEOUT_S"]),
        "judge_max_retries": int(os.environ["JUDGE_MAX_RETRIES"]),
        "doc_index_path": os.environ["DOC_INDEX_PATH"],
        "postgres_schema": os.environ["POSTGRES_SCHEMA"],
    },
    "runs": {},
}
if paths_file.exists():
    for line in paths_file.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        suite, path = line.split("=", 1)
        path_obj = Path(path.strip())
        score_path = path_obj / "score_summary.json"
        entry = {"run_dir": str(path_obj), "score_summary_path": str(score_path)}
        if score_path.exists():
            entry["score_summary"] = json.loads(score_path.read_text(encoding="utf-8"))
        manifest["runs"][suite.strip()] = entry

manifest_path = out_root / f"{run_group}.manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Wrote manifest: {manifest_path}")
PY
