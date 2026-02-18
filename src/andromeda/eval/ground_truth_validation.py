from __future__ import annotations

from dataclasses import dataclass

from andromeda.eval.schema import EvalQuery
from andromeda.finance_tools import FinanceToolStatus, FinanceTools, number_or_none

_METRIC_TO_EDGAR_KEYS: dict[str, tuple[str, ...]] = {
    "total revenue": ("revenue",),
    "net income": ("net_income",),
}

_SCALE_TO_FACTOR: dict[str, float] = {
    "units": 1.0,
    "thousands": 1e3,
    "millions": 1e6,
    "billions": 1e9,
}


@dataclass(frozen=True)
class EdgarValidationStats:
    """
    Validation counters for factual query post-processing.
    """

    total_factual: int
    validated: int
    matched: int
    mismatched: int
    dropped_mismatched: int
    skipped_unsupported_metric: int
    skipped_missing_ticker: int
    skipped_no_tool_data: int

    def to_dict(self) -> dict[str, int]:
        return {
            "total_factual": self.total_factual,
            "validated": self.validated,
            "matched": self.matched,
            "mismatched": self.mismatched,
            "dropped_mismatched": self.dropped_mismatched,
            "skipped_unsupported_metric": self.skipped_unsupported_metric,
            "skipped_missing_ticker": self.skipped_missing_ticker,
            "skipped_no_tool_data": self.skipped_no_tool_data,
        }

def _expected_value_candidates(raw_value: float, declared_scale: str | None) -> list[tuple[str, float]]:
    """
    Build candidate expected values with scale fallback.

    Some extracted factual rows miss scale hints ("in millions"), so we compare
    against plausible scale normalizations before marking a mismatch.
    """

    declared = declared_scale.strip().lower() if isinstance(declared_scale, str) and declared_scale.strip() else "units"
    out: list[tuple[str, float]] = []
    seen: set[float] = set()

    ordered_scales = [declared, "units", "thousands", "millions", "billions"]
    for scale_name in ordered_scales:
        if scale_name not in _SCALE_TO_FACTOR:
            continue
        value = float(raw_value) * _SCALE_TO_FACTOR[scale_name]
        if value in seen:
            continue
        seen.add(value)
        out.append((scale_name, value))

    if not out:
        out.append(("units", float(raw_value)))
    return out


def _ticker_from_factual_query(query: EvalQuery) -> str | None:
    if query.factual is None:
        return None

    doc_id = query.factual.golden_evidence.doc_id.strip() if query.factual.golden_evidence.doc_id else ""
    if doc_id and "_" in doc_id:
        ticker = doc_id.split("_", maxsplit=1)[0].strip().upper()
        if ticker:
            return ticker

    for tag in query.tags:
        token = tag.strip().upper()
        if token and token.isalnum() and 1 <= len(token) <= 8:
            return token
    return None


def _edgar_metric_cache_for_ticker(finance_tools: FinanceTools, ticker: str) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    results = finance_tools.fetch_edgar_financials(ticker=ticker)
    for result in results:
        if result.status != FinanceToolStatus.OK:
            continue
        if not isinstance(result.payload, dict):
            continue
        metrics_raw = result.payload["metrics"] if "metrics" in result.payload else None
        if not isinstance(metrics_raw, dict):
            continue
        for key, raw_value in metrics_raw.items():
            value = number_or_none(raw_value)
            if not isinstance(value, int | float):
                continue
            bucket = out[key] if key in out else []
            bucket.append(float(value))
            out[key] = bucket
    return out


def validate_factual_queries_with_edgar(
    factual_queries: list[EvalQuery], *, rel_tol: float = 0.2, drop_mismatched: bool = False
) -> tuple[list[EvalQuery], EdgarValidationStats]:
    """
    Validate factual numeric ground truth against EdgarTools metric snapshots.

    Notes:
    - This currently validates only metrics with stable key mapping in EdgarTools
      (`total revenue` and `net income`).
    - Unsupported metrics are preserved and tagged as skipped.
    """

    kept: list[EvalQuery] = []
    cache: dict[str, dict[str, list[float]]] = {}

    total_factual = len(factual_queries)
    validated = 0
    matched = 0
    mismatched = 0
    dropped_mismatched = 0
    skipped_unsupported_metric = 0
    skipped_missing_ticker = 0
    skipped_no_tool_data = 0

    tools = FinanceTools()

    for query in factual_queries:
        if query.kind != "factual" or query.factual is None:
            kept.append(query)
            continue

        metric_name = query.factual.metric.strip().lower()
        edgar_keys = _METRIC_TO_EDGAR_KEYS[metric_name] if metric_name in _METRIC_TO_EDGAR_KEYS else None
        if edgar_keys is None:
            skipped_unsupported_metric += 1
            tagged = query.model_copy(deep=True)
            tagged.generator["edgar_validation"] = {
                "status": "skipped_unsupported_metric",
                "metric": metric_name,
            }
            kept.append(tagged)
            continue

        ticker = _ticker_from_factual_query(query)
        if ticker is None:
            skipped_missing_ticker += 1
            tagged = query.model_copy(deep=True)
            tagged.generator["edgar_validation"] = {
                "status": "skipped_missing_ticker",
                "metric": metric_name,
            }
            kept.append(tagged)
            continue

        if ticker not in cache:
            cache[ticker] = _edgar_metric_cache_for_ticker(tools, ticker)

        metric_cache = cache[ticker]
        candidates: list[float] = []
        for key in edgar_keys:
            if key in metric_cache:
                candidates.extend(metric_cache[key])

        if not candidates:
            skipped_no_tool_data += 1
            tagged = query.model_copy(deep=True)
            tagged.generator["edgar_validation"] = {
                "status": "skipped_no_tool_data",
                "metric": metric_name,
                "ticker": ticker,
                "candidate_keys": list(edgar_keys),
            }
            kept.append(tagged)
            continue

        expected_candidates = _expected_value_candidates(
            query.factual.expected_numeric.value, query.factual.expected_numeric.scale
        )
        best_rel_error = float("inf")
        best_expected_scale = "units"
        best_expected_value = float(query.factual.expected_numeric.value)
        for expected_scale_name, expected_value in expected_candidates:
            denom = max(abs(expected_value), 1.0)
            rel_error = min(abs(candidate - expected_value) / denom for candidate in candidates)
            if rel_error < best_rel_error:
                best_rel_error = rel_error
                best_expected_scale = expected_scale_name
                best_expected_value = expected_value

        is_match = best_rel_error <= rel_tol

        validated += 1
        if is_match:
            matched += 1
        else:
            mismatched += 1

        tagged = query.model_copy(deep=True)
        tagged.generator["edgar_validation"] = {
            "status": "matched" if is_match else "mismatched",
            "metric": metric_name,
            "ticker": ticker,
            "candidate_keys": list(edgar_keys),
            "rel_tol": rel_tol,
            "best_rel_error": best_rel_error,
            "best_expected_scale": best_expected_scale,
            "best_expected_value": best_expected_value,
        }

        if drop_mismatched and not is_match:
            dropped_mismatched += 1
            continue
        kept.append(tagged)

    stats = EdgarValidationStats(
        total_factual=total_factual,
        validated=validated,
        matched=matched,
        mismatched=mismatched,
        dropped_mismatched=dropped_mismatched,
        skipped_unsupported_metric=skipped_unsupported_metric,
        skipped_missing_ticker=skipped_missing_ticker,
        skipped_no_tool_data=skipped_no_tool_data,
    )
    return kept, stats
