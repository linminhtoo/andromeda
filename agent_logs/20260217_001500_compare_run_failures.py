#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    out = []
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            t = line.strip()
            if not t:
                continue
            out.append(json.loads(t))
    return out


def judge_fail_map(scores: list[dict], judge_id: str) -> set[str]:
    out: set[str] = set()
    for row in scores:
        qid = row.get('query_id')
        if not qid:
            continue
        for j in row.get('judges', []):
            if j.get('judge_id') == judge_id and int(j.get('prediction', 0)) == 1:
                out.add(str(qid))
    return out


def main() -> None:
    run_a = Path('eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness_judgev2.20260216_231430')
    run_b = Path('eval/results_revamp/single/eval_run.single_holistic_normal_v17_tools8_norefine_revertprompt.20260216_233713')

    scores_a = load_jsonl(run_a / 'scores.jsonl')
    scores_b = load_jsonl(run_b / 'scores.jsonl')

    faith_a = judge_fail_map(scores_a, 'faithfulness_v1')
    faith_b = judge_fail_map(scores_b, 'faithfulness_v1')

    added = sorted(faith_b - faith_a)
    removed = sorted(faith_a - faith_b)

    print('run_a', run_a)
    print('run_b', run_b)
    print('faith_fail_a', len(faith_a))
    print('faith_fail_b', len(faith_b))
    print('added_failures_in_b', len(added))
    print('removed_failures_in_b', len(removed))
    if added:
        print('added_ids', added)
    if removed:
        print('removed_ids', removed)


if __name__ == '__main__':
    main()
