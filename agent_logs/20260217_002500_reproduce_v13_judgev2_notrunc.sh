#!/usr/bin/env bash
set -euo pipefail

cd /home/mlin/repos/z_scratch/financial-rag
source .venv/bin/activate
set -a
. ./.env
set +a

python - <<'PY'
from __future__ import annotations

import concurrent.futures
import shutil
import threading
from datetime import datetime
from pathlib import Path

from finrag.eval.io import dump_jsonl, load_jsonl
from finrag.eval.judges import get_judge_client
from finrag.eval.runner import save_json
from finrag.eval.schema import EvalGeneration, EvalQuery, EvalScore
from finrag.eval import scoring as scoring_mod

base_run = Path('eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch.20260216_224314')
stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
out_run = Path(f'eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness_judgev2_repro_notrunc.{stamp}')
out_run.mkdir(parents=True, exist_ok=True)

for name in ['eval_queries.jsonl', 'generations.jsonl', 'run_config.json', 'generation_summary.json']:
    shutil.copy2(base_run / name, out_run / name)

queries = load_jsonl(out_run / 'eval_queries.jsonl', EvalQuery)
generations = load_jsonl(out_run / 'generations.jsonl', EvalGeneration)
gens_by_id = {g.query_id: g for g in generations}

orig_build_context = scoring_mod.build_context

def build_context_notrunc(chunks, *, max_chars=65_000, prioritized_chunk_ids=None, max_chunk_text_chars=1_400, max_chunk_context_chars=900):
    return orig_build_context(
        chunks,
        max_chars=max_chars,
        prioritized_chunk_ids=prioritized_chunk_ids,
        max_chunk_text_chars=0,
        max_chunk_context_chars=0,
    )

scoring_mod.build_context = build_context_notrunc

thread_local = threading.local()

def score_query(q: EvalQuery) -> EvalScore:
    if not hasattr(thread_local, 'judge_llm'):
        thread_local.judge_llm = get_judge_client(provider='openai')
    return scoring_mod.score_one(q, gens_by_id.get(q.id), judge_llm=thread_local.judge_llm, judge_context_chars=80_000)

with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
    fut_to_idx = {ex.submit(score_query, q): i for i, q in enumerate(queries)}
    scored: list[EvalScore | None] = [None] * len(queries)
    for fut in concurrent.futures.as_completed(fut_to_idx):
        i = fut_to_idx[fut]
        scored[i] = fut.result()

scores = [s for s in scored if s is not None]
summary = scoring_mod.summarize(scores)

dump_jsonl(scores, out_run / 'scores.jsonl')
save_json(summary, out_run / 'score_summary.json')

print('RUN_DIR', out_run)
print('SUMMARY', summary)
PY
