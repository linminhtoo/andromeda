#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
mkdir -p agent_logs/reports/retrieval_eval_20260218
python - <<'PY'
from __future__ import annotations
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

in_path = Path('eval/results_revamp/full_suite/reduced_heuristics_full_retry4_retrieval_pool.sample300.codex_manual.csv')
out_json = Path('agent_logs/reports/retrieval_eval_20260218/manual_sample300_summary.json')
out_md = Path('agent_logs/reports/retrieval_eval_20260218/manual_sample300_summary.md')

rows = []
with in_path.open('r', encoding='utf-8', newline='') as f:
    for row in csv.DictReader(f):
        rows.append(row)

def to_i(v: str) -> int | None:
    t = (v or '').strip()
    if t in {'0','1'}:
        return int(t)
    return None

def to_rank(v: str) -> int | None:
    t = (v or '').strip()
    if not t:
        return None
    try:
        return int(float(t))
    except Exception:
        return None

labeled = []
for r in rows:
    hr = to_i(r.get('human_relevance', ''))
    if hr is None:
        continue
    r2 = dict(r)
    r2['human_relevance_i'] = hr
    r2['in_pre_i'] = to_i(r.get('in_pre','')) or 0
    r2['in_post_i'] = to_i(r.get('in_post','')) or 0
    r2['rank_pre_i'] = to_rank(r.get('rank_pre',''))
    r2['rank_post_i'] = to_rank(r.get('rank_post',''))
    labeled.append(r2)

summary: dict[str, object] = {}
summary['n_rows_total'] = len(rows)
summary['n_labeled'] = len(labeled)
summary['positive_count'] = sum(r['human_relevance_i'] for r in labeled)
summary['positive_rate'] = (summary['positive_count'] / len(labeled)) if labeled else 0.0

# By kind
kind_counts = Counter(r.get('kind','') for r in labeled)
kind_pos = Counter()
for r in labeled:
    if r['human_relevance_i'] == 1:
        kind_pos[r.get('kind','')] += 1
summary['by_kind'] = {
    k: {
        'n': kind_counts[k],
        'n_positive': kind_pos[k],
        'positive_rate': (kind_pos[k] / kind_counts[k]) if kind_counts[k] else 0.0,
    }
    for k in sorted(kind_counts)
}

# By run
run_counts = Counter(r.get('run_name','') for r in labeled)
run_pos = Counter()
for r in labeled:
    if r['human_relevance_i'] == 1:
        run_pos[r.get('run_name','')] += 1
summary['by_run'] = {
    k: {
        'n': run_counts[k],
        'n_positive': run_pos[k],
        'positive_rate': (run_pos[k] / run_counts[k]) if run_counts[k] else 0.0,
    }
    for k in sorted(run_counts)
}

# Membership (pre/post)
membership_map = {
    (1,1): 'both',
    (1,0): 'pre_only',
    (0,1): 'post_only',
    (0,0): 'neither',
}
member_counts = Counter()
member_pos = Counter()
for r in labeled:
    key = membership_map[(r['in_pre_i'], r['in_post_i'])]
    member_counts[key] += 1
    if r['human_relevance_i'] == 1:
        member_pos[key] += 1
summary['by_membership'] = {
    k: {
        'n': member_counts[k],
        'n_positive': member_pos[k],
        'positive_rate': (member_pos[k] / member_counts[k]) if member_counts[k] else 0.0,
    }
    for k in ['both', 'pre_only', 'post_only', 'neither']
}

# Rank movement on relevant rows present in both
relevant_both = [
    r for r in labeled
    if r['human_relevance_i'] == 1 and r['rank_pre_i'] is not None and r['rank_post_i'] is not None
]
promoted = 0
same = 0
demoted = 0
deltas = []
for r in relevant_both:
    delta = r['rank_post_i'] - r['rank_pre_i']
    deltas.append(delta)
    if delta < 0:
        promoted += 1
    elif delta > 0:
        demoted += 1
    else:
        same += 1
summary['relevant_rank_movement_both'] = {
    'n': len(relevant_both),
    'promoted': promoted,
    'demoted': demoted,
    'same_rank': same,
    'avg_delta_rank_post_minus_pre': (sum(deltas)/len(deltas)) if deltas else 0.0,
}

# Rank movement by kind (relevant rows present in both)
movement_by_kind = {}
for kind in sorted({r.get('kind', '') for r in relevant_both}):
    sub = [r for r in relevant_both if r.get('kind', '') == kind]
    k_promoted = 0
    k_same = 0
    k_demoted = 0
    k_deltas = []
    for r in sub:
        delta = r['rank_post_i'] - r['rank_pre_i']
        k_deltas.append(delta)
        if delta < 0:
            k_promoted += 1
        elif delta > 0:
            k_demoted += 1
        else:
            k_same += 1
    movement_by_kind[kind] = {
        'n': len(sub),
        'promoted': k_promoted,
        'demoted': k_demoted,
        'same_rank': k_same,
        'avg_delta_rank_post_minus_pre': (sum(k_deltas) / len(k_deltas)) if k_deltas else 0.0,
    }
summary['relevant_rank_movement_both_by_kind'] = movement_by_kind

# Top-k relevance slices (sample-estimate)

def topk_slice(phase: str, k: int) -> tuple[int,int,float]:
    assert phase in {'pre','post'}
    key = 'rank_pre_i' if phase == 'pre' else 'rank_post_i'
    sub = [r for r in labeled if r[key] is not None and r[key] <= k]
    n = len(sub)
    pos = sum(r['human_relevance_i'] for r in sub)
    rate = (pos / n) if n else 0.0
    return n, pos, rate

summary['topk_relevance_rate_sample'] = {'pre': {}, 'post': {}}
for phase in ['pre','post']:
    for k in [1,3,5,10,25]:
        n, pos, rate = topk_slice(phase, k)
        summary['topk_relevance_rate_sample'][phase][f'k{k}'] = {
            'n': n,
            'n_positive': pos,
            'positive_rate': rate,
        }

# Weak-label coverage and confusion at threshold 0.5
usable = []
for r in labeled:
    w = (r.get('weak_relevance','') or '').strip()
    try:
        wf = float(w)
    except Exception:
        continue
    pred = 1 if wf >= 0.5 else 0
    usable.append((r['human_relevance_i'], pred))

tp = sum(1 for y,p in usable if y==1 and p==1)
fp = sum(1 for y,p in usable if y==0 and p==1)
tn = sum(1 for y,p in usable if y==0 and p==0)
fn = sum(1 for y,p in usable if y==1 and p==0)
precision = tp / (tp + fp) if (tp + fp) else 0.0
recall = tp / (tp + fn) if (tp + fn) else 0.0
acc = (tp + tn) / len(usable) if usable else 0.0
summary['weak_label_alignment_subset'] = {
    'n': len(usable),
    'tp': tp,
    'fp': fp,
    'tn': tn,
    'fn': fn,
    'accuracy': acc,
    'precision_1': precision,
    'recall_1': recall,
}

out_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

lines = []
lines.append('# Retrieval Manual Sample (300) Summary')
lines.append('')
lines.append(f"- source: `{in_path}`")
lines.append(f"- n_rows_total: `{summary['n_rows_total']}`")
lines.append(f"- n_labeled: `{summary['n_labeled']}`")
lines.append(f"- positive_rate: `{summary['positive_rate']:.4f}`")
lines.append('')
lines.append('## By Kind')
lines.append('')
lines.append('| kind | n | n_positive | positive_rate |')
lines.append('|---|---:|---:|---:|')
for kind, payload in summary['by_kind'].items():
    lines.append(f"| {kind} | {payload['n']} | {payload['n_positive']} | {payload['positive_rate']:.4f} |")
lines.append('')
lines.append('## Membership')
lines.append('')
lines.append('| bucket | n | n_positive | positive_rate |')
lines.append('|---|---:|---:|---:|')
for bucket, payload in summary['by_membership'].items():
    lines.append(f"| {bucket} | {payload['n']} | {payload['n_positive']} | {payload['positive_rate']:.4f} |")
lines.append('')
rm = summary['relevant_rank_movement_both']
lines.append('## Relevant Rank Movement (Rows Present in Pre and Post)')
lines.append('')
lines.append(
    f"- n: `{rm['n']}`, promoted: `{rm['promoted']}`, demoted: `{rm['demoted']}`, same: `{rm['same_rank']}`, avg_delta(post-pre): `{rm['avg_delta_rank_post_minus_pre']:.4f}`"
)
lines.append('')
lines.append('### By Kind')
lines.append('')
lines.append('| kind | n | promoted | demoted | same | avg_delta(post-pre) |')
lines.append('|---|---:|---:|---:|---:|---:|')
for kind, payload in summary['relevant_rank_movement_both_by_kind'].items():
    lines.append(
        f"| {kind} | {payload['n']} | {payload['promoted']} | {payload['demoted']} | "
        f"{payload['same_rank']} | {payload['avg_delta_rank_post_minus_pre']:.4f} |"
    )
lines.append('')
lines.append('## Top-k Relevance Rate (Sample-based)')
lines.append('')
lines.append('| phase | k | n | n_positive | positive_rate |')
lines.append('|---|---:|---:|---:|---:|')
for phase in ['pre','post']:
    for k in ['k1','k3','k5','k10','k25']:
        p = summary['topk_relevance_rate_sample'][phase][k]
        lines.append(f"| {phase} | {k[1:]} | {p['n']} | {p['n_positive']} | {p['positive_rate']:.4f} |")
lines.append('')
wa = summary['weak_label_alignment_subset']
lines.append('## Weak Label Alignment (subset with weak labels)')
lines.append('')
lines.append(
    f"- n: `{wa['n']}`, tp: `{wa['tp']}`, fp: `{wa['fp']}`, tn: `{wa['tn']}`, fn: `{wa['fn']}`, accuracy: `{wa['accuracy']:.4f}`, precision_1: `{wa['precision_1']:.4f}`, recall_1: `{wa['recall_1']:.4f}`"
)
lines.append('')
out_md.write_text('\n'.join(lines) + '\n', encoding='utf-8')

print('Wrote', out_json)
print('Wrote', out_md)
print(json.dumps(summary, indent=2, ensure_ascii=False))
PY
