#!/bin/bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

# NOTE: export same env vars as launch_app.sh
# NOTE: rmbr to set OPENAI_EMBED_BASE_URL and OPENAI_CHAT_BASE_URL in .env
export OPENAI_CHAT_MODEL="Qwen/Qwen3-VL-32B-Instruct-FP8"
export OPENAI_EMBED_MODEL="BAAI/bge-m3"
export RERANKER_MODEL="BAAI/bge-reranker-v2-m3"

export MILVUS_COLLECTION_NAME="with_llm_context_27_12_25"
export MILVUS_DENSE_EMBEDDING="llm"
export MILVUS_SPARSE_EMBEDDING="bm25"
export CONTEXT_STRATEGY="neighbors"
export CONTEXT_WINDOW=8

export MILVUS_PATH="/home/mlin/repos/z_scratch/financial-rag/data/sec_filings_md_v5/chunked_1024_128/milvus.db"
export BM25_PATH="/home/mlin/repos/z_scratch/financial-rag/data/sec_filings_md_v5/chunked_1024_128/bm25.pkl"
export FINRAG_DOC_INDEX_PATH="/home/mlin/repos/z_scratch/financial-rag/data/sec_filings_md_v5/chunked_1024_128/doc_index.jsonl"

# temporary hotfix to use legacy BM25 while we rebuild our Milvus collections with built-in BM25
export MILVUS_LEGACY_BM25=true

# ps aux | grep milvus_lite/lib/milvus
# 3 hours down to 25 mins by using 8 parallel workers
now=$(date +"%Y%m%d_%H%M%S")
mkdir -p logs/
python3 -m scripts.run_eval \
  --eval-queries ./eval/eval_queries_v2.jsonl \
  --out-dir ./eval/results_v2/${now} \
  --run-name legacy_baseline_v2 \
  --index-dir ./data/sec_filings_md_v5/chunked_1024_128 \
  --mode thinking \
  --concurrency 8 \
  --gpu-ids 0 1 \
  2>&1 | tee logs/run_eval_${now}.log

# TODO: run again with smaller model Qwen 4B Instruct FP8 to force failure cases for better judge calibration

# python3 -m scripts.run_eval \
#   --eval-queries ./eval/eval_queries.jsonl \
#   --out-dir ./eval/results/${now} \
#   --run-name legacy_baseline_8workers \
#   --index-dir ./data/sec_filings_md_v5/chunked_1024_128 \
#   --mode thinking \
#   --concurrency 8 \
#   --gpu-ids 0 1 \
#   2>&1 | tee logs/run_eval_${now}.log
