from __future__ import annotations

import importlib
import re

from andromeda.ingestion.ingestion_jobs import normalize_ticker


class PlannerFallbackHeuristics:
    """
    Heuristic helpers used only when planner structured output fails.
    """

    CHARACTERISTIC_COMPARISON = "comparison"
    CHARACTERISTIC_MARKET_DATA = "market_data"
    CHARACTERISTIC_FINANCIAL_METRICS = "financial_metrics"
    CHARACTERISTIC_FILING_NARRATIVE = "filing_narrative"
    CHARACTERISTIC_PERIOD_SCOPED = "period_scoped"
    CHARACTERISTIC_SIMPLE_NUMERIC = "simple_numeric"

    @staticmethod
    def question_mentions_comparison(question: str) -> bool:
        lowered = question.lower()
        tokens = (" compare ", " versus ", " vs ", " relative to ", " better investment ", " which is better ", " or ")
        padded = f" {lowered} "
        return any(token in padded for token in tokens)

    @staticmethod
    def question_mentions_market_data(question: str) -> bool:
        lowered = f" {question.lower()} "
        tokens = (
            " stock price ",
            " price ",
            " chart ",
            " valuation ",
            " market cap ",
            " news ",
            " return ",
            " performance ",
            " volume ",
            " pe ratio ",
            " p/e ",
            " dividend ",
        )
        return any(token in lowered for token in tokens)

    @staticmethod
    def question_mentions_financial_metrics(question: str) -> bool:
        lowered = f" {question.lower()} "
        tokens = (
            " revenue ",
            " net income ",
            " gross margin ",
            " operating margin ",
            " eps ",
            " balance sheet ",
            " cash flow ",
            " free cash flow ",
            " assets ",
            " liabilities ",
            " equity ",
            " ratio ",
            " debt ",
        )
        return any(token in lowered for token in tokens)

    @staticmethod
    def question_has_explicit_period_scope(question: str) -> bool:
        lowered = f" {question.lower()} "
        if re.search(r"\b20\d{2}\b", lowered):
            return True
        tokens = (
            " quarter ",
            " q1 ",
            " q2 ",
            " q3 ",
            " q4 ",
            " fiscal year ",
            " fy ",
            " year ended ",
            " as of ",
            " during ",
            " in the latest filing ",
            " latest filing ",
        )
        return any(token in lowered for token in tokens)

    @staticmethod
    def infer_filing_date_window_from_question(question: str) -> tuple[str, str] | None:
        """
        Infer inclusive filing-date window from explicit years in question.
        """

        years = sorted({int(token) for token in re.findall(r"\b(20\d{2})\b", question)})
        if not years:
            return None
        start_year = years[0]
        end_year = years[-1]
        if end_year - start_year > 6:
            return None
        return f"{start_year:04d}-01-01", f"{end_year:04d}-12-31"

    @staticmethod
    def question_mentions_filing_narrative(question: str) -> bool:
        lowered = f" {question.lower()} "
        tokens = (
            " sec filing ",
            " sec filings ",
            " long-term investment ",
            " long term investment ",
            " investment thesis ",
            " bull-vs-bear ",
            " bull vs bear ",
            " business trajectory ",
            " growth driver ",
            " growth drivers ",
            " growth opportunities ",
            " key risks ",
            " material risks ",
            " downside risks ",
            " competitive positioning ",
            " competitive position ",
            " risk factor ",
            " management discussion ",
            " management commentary ",
            " md&a ",
            " discuss ",
            " explain ",
            " guidance ",
            " outlook ",
            " strategy ",
            " segment ",
            " capital allocation ",
            " margin resilience ",
            " cash-flow quality ",
            " cash flow quality ",
            " operational bottleneck ",
            " operational bottlenecks ",
            " dependencies ",
            " demand trends ",
            " customer behavior ",
            " trade-off ",
            " trade-offs ",
            " why ",
        )
        return any(token in lowered for token in tokens)

    @classmethod
    def question_is_simple_numeric_metric(cls, question: str) -> bool:
        """
        Return whether the question is a direct numeric metric lookup.
        """

        mentions_metrics = cls.question_mentions_financial_metrics(question) or cls.question_mentions_market_data(
            question
        )
        mentions_narrative = cls.question_mentions_filing_narrative(question)
        mentions_comparison = cls.question_mentions_comparison(question)
        has_period_scope = cls.question_has_explicit_period_scope(question)
        lowered = f" {question.lower()} "
        has_explicit_numeric_intent = any(
            token in lowered
            for token in (
                " what was ",
                " what is ",
                " how much ",
                " amount ",
                " total ",
                " value ",
                " figure ",
                " give me ",
            )
        )
        token_count = len(question.split())
        return (
            mentions_metrics
            and not mentions_narrative
            and not mentions_comparison
            and not has_period_scope
            and has_explicit_numeric_intent
            and token_count <= 24
        )

    @classmethod
    def classify_characteristics(cls, question: str) -> list[str]:
        """
        Infer planner characteristics with fallback heuristics.
        """

        out: list[str] = []
        if cls.question_mentions_comparison(question):
            out.append(cls.CHARACTERISTIC_COMPARISON)
        if cls.question_mentions_market_data(question):
            out.append(cls.CHARACTERISTIC_MARKET_DATA)
        if cls.question_mentions_financial_metrics(question):
            out.append(cls.CHARACTERISTIC_FINANCIAL_METRICS)
        if cls.question_mentions_filing_narrative(question):
            out.append(cls.CHARACTERISTIC_FILING_NARRATIVE)
        if cls.question_has_explicit_period_scope(question):
            out.append(cls.CHARACTERISTIC_PERIOD_SCOPED)
        if cls.question_is_simple_numeric_metric(question):
            out.append(cls.CHARACTERISTIC_SIMPLE_NUMERIC)
        return out

    @staticmethod
    def infer_tickers_from_question(question: str, companies: list[dict[str, str]]) -> list[str]:
        """
        Infer candidate tickers using yfinance search (fallback path only).
        """

        known_tickers: set[str] = set()
        for item in companies:
            if "ticker" not in item:
                continue
            ticker = str(item["ticker"]).strip().upper()
            if ticker:
                known_tickers.add(ticker)
        if not known_tickers:
            return []

        try:
            yfinance = importlib.import_module("yfinance")
        except Exception:
            return []

        search_terms: list[str] = []
        base_query = str(question).strip()
        if base_query:
            search_terms.append(base_query)

        normalized_question = " " + re.sub(r"[^a-z0-9]+", " ", question.lower()).strip() + " "
        for item in companies:
            if "company" not in item:
                continue
            company = str(item["company"]).strip()
            if not company:
                continue
            normalized_company = " " + re.sub(r"[^a-z0-9]+", " ", company.lower()).strip() + " "
            if normalized_company in normalized_question:
                search_terms.append(company)

        deduped_terms: list[str] = []
        seen_terms: set[str] = set()
        for term in search_terms:
            key = term.lower().strip()
            if not key or key in seen_terms:
                continue
            seen_terms.add(key)
            deduped_terms.append(term)

        inferred: list[str] = []
        seen_tickers: set[str] = set()
        for term in deduped_terms[:4]:
            try:
                search_obj = yfinance.Search(
                    term,
                    max_results=12,
                    news_count=0,
                    lists_count=0,
                    include_nav_links=False,
                    include_research=False,
                    include_cultural_assets=False,
                    enable_fuzzy_query=True,
                    raise_errors=False,
                    timeout=10,
                )
            except Exception:
                continue
            quotes = search_obj.quotes if hasattr(search_obj, "quotes") else []
            if not isinstance(quotes, list):
                continue
            for quote in quotes:
                if not isinstance(quote, dict) or "symbol" not in quote:
                    continue
                raw_symbol = str(quote["symbol"]).strip()
                if not raw_symbol:
                    continue
                try:
                    symbol = normalize_ticker(raw_symbol)
                except ValueError:
                    symbol = raw_symbol.upper()
                if symbol not in known_tickers or symbol in seen_tickers:
                    continue
                seen_tickers.add(symbol)
                inferred.append(symbol)
                if len(inferred) >= 6:
                    return inferred
        return inferred
