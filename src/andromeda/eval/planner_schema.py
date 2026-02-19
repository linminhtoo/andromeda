from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class PlannerEvalCharacteristic(str, Enum):
    """
    Planner multi-label characteristic taxonomy.
    """

    COMPARISON = "comparison"
    MARKET_DATA = "market_data"
    FINANCIAL_METRICS = "financial_metrics"
    FILING_NARRATIVE = "filing_narrative"
    PERIOD_SCOPED = "period_scoped"
    SIMPLE_NUMERIC = "simple_numeric"


class PlannerEvalAction(str, Enum):
    """
    Planner action taxonomy for evaluation.
    """

    ANSWERED = "answered"
    CLARIFICATION_REQUIRED = "clarification_required"
    REFUSED = "refused"


class PlannerEvalQuery(BaseModel):
    """
    Ground-truth row for planner characteristics evaluation.
    """

    id: str
    question: str
    expected_characteristics: list[PlannerEvalCharacteristic] = Field(default_factory=list)
    expected_action: PlannerEvalAction | None = None
    explicit_tickers: list[str] = Field(default_factory=list)
    filing_date_from: str | None = None
    filing_date_to: str | None = None
    tags: list[str] = Field(default_factory=list)
    rationale: str | None = None
    created_at: datetime | None = None

    @model_validator(mode="after")
    def normalize(self) -> "PlannerEvalQuery":
        seen_chars: set[PlannerEvalCharacteristic] = set()
        deduped_chars: list[PlannerEvalCharacteristic] = []
        for item in self.expected_characteristics:
            if item in seen_chars:
                continue
            seen_chars.add(item)
            deduped_chars.append(item)
        self.expected_characteristics = deduped_chars

        seen_tickers: set[str] = set()
        deduped_tickers: list[str] = []
        for raw in self.explicit_tickers:
            ticker = raw.strip().upper()
            if not ticker:
                continue
            if ticker in seen_tickers:
                continue
            seen_tickers.add(ticker)
            deduped_tickers.append(ticker)
        self.explicit_tickers = deduped_tickers

        return self


class PlannerEvalPrediction(BaseModel):
    """
    Planner output recorded for one eval query.
    """

    query_id: str
    question: str
    predicted_characteristics: list[PlannerEvalCharacteristic] = Field(default_factory=list)
    predicted_action: PlannerEvalAction | None = None
    predicted_tickers: list[str] = Field(default_factory=list)

    use_rag: bool | None = None
    use_yfinance: bool | None = None
    use_edgar_financials: bool | None = None
    use_per_ticker_retrieval: bool | None = None
    use_multi_ticker_briefs: bool | None = None

    attempts: int = 0
    timing_ms: dict[str, float] = Field(default_factory=dict)
    error: str | None = None

    @model_validator(mode="after")
    def normalize(self) -> "PlannerEvalPrediction":
        seen_chars: set[PlannerEvalCharacteristic] = set()
        deduped_chars: list[PlannerEvalCharacteristic] = []
        for item in self.predicted_characteristics:
            if item in seen_chars:
                continue
            seen_chars.add(item)
            deduped_chars.append(item)
        self.predicted_characteristics = deduped_chars

        seen_tickers: set[str] = set()
        deduped_tickers: list[str] = []
        for raw in self.predicted_tickers:
            ticker = raw.strip().upper()
            if not ticker:
                continue
            if ticker in seen_tickers:
                continue
            seen_tickers.add(ticker)
            deduped_tickers.append(ticker)
        self.predicted_tickers = deduped_tickers
        return self


class PlannerEvalScore(BaseModel):
    """
    Per-query planner evaluation metrics.
    """

    query_id: str
    question: str
    expected_characteristics: list[PlannerEvalCharacteristic] = Field(default_factory=list)
    predicted_characteristics: list[PlannerEvalCharacteristic] = Field(default_factory=list)
    missing_characteristics: list[PlannerEvalCharacteristic] = Field(default_factory=list)
    extra_characteristics: list[PlannerEvalCharacteristic] = Field(default_factory=list)

    expected_action: PlannerEvalAction | None = None
    predicted_action: PlannerEvalAction | None = None
    action_match: bool | None = None

    characteristic_exact_match: bool = False
    expected_subset_recalled: bool = False
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0

    prediction_error: str | None = None
