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

export HOME=/tmp

# Reuse historical, reproducible scripts to keep lineage with LOGBOOK entries.
bash agent_logs/scripts/eval/20260217_042950_build_combined_profile_chunk512.sh
bash agent_logs/scripts/eval/20260217_043020_generate_eval_set_combined512_validated_tol05.sh
bash agent_logs/scripts/eval/20260217_043130_build_eval100_subsets_combined512_tol05.sh
bash agent_logs/scripts/eval/20260217_235950_generate_openended200_diverse_v1.sh

echo "Prepared assets:"
echo "  - data/ingest_profiles/eval_revamp_combined_512_20260217/sec_filings_md_secparser/chunked_512_64/doc_index.jsonl"
echo "  - eval/eval_queries_combined512_single_balanced100_validated_tol05_20260217.jsonl"
echo "  - eval/eval_queries_combined512_multi_comparison60_validated_tol05_20260217.jsonl"
echo "  - eval/eval_queries_openended200_diverse_20260217_v1.jsonl"
