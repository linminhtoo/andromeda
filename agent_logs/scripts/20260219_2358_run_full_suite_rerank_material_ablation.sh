#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/_env.sh"

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
project_root="$(cd -- "$script_dir/../.." >/dev/null 2>&1 && pwd)"
cd "$project_root"

if [[ -d ".venv" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

INGEST_PROFILE="${INGEST_PROFILE:-eval_revamp_combined_512_20260217}"
CHUNK_DIR="${CHUNK_DIR:-chunked_512_64}"
POSTGRES_SCHEMA="${POSTGRES_SCHEMA:-$INGEST_PROFILE}"
DOC_INDEX_PATH="$(resolve_eval_doc_index_path "$project_root" "$INGEST_PROFILE" "$CHUNK_DIR")"
SINGLE_QUERIES="${SINGLE_QUERIES:-eval/eval_queries_combined512_single_balanced100_validated_tol05_20260217.jsonl}"
MULTI_QUERIES="${MULTI_QUERIES:-eval/eval_queries_combined512_multi_comparison60_validated_tol05_20260217.jsonl}"
OPEN_QUERIES="${OPEN_QUERIES:-eval/eval_queries_openended200_diverse_20260217_v1.jsonl}"
EXPECTED_INGEST_PROFILE_FOR_DEFAULT_QUERIES="${EXPECTED_INGEST_PROFILE_FOR_DEFAULT_QUERIES:-eval_revamp_combined_512_20260217}"
ALLOW_EVAL_PROFILE_MISMATCH="${ALLOW_EVAL_PROFILE_MISMATCH:-0}"

OUT_ROOT="${OUT_ROOT:-eval/results_revamp/full_suite_ablation}"
STAMP="$(date +"%Y%m%d_%H%M%S")"
RUN_GROUP="${RUN_GROUP:-full_suite_ablation_${STAMP}}"

MODE="${MODE:-normal}"
GEN_WORKERS="${GEN_WORKERS:-12}"
JUDGE_WORKERS="${JUDGE_WORKERS:-12}"
QUERY_TIMEOUT_S="${QUERY_TIMEOUT_S:-350}"
QUERY_MAX_RETRIES="${QUERY_MAX_RETRIES:-1}"
JUDGE_CONTEXT_CHARS="${JUDGE_CONTEXT_CHARS:-80000}"
JUDGE_TIMEOUT_S="${JUDGE_TIMEOUT_S:-350}"
JUDGE_MAX_RETRIES="${JUDGE_MAX_RETRIES:-1}"
PARALLEL_BACKEND="${PARALLEL_BACKEND:-thread}"

mkdir -p "$OUT_ROOT"

if [[ "$ALLOW_EVAL_PROFILE_MISMATCH" != "1" && "$DOC_INDEX_PATH" != *"/data/ingest_profiles/${INGEST_PROFILE}/"* ]]; then
  echo "Doc index path/profile mismatch detected." >&2
  echo "  INGEST_PROFILE=${INGEST_PROFILE}" >&2
  echo "  DOC_INDEX_PATH=${DOC_INDEX_PATH}" >&2
  echo "Set ALLOW_EVAL_PROFILE_MISMATCH=1 to bypass intentionally." >&2
  exit 1
fi

if [[ "$ALLOW_EVAL_PROFILE_MISMATCH" != "1" ]]; then
  if [[ "$SINGLE_QUERIES" == "eval/eval_queries_combined512_single_balanced100_validated_tol05_20260217.jsonl" && "$INGEST_PROFILE" != "$EXPECTED_INGEST_PROFILE_FOR_DEFAULT_QUERIES" ]]; then
    echo "Default single100 eval set expects profile ${EXPECTED_INGEST_PROFILE_FOR_DEFAULT_QUERIES}, got ${INGEST_PROFILE}." >&2
    echo "Set ALLOW_EVAL_PROFILE_MISMATCH=1 to bypass intentionally." >&2
    exit 1
  fi
  if [[ "$MULTI_QUERIES" == "eval/eval_queries_combined512_multi_comparison60_validated_tol05_20260217.jsonl" && "$INGEST_PROFILE" != "$EXPECTED_INGEST_PROFILE_FOR_DEFAULT_QUERIES" ]]; then
    echo "Default multi60 eval set expects profile ${EXPECTED_INGEST_PROFILE_FOR_DEFAULT_QUERIES}, got ${INGEST_PROFILE}." >&2
    echo "Set ALLOW_EVAL_PROFILE_MISMATCH=1 to bypass intentionally." >&2
    exit 1
  fi
fi

echo "Resolved eval profile: ${INGEST_PROFILE}"
echo "Resolved doc index path: ${DOC_INDEX_PATH}"
echo "Resolved postgres schema: ${POSTGRES_SCHEMA}"

export POSTGRES_SCHEMA
export FINRAG_INGEST_PROFILE="${FINRAG_INGEST_PROFILE:-$INGEST_PROFILE}"
export FINRAG_DOC_INDEX_PATH="$DOC_INDEX_PATH"
export FINRAG_ENABLE_NARRATIVE_QUERY_EXPANSION="${FINRAG_ENABLE_NARRATIVE_QUERY_EXPANSION:-0}"
export FINRAG_ENABLE_NARRATIVE_ASPECT_COVERAGE="${FINRAG_ENABLE_NARRATIVE_ASPECT_COVERAGE:-1}"
export FINRAG_ENABLE_ADAPTIVE_RETRIEVAL_BUDGET="${FINRAG_ENABLE_ADAPTIVE_RETRIEVAL_BUDGET:-1}"
export FINRAG_ENABLE_MMR_DIVERSITY="${FINRAG_ENABLE_MMR_DIVERSITY:-0}"

run_and_score() {
  local exp_name="$1"
  local suite_name="$2"
  local eval_queries="$3"
  local kinds="${4:-}"
  local enable_rerank_override="$5"

  local run_name="${RUN_GROUP}.${exp_name}.${suite_name}.${MODE}.tools${GEN_WORKERS}.norefine"

  local run_cmd=(
    python -m scripts.run_eval
    --eval-queries "$eval_queries"
    --out-dir "$OUT_ROOT"
    --run-name "$run_name"
    --mode "$MODE"
    --concurrency "$GEN_WORKERS"
    --parallel-backend "$PARALLEL_BACKEND"
    --doc-index-path "$DOC_INDEX_PATH"
    --query-timeout-s "$QUERY_TIMEOUT_S"
    --query-max-retries "$QUERY_MAX_RETRIES"
  )

  if [[ -n "$enable_rerank_override" ]]; then
    run_cmd+=(--enable-rerank "$enable_rerank_override")
  fi

  echo "=== Generation: ${exp_name} / ${suite_name} (${run_name}) ==="
  "${run_cmd[@]}"

  local run_dir
  run_dir="$(ls -td "${OUT_ROOT}/eval_run.${run_name}."* | head -n 1)"
  if [[ -z "$run_dir" ]]; then
    echo "Failed to resolve run dir for ${exp_name}/${suite_name}" >&2
    exit 1
  fi

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

  echo "=== Scoring: ${exp_name} / ${suite_name} (${run_dir}) ==="
  "${score_cmd[@]}"

  echo "${exp_name}.${suite_name}=${run_dir}" >> "${OUT_ROOT}/${RUN_GROUP}.run_paths"
}

run_experiment() {
  local exp_name="$1"
  local enable_rerank_override="$2"
  local material_cap="$3"

  export FINRAG_MAX_MATERIAL_POINTS="$material_cap"

  run_and_score "$exp_name" "single100" "$SINGLE_QUERIES" "" "$enable_rerank_override"
  run_and_score "$exp_name" "multi60" "$MULTI_QUERIES" "" "$enable_rerank_override"
  run_and_score "$exp_name" "open200" "$OPEN_QUERIES" "open_ended" "$enable_rerank_override"
}

# baseline: current best behavior (normal preset default rerank + cap=6)
run_experiment "baseline_best" "" "6"

# ablation 1: disable reranker
run_experiment "ablation_no_rerank" "0" "6"

# ablation 2: remove material-points cap while keeping baseline rerank behavior
run_experiment "ablation_no_material_cap" "" "0"

python - <<'PY'
import json
import os
from pathlib import Path

out_root = Path(os.environ.get("OUT_ROOT", "eval/results_revamp/full_suite_ablation"))
run_group = os.environ["RUN_GROUP"]
paths_file = out_root / f"{run_group}.run_paths"
manifest = {
    "run_group": run_group,
    "settings": {
        "mode": os.environ["MODE"],
        "gen_workers": int(os.environ["GEN_WORKERS"]),
        "judge_workers": int(os.environ["JUDGE_WORKERS"]),
        "query_timeout_s": float(os.environ["QUERY_TIMEOUT_S"]),
        "query_max_retries": int(os.environ["QUERY_MAX_RETRIES"]),
        "judge_context_chars": int(os.environ["JUDGE_CONTEXT_CHARS"]),
        "judge_timeout_s": float(os.environ["JUDGE_TIMEOUT_S"]),
        "judge_max_retries": int(os.environ["JUDGE_MAX_RETRIES"]),
        "postgres_schema": os.environ["POSTGRES_SCHEMA"],
        "doc_index_path": os.environ["FINRAG_DOC_INDEX_PATH"],
        "ingest_profile": os.environ.get("FINRAG_INGEST_PROFILE"),
    },
    "runs": {},
}

for line in paths_file.read_text(encoding="utf-8").splitlines():
    if "=" not in line:
        continue
    key, run_dir = line.split("=", 1)
    score_path = Path(run_dir.strip()) / "score_summary.json"
    item = {"run_dir": run_dir.strip(), "score_summary_path": str(score_path)}
    if score_path.exists():
        item["score_summary"] = json.loads(score_path.read_text(encoding="utf-8"))
    manifest["runs"][key.strip()] = item

manifest_path = out_root / f"{run_group}.manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Wrote manifest: {manifest_path}")
PY

echo "Completed run group: ${RUN_GROUP}"
echo "Manifest: ${OUT_ROOT}/${RUN_GROUP}.manifest.json"
