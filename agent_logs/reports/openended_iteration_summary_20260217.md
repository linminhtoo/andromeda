# Open-Ended Iteration Summary (2026-02-17)

| Iteration | Strategy | n_ok | n_err | Faithfulness Fail | Helpfulness Fail | Avg Total ms | Wall ms |
|---|---|---:|---:|---:|---:|---:|---:|
| iter1 | baseline diverse open-ended set | 100 | 0 | 22.00% | 0.00% | 76653 | 664464 |
| iter2 | period-scope guardrail prompt additions | 100 | 0 | 26.00% | 0.00% | 78127 | 680486 |
| iter3 | expanded narrative intent + diversified retrieval queries | 100 | 0 | 18.00% | 0.00% | 74754 | 663397 |
| iter4 | narrative draft temperature=0 (ablation) | 99 | 1 | 23.23% | 0.00% | 84880 | 803361 |

Best faithfulness in this series: `iter3`.
