from __future__ import annotations

from andromeda.eval.planner_schema import (
    PlannerEvalCharacteristic,
    PlannerEvalPrediction,
    PlannerEvalQuery,
    PlannerEvalScore,
)


def _safe_div(numerator: float, denominator: float) -> float:
    """
    Divide safely and return zero when denominator is not positive.
    """

    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _precision(true_set: set[PlannerEvalCharacteristic], pred_set: set[PlannerEvalCharacteristic]) -> float:
    """
    Compute per-query set precision.
    """

    if not pred_set:
        return 1.0 if not true_set else 0.0
    return _safe_div(float(len(true_set & pred_set)), float(len(pred_set)))


def _recall(true_set: set[PlannerEvalCharacteristic], pred_set: set[PlannerEvalCharacteristic]) -> float:
    """
    Compute per-query set recall.
    """

    if not true_set:
        return 1.0
    return _safe_div(float(len(true_set & pred_set)), float(len(true_set)))


def _f1(precision: float, recall: float) -> float:
    """
    Compute harmonic mean of precision and recall.
    """

    if precision + recall <= 0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def _mean(values: list[float]) -> float:
    """
    Return arithmetic mean or zero for an empty sequence.
    """

    if not values:
        return 0.0
    return sum(values) / float(len(values))


def _sorted_characteristics(items: set[PlannerEvalCharacteristic]) -> list[PlannerEvalCharacteristic]:
    """
    Return characteristics sorted by enum value for deterministic output.
    """

    return sorted(items, key=lambda item: item.value)


def score_planner_predictions(
    *, queries: list[PlannerEvalQuery], predictions: list[PlannerEvalPrediction]
) -> tuple[list[PlannerEvalScore], dict[str, object]]:
    """
    Score planner predictions against manually labeled characteristics.
    """

    predictions_by_id = {item.query_id: item for item in predictions}
    universe = list(PlannerEvalCharacteristic)

    per_query_scores: list[PlannerEvalScore] = []

    exact_match_hits = 0
    subset_recall_hits = 0

    query_precisions: list[float] = []
    query_recalls: list[float] = []
    query_f1s: list[float] = []

    micro_tp = 0
    micro_fp = 0
    micro_fn = 0

    per_char_counts: dict[PlannerEvalCharacteristic, dict[str, int]] = {
        c: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for c in universe
    }

    action_evaluable = 0
    action_hits = 0

    missing_predictions = 0
    prediction_errors = 0

    for query in queries:
        prediction = predictions_by_id.get(query.id)
        prediction_error: str | None = None

        if prediction is None:
            missing_predictions += 1
            predicted_action = None
            pred_set: set[PlannerEvalCharacteristic] = set()
            prediction_error = "missing_prediction"
        else:
            predicted_action = prediction.predicted_action
            pred_set = set(prediction.predicted_characteristics)
            prediction_error = prediction.error
            if prediction.error is not None and prediction.error.strip():
                prediction_errors += 1

        true_set = set(query.expected_characteristics)

        missing = true_set - pred_set
        extra = pred_set - true_set

        precision = _precision(true_set, pred_set)
        recall = _recall(true_set, pred_set)
        f1 = _f1(precision, recall)

        exact_match = true_set == pred_set
        subset_recalled = true_set.issubset(pred_set)

        if exact_match:
            exact_match_hits += 1
        if subset_recalled:
            subset_recall_hits += 1

        query_precisions.append(precision)
        query_recalls.append(recall)
        query_f1s.append(f1)

        micro_tp += len(true_set & pred_set)
        micro_fp += len(extra)
        micro_fn += len(missing)

        for characteristic in universe:
            true_has = characteristic in true_set
            pred_has = characteristic in pred_set
            bucket = per_char_counts[characteristic]
            if true_has and pred_has:
                bucket["tp"] += 1
            elif (not true_has) and pred_has:
                bucket["fp"] += 1
            elif true_has and (not pred_has):
                bucket["fn"] += 1
            else:
                bucket["tn"] += 1

        action_match: bool | None = None
        if query.expected_action is not None:
            action_evaluable += 1
            action_match = predicted_action == query.expected_action
            if action_match:
                action_hits += 1

        per_query_scores.append(
            PlannerEvalScore(
                query_id=query.id,
                question=query.question,
                expected_characteristics=_sorted_characteristics(true_set),
                predicted_characteristics=_sorted_characteristics(pred_set),
                missing_characteristics=_sorted_characteristics(missing),
                extra_characteristics=_sorted_characteristics(extra),
                expected_action=query.expected_action,
                predicted_action=predicted_action,
                action_match=action_match,
                characteristic_exact_match=exact_match,
                expected_subset_recalled=subset_recalled,
                precision=precision,
                recall=recall,
                f1=f1,
                prediction_error=prediction_error,
            )
        )

    micro_precision = _safe_div(float(micro_tp), float(micro_tp + micro_fp))
    micro_recall = _safe_div(float(micro_tp), float(micro_tp + micro_fn))
    micro_f1 = _f1(micro_precision, micro_recall)

    per_characteristic_summary: dict[str, dict[str, float | int]] = {}
    for characteristic in universe:
        bucket = per_char_counts[characteristic]
        tp = bucket["tp"]
        fp = bucket["fp"]
        fn = bucket["fn"]
        tn = bucket["tn"]
        p = _safe_div(float(tp), float(tp + fp))
        r = _safe_div(float(tp), float(tp + fn))
        f = _f1(p, r)
        per_characteristic_summary[characteristic.value] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "support": tp + fn,
            "precision": p,
            "recall": r,
            "f1": f,
        }

    n_queries = len(queries)
    summary: dict[str, object] = {
        "n_queries": n_queries,
        "n_predictions": len(predictions),
        "missing_predictions": missing_predictions,
        "prediction_errors": prediction_errors,
        "characteristic_exact_match_rate": _safe_div(float(exact_match_hits), float(n_queries)),
        "expected_subset_recall_rate": _safe_div(float(subset_recall_hits), float(n_queries)),
        "macro_precision": _mean(query_precisions),
        "macro_recall": _mean(query_recalls),
        "macro_f1": _mean(query_f1s),
        "micro_precision": micro_precision,
        "micro_recall": micro_recall,
        "micro_f1": micro_f1,
        "action_evaluable_n": action_evaluable,
        "action_accuracy": _safe_div(float(action_hits), float(action_evaluable)) if action_evaluable > 0 else 0.0,
        "per_characteristic": per_characteristic_summary,
    }

    return per_query_scores, summary
