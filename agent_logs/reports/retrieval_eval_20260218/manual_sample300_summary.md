# Retrieval Manual Sample (300) Summary

- source: `eval/results_revamp/full_suite/reduced_heuristics_full_retry4_retrieval_pool.sample300.codex_manual.csv`
- n_rows_total: `300`
- n_labeled: `300`
- positive_rate: `0.4167`

## By Kind

| kind | n | n_positive | positive_rate |
|---|---:|---:|---:|
| comparison | 55 | 44 | 0.8000 |
| distractor | 15 | 9 | 0.6000 |
| factual | 140 | 19 | 0.1357 |
| open_ended | 90 | 53 | 0.5889 |

## Membership

| bucket | n | n_positive | positive_rate |
|---|---:|---:|---:|
| both | 195 | 74 | 0.3795 |
| pre_only | 53 | 26 | 0.4906 |
| post_only | 52 | 25 | 0.4808 |
| neither | 0 | 0 | 0.0000 |

## Relevant Rank Movement (Rows Present in Pre and Post)

- n: `74`, promoted: `32`, demoted: `37`, same: `5`, avg_delta(post-pre): `0.0676`

### By Kind

| kind | n | promoted | demoted | same | avg_delta(post-pre) |
|---|---:|---:|---:|---:|---:|
| comparison | 17 | 6 | 10 | 1 | 3.4118 |
| distractor | 4 | 3 | 1 | 0 | -6.2500 |
| factual | 15 | 4 | 9 | 2 | 2.8000 |
| open_ended | 38 | 19 | 17 | 2 | -1.8421 |

## Top-k Relevance Rate (Sample-based)

| phase | k | n | n_positive | positive_rate |
|---|---:|---:|---:|---:|
| pre | 1 | 15 | 11 | 0.7333 |
| pre | 3 | 34 | 24 | 0.7059 |
| pre | 5 | 63 | 40 | 0.6349 |
| pre | 10 | 128 | 60 | 0.4688 |
| pre | 25 | 233 | 95 | 0.4077 |
| post | 1 | 18 | 11 | 0.6111 |
| post | 3 | 36 | 23 | 0.6389 |
| post | 5 | 64 | 37 | 0.5781 |
| post | 10 | 134 | 71 | 0.5299 |
| post | 25 | 247 | 99 | 0.4008 |

## Weak Label Alignment (subset with weak labels)

- n: `140`, tp: `19`, fp: `121`, tn: `0`, fn: `0`, accuracy: `0.1357`, precision_1: `0.1357`, recall_1: `1.0000`

