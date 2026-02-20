#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
mkdir -p agent_logs/reports/retrieval_eval_20260218
export PYTHONPATH=src
# hard cap to avoid indefinite hangs
/usr/bin/timeout 500s python - <<'PY'
from __future__ import annotations
import json
import time
from pathlib import Path

from dotenv import load_dotenv

from andromeda.llm.generation_controls import resolve_generation_settings
from andromeda.main import get_rag_service

load_dotenv(Path('.env'))
query = "What was LITE's net income in its 10-Q filed 2026-02-04?"
settings = resolve_generation_settings(mode='normal')
service = get_rag_service()

attempts = []
for i in range(2):
    start = time.perf_counter()
    payload = {
        'attempt': i + 1,
        'query': query,
        'mode': settings.mode,
        'top_k_retrieve': settings.top_k_retrieve,
        'top_k_rerank': settings.top_k_rerank,
        'draft_max_tokens': settings.draft_max_tokens,
        'final_max_tokens': settings.final_max_tokens,
        'answering_effort': settings.answering_effort.value,
    }
    try:
        response = service.answer_question(query, settings)
        elapsed = time.perf_counter() - start
        payload.update(
            {
                'ok': True,
                'latency_s': elapsed,
                'tool_trace_len': len(response.tool_trace),
                'tool_results_len': len(response.tool_results),
                'top_chunks_len': len(response.top_chunks),
                'answer_preview': (response.final_answer or '')[:220],
            }
        )
    except Exception as exc:  # pragma: no cover - runtime probe path
        elapsed = time.perf_counter() - start
        payload.update({'ok': False, 'latency_s': elapsed, 'error': str(exc)})
    attempts.append(payload)

out = {
    'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
    'attempts': attempts,
}
out_path = Path('agent_logs/reports/retrieval_eval_20260218/lite_query_isolated_latency.json')
out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print(json.dumps(out, indent=2, ensure_ascii=False))
print(f'Wrote: {out_path}')
PY
