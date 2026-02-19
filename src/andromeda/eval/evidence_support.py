from __future__ import annotations

import math
from dataclasses import dataclass

from sentence_transformers import CrossEncoder


@dataclass(frozen=True)
class CitationSupportSummary:
    """
    Citation support stats for one answer.
    """

    citation_count: int
    supported_citation_count: int
    unsupported_citation_count: int
    supported_rate: float


@dataclass(frozen=True)
class ClaimSupportSummary:
    """
    Claim-level support stats for one answer.
    """

    claim_count: int
    supported_claim_count: int
    contradicted_claim_count: int
    unsupported_claim_count: int
    support_rate: float
    contradiction_rate: float
    unsupported_rate: float


def citation_support_summary(*, cited_chunk_ids: list[str], available_chunk_ids: list[str]) -> CitationSupportSummary:
    """
    Compute citation support coverage against available chunk ids.
    """

    cited = [item for item in cited_chunk_ids if item]
    if not cited:
        return CitationSupportSummary(
            citation_count=0, supported_citation_count=0, unsupported_citation_count=0, supported_rate=math.nan
        )

    available = set(item for item in available_chunk_ids if item)
    supported = sum(1 for item in cited if item in available)
    unsupported = len(cited) - supported
    return CitationSupportSummary(
        citation_count=len(cited),
        supported_citation_count=supported,
        unsupported_citation_count=unsupported,
        supported_rate=(supported / len(cited)),
    )


def split_claim_like_units(answer_text: str, *, max_claims: int = 8, min_chars: int = 30) -> list[str]:
    """
    Split an answer into claim-like text units for support scoring.
    """

    if not answer_text.strip():
        return []

    out: list[str] = []
    for line in answer_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        pieces = [part.strip() for part in stripped.split(". ") if part.strip()]
        for piece in pieces:
            if len(piece) < min_chars:
                continue
            out.append(piece)
            if len(out) >= max_claims:
                return out
    return out[:max_claims]


class EntailmentScorer:
    """
    Local cross-encoder entailment scorer for claim-evidence support checks.
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/nli-deberta-v3-base",
        max_length: int = 512,
        batch_size: int = 128,
        device: str | None = None,
        predict_chunk_size: int | None = None,
    ):
        self.model_name = model_name
        self.model = CrossEncoder(model_name, max_length=max_length)
        self.batch_size = max(1, int(batch_size))
        self.predict_chunk_size = predict_chunk_size
        self.device = self._resolve_device(device)
        id2label = getattr(self.model.model.config, "id2label", {}) or {}
        entailment_id: int | None = None
        contradiction_id: int | None = None
        for idx, label in id2label.items():
            lowered = str(label).strip().lower()
            if "entail" in lowered:
                entailment_id = int(idx)
            if "contrad" in lowered:
                contradiction_id = int(idx)
        self.entailment_id = entailment_id if entailment_id is not None else 2
        self.contradiction_id = contradiction_id if contradiction_id is not None else 0

    @staticmethod
    def _resolve_device(device: str | None) -> str | None:
        """
        Resolve a concrete device for CrossEncoder.predict.
        """

        if device and device.strip():
            return device.strip()
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
        except Exception:
            return None
        return None

    def score_claims_against_evidence(
        self,
        *,
        claims: list[str],
        evidence_blocks: list[str],
        support_threshold: float = 0.50,
        contradiction_threshold: float = 0.50,
    ) -> ClaimSupportSummary:
        """
        Score claim support/contradiction against evidence blocks.
        """

        valid_claims = [item.strip() for item in claims if item and item.strip()]
        valid_evidence = [item.strip() for item in evidence_blocks if item and item.strip()]
        if not valid_claims:
            return ClaimSupportSummary(
                claim_count=0,
                supported_claim_count=0,
                contradicted_claim_count=0,
                unsupported_claim_count=0,
                support_rate=math.nan,
                contradiction_rate=math.nan,
                unsupported_rate=math.nan,
            )
        if not valid_evidence:
            return ClaimSupportSummary(
                claim_count=len(valid_claims),
                supported_claim_count=0,
                contradicted_claim_count=0,
                unsupported_claim_count=len(valid_claims),
                support_rate=0.0,
                contradiction_rate=0.0,
                unsupported_rate=1.0,
            )

        pairs: list[tuple[str, str]] = []
        for claim in valid_claims:
            for evidence in valid_evidence:
                pairs.append((claim, evidence))
        outputs = self.model.predict(
            pairs,
            apply_softmax=True,
            batch_size=self.batch_size,
            show_progress_bar=False,
            device=self.device,
            chunk_size=self.predict_chunk_size,
        )

        supported = 0
        contradicted = 0
        unsupported = 0
        evidence_count = len(valid_evidence)
        for idx, _claim in enumerate(valid_claims):
            row = outputs[idx * evidence_count : (idx + 1) * evidence_count]
            max_entailment = max(float(item[self.entailment_id]) for item in row)
            max_contradiction = max(float(item[self.contradiction_id]) for item in row)
            if max_entailment >= support_threshold:
                supported += 1
            elif max_contradiction >= contradiction_threshold:
                contradicted += 1
            else:
                unsupported += 1

        claim_count = len(valid_claims)
        return ClaimSupportSummary(
            claim_count=claim_count,
            supported_claim_count=supported,
            contradicted_claim_count=contradicted,
            unsupported_claim_count=unsupported,
            support_rate=(supported / claim_count),
            contradiction_rate=(contradicted / claim_count),
            unsupported_rate=(unsupported / claim_count),
        )
