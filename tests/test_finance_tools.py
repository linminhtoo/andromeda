from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace

from finrag.finance_tools import FinanceToolResult, FinanceToolStatus, FinanceTools


class FakeHistoryFrame:
    def __init__(self, rows: list[tuple[datetime, dict[str, float | int]]]) -> None:
        self.rows = rows
        self.empty = len(rows) == 0

    def tail(self, n: int) -> "FakeHistoryFrame":
        return FakeHistoryFrame(self.rows[-n:])

    def iterrows(self):
        for row in self.rows:
            yield row


class FakeYFinanceTicker:
    def __init__(self) -> None:
        self.info = {
            "longName": "Apple Inc.",
            "sector": "Technology",
            "marketCap": 3_100_000_000_000,
            "trailingPE": 31.2,
            "currentPrice": 210.5,
        }

    def get_news(self) -> list[dict[str, object]]:
        return [
            {
                "title": "Apple posts strong quarter",
                "providerPublishTime": 1_739_584_800,
                "link": "https://example.com/apple-news",
            }
        ]

    def history(self, period: str, interval: str, rounding: bool = True) -> FakeHistoryFrame:
        _ = period, interval, rounding
        return FakeHistoryFrame(
            [
                (datetime(2026, 1, 1), {"Open": 100.0, "High": 110.0, "Low": 99.0, "Close": 105.0, "Volume": 1000}),
                (datetime(2026, 1, 2), {"Open": 106.0, "High": 112.0, "Low": 103.0, "Close": 110.0, "Volume": 1500}),
            ]
        )


@dataclass
class FakeFinancials:
    def get_financial_metrics(self) -> dict[str, float]:
        return {"revenue": 1000.0, "net_income": 220.0}

    def income_statement(self, view: str | None = None) -> str:
        _ = view
        return "income statement"

    def balance_sheet(self, view: str | None = None) -> str:
        _ = view
        return "balance sheet"

    def cashflow_statement(self, view: str | None = None) -> str:
        _ = view
        return "cash flow"


class FakeCompany:
    def get_financials(self) -> FakeFinancials:
        return FakeFinancials()

    def get_quarterly_financials(self) -> FakeFinancials:
        return FakeFinancials()


def test_fetch_yfinance_suite(monkeypatch) -> None:
    fake_module = SimpleNamespace(Ticker=lambda _ticker: FakeYFinanceTicker())
    monkeypatch.setattr("importlib.import_module", lambda name: fake_module if name == "yfinance" else None)

    tools = FinanceTools(max_news_items=2, max_history_points=10)
    results = tools.fetch_yfinance_suite(ticker="AAPL")

    assert len(results) == 3
    assert [item.tool for item in results] == [
        "yfinance_get_ticker_info",
        "yfinance_get_ticker_news",
        "yfinance_get_price_history",
    ]
    assert all(item.status == FinanceToolStatus.OK for item in results)


def test_fetch_edgar_financials(monkeypatch) -> None:
    fake_module = SimpleNamespace(set_identity=lambda _email: None, Company=lambda _ticker: FakeCompany())
    monkeypatch.setenv("USER_EMAIL", "test@example.com")
    monkeypatch.setattr("importlib.import_module", lambda name: fake_module if name == "edgar" else None)

    tools = FinanceTools()
    results = tools.fetch_edgar_financials(ticker="AAPL")

    assert len(results) == 3
    assert [item.tool for item in results] == [
        "edgar_get_financial_metrics",
        "edgar_get_quarterly_financial_metrics",
        "edgar_get_financial_statements",
    ]
    assert all(item.status == FinanceToolStatus.OK for item in results)


def test_fetch_edgar_financials_requires_user_email(monkeypatch) -> None:
    fake_module = SimpleNamespace(set_identity=lambda _email: None, Company=lambda _ticker: FakeCompany())
    monkeypatch.delenv("USER_EMAIL", raising=False)
    monkeypatch.setattr("importlib.import_module", lambda name: fake_module if name == "edgar" else None)

    tools = FinanceTools()
    results = tools.fetch_edgar_financials(ticker="AAPL")
    assert len(results) == 1
    assert results[0].tool == "edgar_set_identity"
    assert results[0].status == FinanceToolStatus.ERROR


def test_tool_context_text_is_bounded() -> None:
    tools = FinanceTools(max_context_chars_per_result=40)
    payload = {"k": "x" * 400}
    results = [
        tools.fetch_yfinance_info(ticker="AAPL", ticker_obj=SimpleNamespace(info={"longName": "Apple"})),
        tools.fetch_yfinance_news(ticker="AAPL", ticker_obj=SimpleNamespace(get_news=lambda: [{"title": "A"}])),
    ]
    results.append(FinanceToolResult(tool="manual", ticker="AAPL", status=FinanceToolStatus.OK, summary="ok", payload=payload))

    text = tools.tool_context_text(results, max_chars=2000)
    assert "[tool=yfinance_get_ticker_info" in text
    assert "[tool=manual ticker=AAPL" in text
    assert "(truncated)" in text
