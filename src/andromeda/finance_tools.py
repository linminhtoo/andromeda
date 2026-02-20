from __future__ import annotations

import importlib
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class FinanceToolStatus(str, Enum):
    """
    Status code for one finance tool call.
    """

    OK = "ok"
    NO_DATA = "no_data"
    ERROR = "error"


class EdgarStatementView(str, Enum):
    """
    Statement rendering mode for EdgarTools statement methods.
    """

    STANDARD = "standard"
    DETAILED = "detailed"
    SUMMARY = "summary"


@dataclass(frozen=True)
class FinanceToolResult:
    """
    Normalized finance tool output used by query runtime and API responses.
    """

    tool: str
    ticker: str | None
    status: FinanceToolStatus
    summary: str
    payload: object | None = None


def number_or_none(value: object) -> float | int | None:
    """
    Convert an arbitrary scalar to JSON-safe numeric value, else `None`.
    """

    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    if parsed.is_integer():
        return int(parsed)
    return parsed


def text_or_none(value: object) -> str | None:
    """
    Return stripped string when non-empty, else `None`.
    """

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def compact_json(value: object, *, max_chars: int) -> str:
    """
    Serialize a value to compact JSON and trim to bounded characters.
    """

    raw = json.dumps(value, ensure_ascii=True, default=str)
    if len(raw) <= max_chars:
        return raw
    suffix = "...(truncated)"
    return raw[: max(0, max_chars - len(suffix))] + suffix


class FinanceTools:
    """
    Adapter suite for market data (`yfinance`) and SEC financials (`edgar`).
    """

    def __init__(
        self,
        *,
        max_news_items: int = 5,
        max_history_points: int = 60,
        max_statement_chars: int = 5000,
        max_context_chars_per_result: int = 2200,
    ) -> None:
        self.max_news_items = max(1, int(max_news_items))
        self.max_history_points = max(1, int(max_history_points))
        self.max_statement_chars = max(500, int(max_statement_chars))
        self.max_context_chars_per_result = max(300, int(max_context_chars_per_result))

    def fetch_for_plan(self, *, question: str, tickers: list[str]) -> list[FinanceToolResult]:
        """
        Execute finance tools for requested tickers.
        """

        _ = question
        out: list[FinanceToolResult] = []
        for ticker in tickers:
            normalized = str(ticker or "").strip().upper()
            if not normalized:
                continue
            out.extend(self.fetch_yfinance_suite(ticker=normalized))
            out.extend(self.fetch_edgar_financials(ticker=normalized))
        return out

    def tool_context_text(self, results: list[FinanceToolResult], *, max_chars: int = 14_000) -> str:
        """
        Build bounded textual context block from tool outputs for the final LLM call.
        """

        if not results:
            return ""
        blocks: list[str] = []
        used = 0
        for result in results:
            header = f"[tool={result.tool} ticker={result.ticker or 'n/a'} status={result.status.value}]"
            payload_text = ""
            if result.payload is not None:
                payload_for_context = self.context_payload_for_result(result=result)
                payload_text = compact_json(payload_for_context, max_chars=self.max_context_chars_per_result)
            block = f"{header}\nsummary: {result.summary}"
            if payload_text:
                block += f"\npayload: {payload_text}"
            block += "\n"
            if used + len(block) > max_chars:
                break
            blocks.append(block)
            used += len(block)
        return "\n".join(blocks).strip()

    @staticmethod
    def _month_key(value: object) -> str | None:
        """
        Build a year-month key from a datetime-like or ISO timestamp value.
        """

        if hasattr(value, "year") and hasattr(value, "month"):
            try:
                year = int(getattr(value, "year"))
                month = int(getattr(value, "month"))
            except (TypeError, ValueError):
                year = 0
                month = 0
            if 1900 <= year <= 2200 and 1 <= month <= 12:
                return f"{year:04d}-{month:02d}"

        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return f"{parsed.year:04d}-{parsed.month:02d}"
        except ValueError:
            pass

        if len(text) >= 7 and text[4] == "-":
            yyyy = text[:4]
            mm = text[5:7]
            if yyyy.isdigit() and mm.isdigit():
                year = int(yyyy)
                month = int(mm)
                if 1900 <= year <= 2200 and 1 <= month <= 12:
                    return f"{year:04d}-{month:02d}"
        return None

    def monthly_close_series(self, series: list[dict[str, object]], *, max_months: int = 12) -> list[dict[str, object]]:
        """
        Build compact monthly close points from daily series data.
        """

        latest_close_by_month: dict[str, float] = {}
        for point in series:
            close_raw = point["close"] if "close" in point else None
            close_number = number_or_none(close_raw)
            if not isinstance(close_number, int | float):
                continue
            month = self._month_key(point["t"] if "t" in point else None)
            if month is None:
                continue
            latest_close_by_month[month] = round(float(close_number), 2)

        if not latest_close_by_month:
            return []
        months = sorted(latest_close_by_month.keys())[-max(1, int(max_months)) :]
        return [{"month": month, "close": latest_close_by_month[month]} for month in months]

    def context_payload_for_result(self, *, result: FinanceToolResult) -> object:
        """
        Return payload representation tuned for LLM context consumption.
        """

        if result.payload is None:
            return None
        if result.tool != "yfinance_get_price_history":
            return result.payload
        if not isinstance(result.payload, dict):
            return result.payload

        monthly_series = result.payload["monthly_close_12m"] if "monthly_close_12m" in result.payload else None
        if not isinstance(monthly_series, list):
            return {"monthly_close_12m": []}

        close_values: list[float] = []
        for item in monthly_series:
            if not isinstance(item, dict) or "close" not in item:
                continue
            close_value = number_or_none(item["close"])
            if isinstance(close_value, int | float):
                close_values.append(round(float(close_value), 2))

        out: dict[str, object] = {"monthly_close_12m": close_values}
        if len(close_values) >= 2 and close_values[0] != 0:
            out["change_12m_pct"] = round(((close_values[-1] - close_values[0]) / close_values[0]) * 100.0, 2)
        return out

    def fetch_yfinance_suite(self, *, ticker: str) -> list[FinanceToolResult]:
        """
        Fetch valuation info, news, and recent price history from yfinance.
        """

        try:
            yfinance = importlib.import_module("yfinance")
        except Exception as exc:  # noqa: BLE001
            return [
                FinanceToolResult(
                    tool="yfinance_import",
                    ticker=ticker,
                    status=FinanceToolStatus.ERROR,
                    summary=f"Unable to import yfinance: {exc}",
                )
            ]

        try:
            ticker_obj = yfinance.Ticker(ticker)
        except Exception as exc:  # noqa: BLE001
            return [
                FinanceToolResult(
                    tool="yfinance_init_ticker",
                    ticker=ticker,
                    status=FinanceToolStatus.ERROR,
                    summary=f"Unable to initialize yfinance ticker: {exc}",
                )
            ]

        return [
            self.fetch_yfinance_info(ticker=ticker, ticker_obj=ticker_obj),
            self.fetch_yfinance_news(ticker=ticker, ticker_obj=ticker_obj),
            self.fetch_yfinance_price_history(ticker=ticker, ticker_obj=ticker_obj),
        ]

    def fetch_yfinance_info(self, *, ticker: str, ticker_obj: object) -> FinanceToolResult:
        """
        Fetch profile and valuation snapshot from yfinance.
        """

        try:
            raw_info = ticker_obj.info  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            return FinanceToolResult(
                tool="yfinance_get_ticker_info",
                ticker=ticker,
                status=FinanceToolStatus.ERROR,
                summary=f"Failed to fetch ticker info: {exc}",
            )

        if not isinstance(raw_info, dict) or not raw_info:
            return FinanceToolResult(
                tool="yfinance_get_ticker_info",
                ticker=ticker,
                status=FinanceToolStatus.NO_DATA,
                summary="No ticker info returned by yfinance.",
            )

        profile: dict[str, object] = {}
        valuation: dict[str, object] = {}
        market: dict[str, object] = {}

        profile_keys = ("longName", "sector", "industry", "country", "website")
        valuation_keys = ("marketCap", "enterpriseValue", "trailingPE", "forwardPE", "priceToBook", "pegRatio")
        market_keys = ("currentPrice", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "volume", "averageVolume")

        for key in profile_keys:
            if key in raw_info:
                value = text_or_none(raw_info[key])
                if value is not None:
                    profile[key] = value

        for key in valuation_keys:
            if key in raw_info:
                value = number_or_none(raw_info[key])
                if value is not None:
                    valuation[key] = value

        for key in market_keys:
            if key in raw_info:
                value = number_or_none(raw_info[key])
                if value is not None:
                    market[key] = value

        payload = {"profile": profile, "valuation": valuation, "market": market}
        summary_name = profile["longName"] if "longName" in profile else ticker
        return FinanceToolResult(
            tool="yfinance_get_ticker_info",
            ticker=ticker,
            status=FinanceToolStatus.OK,
            summary=f"Fetched profile/valuation snapshot for {summary_name}.",
            payload=payload,
        )

    def fetch_yfinance_news(self, *, ticker: str, ticker_obj: object) -> FinanceToolResult:
        """
        Fetch recent company news from yfinance.
        """

        try:
            raw_news = ticker_obj.get_news()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            return FinanceToolResult(
                tool="yfinance_get_ticker_news",
                ticker=ticker,
                status=FinanceToolStatus.ERROR,
                summary=f"Failed to fetch ticker news: {exc}",
            )

        if not isinstance(raw_news, list) or not raw_news:
            return FinanceToolResult(
                tool="yfinance_get_ticker_news",
                ticker=ticker,
                status=FinanceToolStatus.NO_DATA,
                summary="No recent news returned by yfinance.",
            )

        articles: list[dict[str, object]] = []
        for item in raw_news:
            if not isinstance(item, dict):
                continue
            article: dict[str, object] = {}

            if "title" in item:
                title = text_or_none(item["title"])
                if title is not None:
                    article["title"] = title

            if "content" in item and isinstance(item["content"], dict):
                content = item["content"]
                if "title" in content and "title" not in article:
                    title = text_or_none(content["title"])
                    if title is not None:
                        article["title"] = title
                if "summary" in content:
                    summary = text_or_none(content["summary"])
                    if summary is not None:
                        article["summary"] = summary
                if "pubDate" in content:
                    pub_date = text_or_none(content["pubDate"])
                    if pub_date is not None:
                        article["published_at"] = pub_date

            if "providerPublishTime" in item and "published_at" not in article:
                ts = number_or_none(item["providerPublishTime"])
                if isinstance(ts, int | float):
                    article["published_at"] = datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()

            if "link" in item:
                link = text_or_none(item["link"])
                if link is not None:
                    article["url"] = link

            if "canonicalUrl" in item and isinstance(item["canonicalUrl"], dict):
                canonical = item["canonicalUrl"]
                if "url" in canonical and "url" not in article:
                    url = text_or_none(canonical["url"])
                    if url is not None:
                        article["url"] = url

            if article:
                articles.append(article)
            if len(articles) >= self.max_news_items:
                break

        if not articles:
            return FinanceToolResult(
                tool="yfinance_get_ticker_news",
                ticker=ticker,
                status=FinanceToolStatus.NO_DATA,
                summary="Ticker news payload was empty after normalization.",
            )

        return FinanceToolResult(
            tool="yfinance_get_ticker_news",
            ticker=ticker,
            status=FinanceToolStatus.OK,
            summary=f"Fetched {len(articles)} recent news items for {ticker}.",
            payload={"articles": articles},
        )

    def fetch_yfinance_price_history(self, *, ticker: str, ticker_obj: object) -> FinanceToolResult:
        """
        Fetch recent OHLCV data points from yfinance for chart-ready rendering.
        """

        try:
            history = ticker_obj.history(period="12mo", interval="1d", rounding=True)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            return FinanceToolResult(
                tool="yfinance_get_price_history",
                ticker=ticker,
                status=FinanceToolStatus.ERROR,
                summary=f"Failed to fetch price history: {exc}",
            )

        if history is None or getattr(history, "empty", True):
            return FinanceToolResult(
                tool="yfinance_get_price_history",
                ticker=ticker,
                status=FinanceToolStatus.NO_DATA,
                summary="No price history returned by yfinance.",
            )

        series: list[dict[str, object]] = []
        for index, row in history.iterrows():
            point: dict[str, object] = {}
            if hasattr(index, "isoformat"):
                point["t"] = index.isoformat()  # type: ignore[union-attr]
            else:
                point["t"] = str(index)

            open_price = number_or_none(row["Open"]) if "Open" in row else None
            high_price = number_or_none(row["High"]) if "High" in row else None
            low_price = number_or_none(row["Low"]) if "Low" in row else None
            close_price = number_or_none(row["Close"]) if "Close" in row else None
            volume = number_or_none(row["Volume"]) if "Volume" in row else None

            if open_price is not None:
                point["open"] = open_price
            if high_price is not None:
                point["high"] = high_price
            if low_price is not None:
                point["low"] = low_price
            if close_price is not None:
                point["close"] = close_price
            if volume is not None:
                point["volume"] = volume

            series.append(point)

        if not series:
            return FinanceToolResult(
                tool="yfinance_get_price_history",
                ticker=ticker,
                status=FinanceToolStatus.NO_DATA,
                summary="Price history was empty after normalization.",
            )

        monthly_close_12m = self.monthly_close_series(series, max_months=12)
        trimmed_series = series[-self.max_history_points :]

        return FinanceToolResult(
            tool="yfinance_get_price_history",
            ticker=ticker,
            status=FinanceToolStatus.OK,
            summary=(
                f"Fetched {len(trimmed_series)} chart OHLCV points and "
                f"{len(monthly_close_12m)} monthly close values for {ticker}."
            ),
            payload={
                "period": "12mo",
                "interval": "1d",
                "series": trimmed_series,
                "monthly_close_12m": monthly_close_12m,
            },
        )

    def fetch_edgar_financials(
        self, *, ticker: str, view: EdgarStatementView = EdgarStatementView.SUMMARY
    ) -> list[FinanceToolResult]:
        """
        Fetch annual and quarterly financial metrics/statements from EdgarTools.
        """

        try:
            edgar = importlib.import_module("edgar")
        except Exception as exc:  # noqa: BLE001
            return [
                FinanceToolResult(
                    tool="edgar_import",
                    ticker=ticker,
                    status=FinanceToolStatus.ERROR,
                    summary=f"Unable to import edgar: {exc}",
                )
            ]

        user_email = (os.getenv("USER_EMAIL") or "").strip()
        if not user_email:
            return [
                FinanceToolResult(
                    tool="edgar_set_identity",
                    ticker=ticker,
                    status=FinanceToolStatus.ERROR,
                    summary="USER_EMAIL is not set. Configure USER_EMAIL so EdgarTools can set user identity.",
                )
            ]
        try:
            edgar.set_identity(user_email)
        except Exception as exc:  # noqa: BLE001
            return [
                FinanceToolResult(
                    tool="edgar_set_identity",
                    ticker=ticker,
                    status=FinanceToolStatus.ERROR,
                    summary=f"Unable to set Edgar identity from USER_EMAIL: {exc}",
                )
            ]

        try:
            company = edgar.Company(ticker)
        except Exception as exc:  # noqa: BLE001
            return [
                FinanceToolResult(
                    tool="edgar_init_company",
                    ticker=ticker,
                    status=FinanceToolStatus.ERROR,
                    summary=f"Unable to initialize edgar company: {exc}",
                )
            ]

        return [
            self.fetch_edgar_metrics(ticker=ticker, company=company, quarterly=False),
            self.fetch_edgar_metrics(ticker=ticker, company=company, quarterly=True),
            self.fetch_edgar_statements(ticker=ticker, company=company, view=view),
        ]

    def fetch_edgar_metrics(self, *, ticker: str, company: object, quarterly: bool) -> FinanceToolResult:
        """
        Fetch compact metric dictionary from EdgarTools financials.
        """

        tool = "edgar_get_quarterly_financial_metrics" if quarterly else "edgar_get_financial_metrics"
        label = "quarterly" if quarterly else "annual"
        try:
            financials = company.get_quarterly_financials() if quarterly else company.get_financials()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            return FinanceToolResult(
                tool=tool,
                ticker=ticker,
                status=FinanceToolStatus.ERROR,
                summary=f"Failed to fetch {label} financials: {exc}",
            )

        if financials is None:
            return FinanceToolResult(
                tool=tool,
                ticker=ticker,
                status=FinanceToolStatus.NO_DATA,
                summary=f"No {label} financial metrics available from SEC filings.",
            )

        try:
            raw_metrics = financials.get_financial_metrics()
        except Exception as exc:  # noqa: BLE001
            return FinanceToolResult(
                tool=tool,
                ticker=ticker,
                status=FinanceToolStatus.ERROR,
                summary=f"Failed to compute {label} financial metrics: {exc}",
            )

        metrics: dict[str, object] = {}
        if isinstance(raw_metrics, dict):
            for key, raw_value in raw_metrics.items():
                value = number_or_none(raw_value)
                if value is not None:
                    metrics[str(key)] = value

        if not metrics:
            return FinanceToolResult(
                tool=tool,
                ticker=ticker,
                status=FinanceToolStatus.NO_DATA,
                summary=f"{label.capitalize()} financial metrics payload is empty.",
            )

        return FinanceToolResult(
            tool=tool,
            ticker=ticker,
            status=FinanceToolStatus.OK,
            summary=f"Fetched {label} SEC financial metrics for {ticker}.",
            payload={"period": label, "metrics": metrics},
        )

    def fetch_edgar_statements(self, *, ticker: str, company: object, view: EdgarStatementView) -> FinanceToolResult:
        """
        Fetch annual statement snapshots from EdgarTools for synthesis use.
        """

        try:
            financials = company.get_financials()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            return FinanceToolResult(
                tool="edgar_get_financial_statements",
                ticker=ticker,
                status=FinanceToolStatus.ERROR,
                summary=f"Failed to fetch annual statements: {exc}",
            )

        if financials is None:
            return FinanceToolResult(
                tool="edgar_get_financial_statements",
                ticker=ticker,
                status=FinanceToolStatus.NO_DATA,
                summary="No annual statements available from latest 10-K filing.",
            )

        payload: dict[str, object] = {}
        statements = (
            ("income_statement", financials.income_statement(view=view.value)),
            ("balance_sheet", financials.balance_sheet(view=view.value)),
            ("cashflow_statement", financials.cashflow_statement(view=view.value)),
        )
        for name, statement in statements:
            if statement is None:
                continue
            text = text_or_none(str(statement))
            if text is None:
                continue
            if len(text) > self.max_statement_chars:
                text = text[: self.max_statement_chars] + "...(truncated)"
            payload[name] = text

        if not payload:
            return FinanceToolResult(
                tool="edgar_get_financial_statements",
                ticker=ticker,
                status=FinanceToolStatus.NO_DATA,
                summary="Annual statement payload is empty after normalization.",
            )

        return FinanceToolResult(
            tool="edgar_get_financial_statements",
            ticker=ticker,
            status=FinanceToolStatus.OK,
            summary=f"Fetched annual statement snapshots for {ticker}.",
            payload=payload,
        )
