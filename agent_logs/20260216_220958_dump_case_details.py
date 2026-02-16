#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_jsonl(path: Path):
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            t=line.strip()
            if t:
                yield json.loads(t)


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument('--run-dir', required=True)
    ap.add_argument('--query-id', required=True)
    ap.add_argument('--chunks', type=int, default=8)
    ap.add_argument('--chars', type=int, default=800)
    args=ap.parse_args()

    run=Path(args.run_dir).expanduser().resolve()
    q=None
    for row in load_jsonl(run/'eval_queries.jsonl'):
        if row.get('id')==args.query_id:
            q=row
            break
    g=None
    for row in load_jsonl(run/'generations.jsonl'):
        if row.get('query_id')==args.query_id:
            g=row
            break
    s=None
    for row in load_jsonl(run/'scores.jsonl'):
        if row.get('query_id')==args.query_id:
            s=row
            break

    if q is None or g is None or s is None:
        raise SystemExit('query_id not found')

    print('QUERY', q['id'])
    print('KIND', q['kind'])
    print('QUESTION', q['question'])
    print('\nJUDGES')
    for j in s.get('judges', []):
        print('-', j.get('judge_id'), 'prediction=', j.get('prediction'))
        expl=(j.get('explanation') or '').replace('\n',' ')
        print('  ', expl[:500])

    print('\nFINAL ANSWER')
    print((g.get('final_answer') or '')[:5000])

    print('\nTOP CHUNKS')
    for i,ch in enumerate((g.get('top_chunks') or [])[:args.chunks],1):
        print(f"\n[{i}] doc={ch.get('doc_id')} chunk={ch.get('chunk_id')} score={ch.get('score')}")
        text=(ch.get('text') or ch.get('preview') or '')
        text=' '.join(str(text).split())
        print(text[:args.chars])


if __name__=='__main__':
    main()
