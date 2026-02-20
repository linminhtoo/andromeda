# BENCHMARK_PLANNER_v2

## Run
- Run dir: `eval/results_planner/planner_eval_run.planner_characteristics_20260219_215722.20260219_215723`
- Eval set: `eval/eval_queries_planner_characteristics_manual100_20260219.jsonl` (clarification rows updated to `expected_characteristics=[]`)
- Runtime policy: `clarification_required` = relevant-but-ambiguous, `refused` = out-of-scope/irrelevant.

## Topline Metrics
- Queries: `100`
- Characteristic exact match: `0.9500`
- Expected subset recall: `1.0000`
- Macro P/R/F1: `0.9783` / `1.0000` / `0.9860`
- Micro P/R/F1: `0.9606` / `1.0000` / `0.9799`
- Action accuracy (action-labeled rows only): `0.6667` on `6` rows
- Mean planner latency/query: `2005.75 ms` (wall `18415.24 ms`)

### Delta vs previous synced run (20260219_214202)
- Characteristic exact match: `0.9200` -> `0.9500`
- Expected subset recall: `0.9600` -> `1.0000`
- Macro F1: `0.9493` -> `0.9860`
- Micro F1: `0.9486` -> `0.9799`
- Action accuracy: `0.6667` -> `0.6667`

## Error Cases (Explicit)
- Total error rows: `7`

### 1. `planner_eval_0009`
- Query: What is AMZN's current free-cash-flow yield?
- Expected decision: `action=answered`, `characteristics=['market_data']`
- Expected response behavior: Proceed with `answer` flow (no clarification/refusal expected).
- LLM decision: `{"predicted_action": "refused", "predicted_characteristics": ["financial_metrics", "market_data"], "predicted_tickers": ["AMZN"], "use_rag": false, "use_finance_tools": true, "use_per_ticker_retrieval": false, "use_multi_ticker_briefs": false}`
- Error type: `characteristic`
- Extra characteristics: `['financial_metrics']`

### 2. `planner_eval_0018`
- Query: How volatile has AMD been recently compared to its history?
- Expected decision: `action=answered`, `characteristics=['market_data']`
- Expected response behavior: Proceed with `answer` flow (no clarification/refusal expected).
- LLM decision: `{"predicted_action": "answered", "predicted_characteristics": ["financial_metrics", "market_data"], "predicted_tickers": ["AMD"], "use_rag": true, "use_finance_tools": true, "use_per_ticker_retrieval": false, "use_multi_ticker_briefs": false}`
- Error type: `characteristic`
- Extra characteristics: `['financial_metrics']`

### 3. `planner_eval_0021`
- Query: How has GOOGL performed relative to the Nasdaq recently?
- Expected decision: `action=answered`, `characteristics=['market_data']`
- Expected response behavior: Proceed with `answer` flow (no clarification/refusal expected).
- LLM decision: `{"predicted_action": "answered", "predicted_characteristics": ["comparison", "market_data"], "predicted_tickers": ["GOOGL"], "use_rag": false, "use_finance_tools": true, "use_per_ticker_retrieval": false, "use_multi_ticker_briefs": false}`
- Error type: `characteristic`
- Extra characteristics: `['comparison']`

### 4. `planner_eval_0093`
- Query: Compare XOM and CVX on market pricing versus commodity sensitivity.
- Expected decision: `action=answered`, `characteristics=['comparison', 'market_data']`
- Expected response behavior: Proceed with `answer` flow (no clarification/refusal expected).
- LLM decision: `{"predicted_action": "refused", "predicted_characteristics": ["comparison", "financial_metrics", "market_data"], "predicted_tickers": ["XOM", "CVX"], "use_rag": true, "use_finance_tools": true, "use_per_ticker_retrieval": false, "use_multi_ticker_briefs": false}`
- Error type: `characteristic`
- Extra characteristics: `['financial_metrics']`

### 5. `planner_eval_0094`
- Query: Compare KO versus PEP on current valuation and defensive market positioning.
- Expected decision: `action=answered`, `characteristics=['comparison', 'market_data']`
- Expected response behavior: Proceed with `answer` flow (no clarification/refusal expected).
- LLM decision: `{"predicted_action": "refused", "predicted_characteristics": ["comparison", "filing_narrative", "market_data"], "predicted_tickers": ["KO", "PEP"], "use_rag": true, "use_finance_tools": true, "use_per_ticker_retrieval": false, "use_multi_ticker_briefs": false}`
- Error type: `characteristic`
- Extra characteristics: `['filing_narrative']`

### 6. `planner_eval_0099`
- Query: Compare the two semiconductor companies in my watchlist on growth and risks.
- Expected decision: `action=clarification_required`, `characteristics=[]`
- Expected response behavior: Ask a concise clarification for missing identifiers (usually ticker symbols). Do not refuse; keep the request in-scope.
- LLM decision: `{"predicted_action": "refused", "predicted_characteristics": [], "predicted_tickers": [], "use_rag": false, "use_finance_tools": false, "use_per_ticker_retrieval": false, "use_multi_ticker_briefs": false}`
- Error type: `action`

### 7. `planner_eval_0100`
- Query: Which bank stock should I buy based on filings and valuation?
- Expected decision: `action=clarification_required`, `characteristics=[]`
- Expected response behavior: Ask a concise clarification for missing identifiers (usually ticker symbols). Do not refuse; keep the request in-scope.
- LLM decision: `{"predicted_action": "refused", "predicted_characteristics": [], "predicted_tickers": [], "use_rag": false, "use_finance_tools": false, "use_per_ticker_retrieval": false, "use_multi_ticker_briefs": false}`
- Error type: `action`

## Notes
- Clarification vs refusal boundary is now explicit in prompt and eval labels, but the planner still refuses the two ambiguous comparison queries (`planner_eval_0099`, `planner_eval_0100`).
- Most remaining errors are over-labeling (`financial_metrics` or `filing_narrative` added on top of otherwise correct labels).
- Per the new policy, clarification rows intentionally have empty characteristics and are judged on action correctness.
