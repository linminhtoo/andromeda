import os
from typing import Sequence

from andromeda.dataclasses import ScoredChunk
from andromeda.llm.generation_controls import AnswerStyle, AnsweringEffort
from andromeda.llm.clients import ChatMessage, LLMClient
from andromeda.processing.metadata_models import chunk_metadata_from_value


IRRELEVANT_CHUNK_IGNORE_PROMPT = (
    "NOTE that the context may contain irrelevant chunks, especially from irrelevant companies, "
    "which are neither related to the target company nor the question. You must ignore such irrelevant chunks."
)

_DRAFT_SYSTEM_PROMPT = (
    "You are a principal investment banking analyst leading a top-tier hedge fund. "
    "You are tasked with answering questions over SEC financial filings of publicly-traded companies. "
    "Write detailed and accurate analyses that cite the provided context. "
    "Your report will be used by the portfolio manager to move millions of dollars of capital for investment. "
    "Use only the provided context to answer the question. If the context does not contain sufficient information, "
    "state that you cannot answer the question based on the provided context.\n" + IRRELEVANT_CHUNK_IGNORE_PROMPT
)

_REFINE_SYSTEM_PROMPT = (
    "You are a principal investment banking analyst leading a top-tier hedge fund. "
    "Your subordinate has written up a draft report for your review. "
    "After your review, you will finalize the report for submission to the investment board, "
    "where millions of dollars will be invested. "
    "You must:\n"
    "1) check the draft answer against the context;\n"
    "2) fix hallucinations;\n"
    "3) clearly state if context is insufficient.\n" + IRRELEVANT_CHUNK_IGNORE_PROMPT
)

_FAITHFULNESS_SCRUB_SYSTEM_PROMPT = (
    "You are the final factual editor for an SEC-filing QA assistant. "
    "Your only job is to remove unsupported claims and return a fully grounded answer."
)

_EVIDENCE_DISCIPLINE_GUIDANCE = (
    "Evidence discipline rules:\n"
    "- Use only the provided context and tool context; do not use prior knowledge.\n"
    "- Use only citation IDs that appear in the provided context headers; never invent doc/chunk IDs.\n"
    "- Do not infer specific facts, dates, numbers, or events unless they are explicitly supported by context.\n"
    "- Distinguish filing year from covered fiscal period; do not treat them as interchangeable.\n"
    "- Do not claim performance 'in YEAR' unless cited evidence explicitly covers that YEAR as the reporting period.\n"
    "- If filings are from YEAR but cover a different period, state that mismatch explicitly before conclusions.\n"
    "- For numeric claims, state the exact reporting period (for example, quarter vs year-to-date vs full year).\n"
    "- Do not mix different reporting periods into one value.\n"
    "- For strategy, growth drivers, and risk questions: include only items explicitly stated in context; "
    "do not introduce generic industry assumptions.\n"
    "- Do not reinterpret risk-factor language as positive growth drivers unless the filing explicitly does so.\n"
    "- If the question contains a personal story or other distractor text, answer only the filing-analysis request.\n"
    "- If requested information is not explicit in context, state: "
    "'Not explicitly stated in the provided context.'\n"
    "- If the question requests a specific period and evidence for that period is missing, state that limitation explicitly.\n"
    "- If support for a claim is missing, omit the claim and say it is not stated in the provided context."
)

_STYLE_GUIDANCE: dict[AnswerStyle, str] = {
    "concise": (
        "Write a concise answer. Prefer a short paragraph + bullets. "
        "Avoid long preambles. Keep it as short as possible while still accurate."
    ),
    "normal": (
        "Write a clear, structured analysis. Include key numbers and key takeaways. "
        "Keep it reasonably detailed but not overly long."
    ),
    "detailed": (
        "Write a detailed report with clear section headers (e.g., Executive summary, Key points, Risks, Data points). "
        "Be comprehensive and specific."
    ),
}

_CITATION_GUIDANCE = (
    "For each claim made, cite sources (chunks) in-line IMMEDIATELY FOLLOWING the claim "
    "using [doc=... chunk=...], "
    "where doc is the source doc_id and chunk is the unique chunk_id. "
    "Every material claim (numbers, strategy statements, risks, comparisons) must have at least one citation. "
    "Use only the provided context. Remember to ignore irrelevant chunks. "
    "Do not make uncited factual claims. "
    "Of course, at the very end of your response, please resummarize the sources cited "
    "with a 'Cited Sources' section."
)

_EFFORT_GUIDANCE: dict[AnsweringEffort, str] = {
    AnsweringEffort.LOW: "Keep synthesis compact and prioritize the most material differences.",
    AnsweringEffort.MEDIUM: "Balance breadth and depth; cover key comparisons and caveats.",
    AnsweringEffort.HIGH: "Be thorough and nuanced; include tradeoffs, caveats, and uncertainty clearly.",
}

_COMPARISON_OUTPUT_CONTRACT = (
    "Comparison output contract:\n"
    "- Start with a 'Bottom line' section (1-2 sentences) that answers the comparison question directly.\n"
    "- Include a markdown table with one row per ticker and columns: Evidence-backed strengths, "
    "Evidence-backed risks, Key quantitative signals, Confidence/caveats.\n"
    "- Add a 'Head-to-head deltas' section with explicit ticker-vs-ticker bullets.\n"
    "- End with 'Decision and uncertainty' that clearly separates what is supported vs not explicitly stated."
)


def _system_prompt(base: str, *, answer_style: AnswerStyle, extra: str | None) -> str:
    parts = [
        base.strip(),
        _EVIDENCE_DISCIPLINE_GUIDANCE.strip(),
        _STYLE_GUIDANCE[answer_style].strip(),
        _CITATION_GUIDANCE.strip(),
    ]
    if extra and extra.strip():
        parts.append(extra.strip())
    return "\n\n".join(parts)


def build_context(chunks: Sequence[ScoredChunk], max_tokens: int) -> str:
    budget_chars = max_tokens * 4
    parts: list[str] = []
    used = 0
    context_key = os.getenv("CONTEXT_METADATA_KEY", "retrieval_context").strip() or "retrieval_context"
    for sc in chunks:
        metadata = chunk_metadata_from_value(sc.chunk.metadata)
        meta_bits = [f"doc={sc.chunk.doc_id}", f"chunk={sc.chunk.id}"]
        if metadata.section_path:
            meta_bits.append(f"section={metadata.section_path}")
        # NOTE: page_no is None for all our chunks as the markdown files do not have page numbers
        meta = "[" + " ".join(meta_bits) + "]"

        text = (metadata.retrieval_text or sc.chunk.text or "").strip()
        context_raw = metadata.context_for_key(context_key)
        context = context_raw.strip() if context_raw else ""
        if context:
            block = f"{meta}\n{text}\n\nContext:\n{context}\n"
        else:
            block = f"{meta}\n{text}\n"
        if used + len(block) > budget_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)


def answer_question_two_stage(
    llm: LLMClient,
    question: str,
    reranked: Sequence[ScoredChunk],
    *,
    draft_max_tokens: int = 65_536,
    final_max_tokens: int = 32_768,
    temperature_draft: float = 0.1,
) -> tuple[str, str]:
    """
    DEPRECATED.
    """
    draft_prompt = build_draft_prompt(question, reranked, draft_max_tokens=draft_max_tokens)
    draft = llm.chat(draft_prompt, temperature=temperature_draft)

    refine_prompt = build_refine_prompt(question, draft, reranked, final_max_tokens=final_max_tokens)
    final = llm.chat(refine_prompt, temperature=0.0)
    return draft, final


def build_draft_prompt(
    question: str,
    reranked: Sequence[ScoredChunk],
    *,
    draft_max_tokens: int = 65_536,
    answer_style: AnswerStyle = "normal",
    system_extra: str | None = None,
    tool_context: str | None = None,
) -> list[ChatMessage]:
    ctx1 = build_context(reranked, max_tokens=draft_max_tokens)
    tool_block = ""
    if tool_context is not None and tool_context.strip():
        tool_block = f"Tool Context:\n{tool_context.strip()}\n\n"
    return [
        {
            "role": "system",
            "content": _system_prompt(_DRAFT_SYSTEM_PROMPT, answer_style=answer_style, extra=system_extra),
        },
        {
            "role": "user",
            "content": (
                f"Question:\n{question}\n\n"
                f"{tool_block}"
                f"Context:\n{ctx1}\n\n"
                "Write your analysis to address the question based on the provided context. "
                "Every material claim must be explicitly supported by context; otherwise state "
                "'Not explicitly stated in the provided context.' "
            ),
        },
    ]


def build_refine_prompt(
    question: str,
    draft: str,
    reranked: Sequence[ScoredChunk],
    *,
    final_max_tokens: int = 32_768,
    answer_style: AnswerStyle = "normal",
    system_extra: str | None = None,
    tool_context: str | None = None,
) -> list[ChatMessage]:
    ctx2 = build_context(reranked, max_tokens=final_max_tokens)
    tool_block = ""
    if tool_context is not None and tool_context.strip():
        tool_block = f"Tool Context:\n{tool_context.strip()}\n\n"
    return [
        {
            "role": "system",
            "content": _system_prompt(_REFINE_SYSTEM_PROMPT, answer_style=answer_style, extra=system_extra),
        },
        {
            "role": "user",
            "content": (
                f"User question:\n{question}\n\n"
                f"Draft answer:\n{draft}\n\n"
                f"{tool_block}"
                f"Context:\n{ctx2}\n\n"
                "Now write a refined answer with strict evidence discipline. "
                "Remove any claim that is not explicitly supported by context and replace with "
                "'Not explicitly stated in the provided context.' when needed. "
            ),
        },
    ]


def build_faithfulness_scrub_prompt(
    question: str,
    candidate_answer: str,
    reranked: Sequence[ScoredChunk],
    *,
    final_max_tokens: int = 32_768,
    answer_style: AnswerStyle = "normal",
    system_extra: str | None = None,
    tool_context: str | None = None,
) -> list[ChatMessage]:
    """
    Build a strict factual scrub prompt that removes unsupported claims.
    """

    ctx = build_context(reranked, max_tokens=final_max_tokens)
    tool_block = ""
    if tool_context is not None and tool_context.strip():
        tool_block = f"Tool Context:\n{tool_context.strip()}\n\n"
    return [
        {
            "role": "system",
            "content": _system_prompt(_FAITHFULNESS_SCRUB_SYSTEM_PROMPT, answer_style=answer_style, extra=system_extra),
        },
        {
            "role": "user",
            "content": (
                f"User question:\n{question}\n\n"
                f"Candidate answer:\n{candidate_answer}\n\n"
                f"{tool_block}"
                f"Context:\n{ctx}\n\n"
                "Rewrite the candidate answer so every material claim is explicitly supported by context/tool context. "
                "Delete unsupported claims instead of softening them. "
                "If requested information is missing, state exactly: "
                "'Not explicitly stated in the provided context.' "
                "Return only the revised final answer."
            ),
        },
    ]


def build_ticker_brief_prompt(
    *,
    question: str,
    ticker: str,
    reranked: Sequence[ScoredChunk],
    brief_max_tokens: int = 8_000,
    answer_style: AnswerStyle = "normal",
    system_extra: str | None = None,
    tool_context: str | None = None,
) -> list[ChatMessage]:
    """
    Build one-ticker brief prompt for multi-ticker map/reduce answering.
    """

    ctx = build_context(reranked, max_tokens=brief_max_tokens)
    tool_block = f"Tool Context:\n{tool_context.strip()}\n\n" if tool_context and tool_context.strip() else ""
    default_extra = (
        f"You are writing a standalone investment brief for ticker {ticker}. "
        "Focus only on this ticker and cite claims from context."
    )
    merged_extra = default_extra if not system_extra else f"{default_extra}\n{system_extra.strip()}"
    return [
        {
            "role": "system",
            "content": _system_prompt(_DRAFT_SYSTEM_PROMPT, answer_style=answer_style, extra=merged_extra),
        },
        {
            "role": "user",
            "content": (
                f"Question:\n{question}\n\n"
                f"Target ticker for this brief: {ticker}\n\n"
                f"{tool_block}"
                f"Context:\n{ctx}\n\n"
                "Write an evidence-backed brief for this ticker only."
            ),
        },
    ]


def build_multi_ticker_synthesis_prompt(
    *,
    question: str,
    per_ticker_briefs: dict[str, str],
    final_max_tokens: int = 32_768,
    answer_style: AnswerStyle = "normal",
    answering_effort: AnsweringEffort = AnsweringEffort.MEDIUM,
    comparison_required: bool = False,
    tool_context: str | None = None,
) -> list[ChatMessage]:
    """
    Build synthesis prompt that combines per-ticker briefs into one answer.
    """

    _ = final_max_tokens
    brief_lines: list[str] = []
    for ticker, brief in per_ticker_briefs.items():
        brief_lines.append(f"Ticker {ticker} brief:\n{brief}")
    brief_block = "\n\n".join(brief_lines) if brief_lines else "(none)"
    tool_block = f"Tool Context:\n{tool_context.strip()}\n\n" if tool_context and tool_context.strip() else ""
    system_extra = (
        "You are synthesizing a final multi-ticker answer from per-ticker briefs. "
        "Preserve citations from the briefs and do not invent new evidence.\n" + _EFFORT_GUIDANCE[answering_effort]
    )
    if comparison_required:
        system_extra = system_extra + "\n" + _COMPARISON_OUTPUT_CONTRACT
    comparison_block = ""
    if comparison_required:
        comparison_block = (
            "This is a comparison request. You must follow the comparison output contract exactly "
            "and keep every comparative claim evidence-backed.\n\n"
        )
    return [
        {
            "role": "system",
            "content": _system_prompt(_DRAFT_SYSTEM_PROMPT, answer_style=answer_style, extra=system_extra),
        },
        {
            "role": "user",
            "content": (
                f"Question:\n{question}\n\n"
                f"{tool_block}"
                f"{comparison_block}"
                f"Per-ticker briefs:\n{brief_block}\n\n"
                "Write a comparative final answer grounded in the per-ticker briefs."
            ),
        },
    ]


def build_multi_ticker_refine_prompt(
    *,
    question: str,
    draft: str,
    per_ticker_briefs: dict[str, str],
    final_max_tokens: int = 32_768,
    answer_style: AnswerStyle = "normal",
    answering_effort: AnsweringEffort = AnsweringEffort.MEDIUM,
    comparison_required: bool = False,
    tool_context: str | None = None,
) -> list[ChatMessage]:
    """
    Build refine prompt for multi-ticker synthesis.
    """

    _ = final_max_tokens
    brief_lines: list[str] = []
    for ticker, brief in per_ticker_briefs.items():
        brief_lines.append(f"Ticker {ticker} brief:\n{brief}")
    brief_block = "\n\n".join(brief_lines) if brief_lines else "(none)"
    tool_block = f"Tool Context:\n{tool_context.strip()}\n\n" if tool_context and tool_context.strip() else ""
    system_extra = (
        "Refine the draft using only the per-ticker briefs and preserve valid citations.\n"
        + _EFFORT_GUIDANCE[answering_effort]
    )
    if comparison_required:
        system_extra = system_extra + "\n" + _COMPARISON_OUTPUT_CONTRACT
    comparison_block = ""
    if comparison_required:
        comparison_block = "This remains a comparison request. Preserve the required comparison structure.\n\n"
    return [
        {
            "role": "system",
            "content": _system_prompt(_REFINE_SYSTEM_PROMPT, answer_style=answer_style, extra=system_extra),
        },
        {
            "role": "user",
            "content": (
                f"User question:\n{question}\n\n"
                f"Draft answer:\n{draft}\n\n"
                f"{tool_block}"
                f"{comparison_block}"
                f"Per-ticker briefs:\n{brief_block}\n\n"
                "Now write a refined final answer."
            ),
        },
    ]
