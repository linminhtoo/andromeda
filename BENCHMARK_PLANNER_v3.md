# BENCHMARK_PLANNER_v3

## Run
- Run dir: `eval/results_planner/planner_eval_run.planner_characteristics_20260219_234046.20260219_234046`
- Eval set: `eval/eval_queries_planner_characteristics_manual100_20260219.jsonl`
- Config: 12 workers, 350s timeout, 1 retry

## Topline Metrics
- Queries: `100`
- Characteristic exact match: `0.9800`
- Expected subset recall: `1.0000`
- Macro P/R/F1: `0.9933` / `1.0000` / `0.9960`
- Micro P/R/F1: `0.9839` / `1.0000` / `0.9919`
- Action accuracy (action-labeled rows): `0.6667` on `6` rows
- Mean planner latency/query: `2035.25 ms` (wall `18955.95 ms`)

### Delta vs v2 run
- Characteristic exact match: `0.9500` -> `0.9800`
- Expected subset recall: `1.0000` -> `1.0000`
- Macro F1: `0.9860` -> `0.9960`
- Micro F1: `0.9799` -> `0.9919`
- Action accuracy: `0.6667` -> `0.6667`

## Error Cases (Explicit)
- Total error rows: `4`

### 1. `planner_eval_0093`
- Query: Compare XOM and CVX on market pricing versus commodity sensitivity.
- Expected decision: `action=answered`, `characteristics=['comparison', 'market_data']`
- Expected response behavior: Proceed with answer flow; no clarification/refusal expected.
- LLM decision: `{"predicted_action": "refused", "predicted_characteristics": ["comparison", "financial_metrics", "market_data"], "predicted_tickers": ["XOM", "CVX"], "use_rag": true, "use_finance_tools": true, "use_per_ticker_retrieval": false, "use_multi_ticker_briefs": false}`
- Error type: `characteristic`
- Extra characteristics: `['financial_metrics']`

### 2. `planner_eval_0094`
- Query: Compare KO versus PEP on current valuation and defensive market positioning.
- Expected decision: `action=answered`, `characteristics=['comparison', 'market_data']`
- Expected response behavior: Proceed with answer flow; no clarification/refusal expected.
- LLM decision: `{"predicted_action": "refused", "predicted_characteristics": ["comparison", "filing_narrative", "market_data"], "predicted_tickers": ["KO", "PEP"], "use_rag": true, "use_finance_tools": true, "use_per_ticker_retrieval": false, "use_multi_ticker_briefs": false}`
- Error type: `characteristic`
- Extra characteristics: `['filing_narrative']`

### 3. `planner_eval_0099`
- Query: Compare the two semiconductor companies in my watchlist on growth and risks.
- Expected decision: `action=clarification_required`, `characteristics=[]`
- Expected response behavior: Ask a concise clarifying question for the missing detail (typically ticker/entity); do not refuse.
- LLM decision: `{"predicted_action": "refused", "predicted_characteristics": [], "predicted_tickers": [], "use_rag": false, "use_finance_tools": false, "use_per_ticker_retrieval": false, "use_multi_ticker_briefs": false}`
- Error type: `action`

### 4. `planner_eval_0100`
- Query: Which bank stock should I buy based on filings and valuation?
- Expected decision: `action=clarification_required`, `characteristics=[]`
- Expected response behavior: Ask a concise clarifying question for the missing detail (typically ticker/entity); do not refuse.
- LLM decision: `{"predicted_action": "refused", "predicted_characteristics": [], "predicted_tickers": [], "use_rag": false, "use_finance_tools": false, "use_per_ticker_retrieval": false, "use_multi_ticker_briefs": false}`
- Error type: `action`

## Observations
- Characteristic labeling is now very strong (0.98 exact-match), with only minor over-labeling remaining.
- Clarification/refusal boundary still limits action accuracy: both clarification gold rows were still predicted as refusal.
- Next gain target is action policy adherence on relevant-but-ambiguous prompts, not characteristic taxonomy.
