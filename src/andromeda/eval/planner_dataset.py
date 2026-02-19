from __future__ import annotations

from andromeda.eval.planner_schema import PlannerEvalAction, PlannerEvalCharacteristic, PlannerEvalQuery


def build_manual_planner_eval_queries() -> list[PlannerEvalQuery]:
    """
    Build a manually curated, non-LLM-generated planner eval set.
    """

    rows: list[PlannerEvalQuery] = []

    def add(
        *,
        question: str,
        characteristics: list[PlannerEvalCharacteristic],
        explicit_tickers: list[str],
        tags: list[str],
        expected_action: PlannerEvalAction | None = None,
        rationale: str,
    ) -> None:
        """
        Append one planner eval row with stable id assignment.
        """

        rows.append(
            PlannerEvalQuery(
                id=f"planner_eval_{len(rows) + 1:04d}",
                question=question,
                expected_characteristics=characteristics,
                expected_action=expected_action,
                explicit_tickers=explicit_tickers,
                tags=tags,
                rationale=rationale,
            )
        )

    # Group A: market_data + simple_numeric (14)
    market_simple = [
        ("What is AAPL's market cap right now?", ["AAPL"]),
        ("What's NVDA's current P/E ratio?", ["NVDA"]),
        ("Give me MSFT's latest stock price.", ["MSFT"]),
        ("What is TSLA's current enterprise value?", ["TSLA"]),
        ("What's AMD's current EV/EBITDA multiple?", ["AMD"]),
        ("What is JPM's latest price-to-book ratio?", ["JPM"]),
        ("What's UNH's market cap now?", ["UNH"]),
        ("Give me META's latest 52-week high and low.", ["META"]),
        ("What is AMZN's current free-cash-flow yield?", ["AMZN"]),
        ("What is GOOGL's current dividend yield?", ["GOOGL"]),
        ("What's XOM's current beta?", ["XOM"]),
        ("What is ORCL's current price-to-sales ratio?", ["ORCL"]),
        ("What's LITE's latest short interest percentage?", ["LITE"]),
        ("What is COST's current forward P/E?", ["COST"]),
    ]
    for question, tickers in market_simple:
        add(
            question=question,
            characteristics=[PlannerEvalCharacteristic.MARKET_DATA, PlannerEvalCharacteristic.SIMPLE_NUMERIC],
            explicit_tickers=tickers,
            tags=["market_data", "simple_numeric"],
            rationale="Direct point-in-time market metric lookup.",
        )

    # Group B: market_data only (8)
    market_contextual = [
        ("How has NVDA traded over the last month?", ["NVDA"]),
        ("Summarize recent price action for MSFT.", ["MSFT"]),
        ("Any major market-moving news for TSLA this week?", ["TSLA"]),
        ("How volatile has AMD been recently compared to its history?", ["AMD"]),
        ("Give me a quick market performance recap for AAPL in the last quarter.", ["AAPL"]),
        ("What are current analyst sentiment trends for META stock?", ["META"]),
        ("How has GOOGL performed relative to the Nasdaq recently?", ["GOOGL"]),
        ("Summarize market momentum signals for AMZN right now.", ["AMZN"]),
    ]
    for question, tickers in market_contextual:
        add(
            question=question,
            characteristics=[PlannerEvalCharacteristic.MARKET_DATA],
            explicit_tickers=tickers,
            tags=["market_data", "contextual"],
            rationale="Market-centric request without strict numeric single-value target.",
        )

    # Group C: financial_metrics + period_scoped + simple_numeric (20)
    metric_period_simple = [
        ("What was AAPL's net income in 2025?", ["AAPL"]),
        ("What was MSFT's total revenue in FY2024?", ["MSFT"]),
        ("What was NVDA's gross margin in Q2 2025?", ["NVDA"]),
        ("What was AMD's operating income in 2024?", ["AMD"]),
        ("What was TSLA's free cash flow in 2025?", ["TSLA"]),
        ("What was GOOGL's EPS in Q1 2025?", ["GOOGL"]),
        ("What was AMZN's operating cash flow in 2024?", ["AMZN"]),
        ("What were META's R&D expenses in 2025?", ["META"]),
        ("What was JPM's CET1 ratio in 2024?", ["JPM"]),
        ("What was BAC's net interest income in Q4 2025?", ["BAC"]),
        ("What was XOM's capital expenditure in 2025?", ["XOM"]),
        ("What was CVX's upstream earnings in 2024?", ["CVX"]),
        ("What was LITE's net income in the quarter ended 2025-12-27?", ["LITE"]),
        ("What was INTC's gross margin in 2025?", ["INTC"]),
        ("What was ORCL's deferred revenue balance in 2024?", ["ORCL"]),
        ("What was CRM's subscription revenue in FY2025?", ["CRM"]),
        ("What was ADBE's operating margin in 2025?", ["ADBE"]),
        ("What was QCOM's handset revenue in Q3 2025?", ["QCOM"]),
        ("What was AVGO's adjusted EBITDA in 2025?", ["AVGO"]),
        ("What was MRVL's free cash flow in fiscal 2025?", ["MRVL"]),
    ]
    for question, tickers in metric_period_simple:
        add(
            question=question,
            characteristics=[
                PlannerEvalCharacteristic.FINANCIAL_METRICS,
                PlannerEvalCharacteristic.PERIOD_SCOPED,
                PlannerEvalCharacteristic.SIMPLE_NUMERIC,
            ],
            explicit_tickers=tickers,
            tags=["financial_metrics", "period_scoped", "simple_numeric"],
            rationale="Single metric lookup for an explicit reporting period.",
        )

    # Group D: financial_metrics + period_scoped (8)
    metric_period_analytic = [
        ("How did AAPL's gross margin trend from 2023 to 2025?", ["AAPL"]),
        ("Analyze MSFT revenue growth by year from 2022 through 2025.", ["MSFT"]),
        ("Break down NVDA operating margin trend across the last 6 quarters.", ["NVDA"]),
        ("Discuss how AMD cash flow quality changed between 2023 and 2025.", ["AMD"]),
        ("How has TSLA's automotive gross margin evolved over recent quarters?", ["TSLA"]),
        ("Review GOOGL's capex and free cash flow trend over the last three years.", ["GOOGL"]),
        ("How did AMZN's North America segment margin move in 2024 versus 2025?", ["AMZN"]),
        ("Evaluate META's operating expense trajectory across the last eight quarters.", ["META"]),
    ]
    for question, tickers in metric_period_analytic:
        add(
            question=question,
            characteristics=[PlannerEvalCharacteristic.FINANCIAL_METRICS, PlannerEvalCharacteristic.PERIOD_SCOPED],
            explicit_tickers=tickers,
            tags=["financial_metrics", "period_scoped", "analysis"],
            rationale="Financial statement analysis over explicit time windows, not single-point numeric lookup.",
        )

    # Group E: filing_narrative (16)
    narrative_only = [
        ("From AAPL filings, summarize management's strategic priorities.", ["AAPL"]),
        ("What key execution risks does MSFT highlight in its latest filings?", ["MSFT"]),
        ("Summarize NVDA's stated long-term growth drivers from filings.", ["NVDA"]),
        ("What competitive pressures does AMD discuss in risk factors?", ["AMD"]),
        ("Explain TSLA's supply-chain risks based on filing language.", ["TSLA"]),
        ("What are GOOGL's key regulatory risk themes in filings?", ["GOOGL"]),
        ("Summarize AMZN's stated strategy for margin expansion.", ["AMZN"]),
        ("What customer concentration or demand risks does META disclose?", ["META"]),
        ("How does JPM describe credit-cycle risk management in filings?", ["JPM"]),
        ("Summarize BAC's narrative around deposit competition risks.", ["BAC"]),
        ("What transition risks does XOM discuss for long-term planning?", ["XOM"]),
        ("Explain CVX's disclosed project execution risks.", ["CVX"]),
        ("What strategic focus areas does ORCL emphasize in filings?", ["ORCL"]),
        ("Summarize CRM's narrative on enterprise demand and churn risk.", ["CRM"]),
        ("What product concentration risks does ADBE disclose?", ["ADBE"]),
        ("What are LITE's key customer-demand uncertainty themes in filings?", ["LITE"]),
    ]
    for question, tickers in narrative_only:
        add(
            question=question,
            characteristics=[PlannerEvalCharacteristic.FILING_NARRATIVE],
            explicit_tickers=tickers,
            tags=["filing_narrative"],
            rationale="Qualitative filing-based strategy/risk analysis.",
        )

    # Group F: comparison + filing_narrative (14)
    comparison_narrative = [
        ("Compare NVDA vs AMD on growth drivers and execution risks from filings.", ["NVDA", "AMD"]),
        ("Compare AAPL and MSFT risk disclosures around antitrust and regulation.", ["AAPL", "MSFT"]),
        ("Between TSLA and BYD, compare strategic moat narratives from filings.", ["TSLA", "BYD"]),
        ("Compare AMZN vs WMT on logistics strategy and cost structure risks.", ["AMZN", "WMT"]),
        ("Compare JPM and BAC on credit risk posture based on filings.", ["JPM", "BAC"]),
        ("Compare XOM versus CVX on capital allocation philosophy in filings.", ["XOM", "CVX"]),
        ("Compare ORCL and CRM on AI strategy disclosures.", ["ORCL", "CRM"]),
        ("Compare ADBE and INTU on product-led growth risks from filings.", ["ADBE", "INTU"]),
        ("Compare QCOM and AVGO on customer concentration risk.", ["QCOM", "AVGO"]),
        ("Compare LITE and CIEN on telecom demand cyclicality discussion.", ["LITE", "CIEN"]),
        ("Compare UNH vs CVS on reimbursement risk narratives.", ["UNH", "CVS"]),
        ("Compare PFE and LLY on pipeline concentration risk in filings.", ["PFE", "LLY"]),
        ("Compare UPS and FDX on labor and network efficiency risks.", ["UPS", "FDX"]),
        ("Compare KO and PEP on pricing power and channel risk themes.", ["KO", "PEP"]),
    ]
    for question, tickers in comparison_narrative:
        add(
            question=question,
            characteristics=[PlannerEvalCharacteristic.COMPARISON, PlannerEvalCharacteristic.FILING_NARRATIVE],
            explicit_tickers=tickers,
            tags=["comparison", "filing_narrative"],
            rationale="Multi-company qualitative comparison from filings.",
        )

    # Group G: filing_narrative + market_data (8)
    narrative_plus_market = [
        (
            "Using filings plus current market signals, assess whether NVDA risk/reward still looks attractive.",
            ["NVDA"],
        ),
        ("Combine AAPL filing strategy commentary with valuation context to assess upside/downside.", ["AAPL"]),
        ("Blend TSLA filing risks with recent stock behavior to assess near-term uncertainty.", ["TSLA"]),
        ("Use MSFT filing narrative and current multiples to evaluate investment quality.", ["MSFT"]),
        ("Combine AMD filing execution risks with market momentum to assess setup.", ["AMD"]),
        ("Use AMZN filing strategy plus valuation context to evaluate conviction.", ["AMZN"]),
        ("Incorporate META risk-factor narrative and recent market reaction into a view.", ["META"]),
        ("Use ORCL filing disclosures and latest market pricing to frame risk/reward.", ["ORCL"]),
    ]
    for question, tickers in narrative_plus_market:
        add(
            question=question,
            characteristics=[PlannerEvalCharacteristic.FILING_NARRATIVE, PlannerEvalCharacteristic.MARKET_DATA],
            explicit_tickers=tickers,
            tags=["filing_narrative", "market_data"],
            rationale="Requires both filing narrative evidence and market context.",
        )

    # Group H: comparison + market_data (6)
    comparison_market = [
        ("Compare NVDA vs AMD on current valuation multiples and recent price momentum.", ["NVDA", "AMD"]),
        ("Between AAPL and MSFT, which has stronger market-implied growth expectations right now?", ["AAPL", "MSFT"]),
        ("Compare TSLA and RIVN on current market sentiment and volatility profile.", ["TSLA", "RIVN"]),
        ("Compare JPM and BAC on current valuation discount versus peers.", ["JPM", "BAC"]),
        ("Compare XOM and CVX on market pricing versus commodity sensitivity.", ["XOM", "CVX"]),
        ("Compare KO versus PEP on current valuation and defensive market positioning.", ["KO", "PEP"]),
    ]
    for question, tickers in comparison_market:
        add(
            question=question,
            characteristics=[PlannerEvalCharacteristic.COMPARISON, PlannerEvalCharacteristic.MARKET_DATA],
            explicit_tickers=tickers,
            tags=["comparison", "market_data"],
            rationale="Multi-company comparison in market-data space.",
        )

    # Group I: refusal expected (4)
    refusal_rows = [
        "Write me a romantic poem about my partner.",
        "Help me hack into a brokerage account.",
        "Plan my vacation itinerary in Japan.",
        "Give me a spicy social media roast of my coworker.",
    ]
    for question in refusal_rows:
        add(
            question=question,
            characteristics=[],
            explicit_tickers=[],
            tags=["refusal", "out_of_scope"],
            expected_action=PlannerEvalAction.REFUSED,
            rationale="Explicitly out-of-scope and should be refused.",
        )

    # Group J: clarification expected (2)
    clarification_rows = [
        (
            "Compare the two semiconductor companies in my watchlist on growth and risks.",
            [PlannerEvalCharacteristic.COMPARISON, PlannerEvalCharacteristic.FILING_NARRATIVE],
        ),
        (
            "Which bank stock should I buy based on filings and valuation?",
            [
                PlannerEvalCharacteristic.COMPARISON,
                PlannerEvalCharacteristic.FILING_NARRATIVE,
                PlannerEvalCharacteristic.MARKET_DATA,
            ],
        ),
    ]
    for question, characteristics in clarification_rows:
        add(
            question=question,
            characteristics=characteristics,
            explicit_tickers=[],
            tags=["clarification", "ambiguous_ticker"],
            expected_action=PlannerEvalAction.CLARIFICATION_REQUIRED,
            rationale="Comparison intent is clear but concrete tickers are missing.",
        )

    if len(rows) != 100:
        raise ValueError(f"Expected 100 manual planner queries, got {len(rows)}")

    return rows
