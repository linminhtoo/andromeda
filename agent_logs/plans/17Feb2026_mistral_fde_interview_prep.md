# 17Feb2026 - Mistral FDE interview prep (Andromeda)

## Goal
Craft a comprehensive interview game plan and Q&A set grounded in this repo (README, FUTURE_WORKS, core runtime/retrieval/LLM code) plus a deep-dive on implementing open-ended sector queries (e.g., "underrated semiconductor company").

## Phases

### Phase 1: Source digestion
- Scope: Review README.md, FUTURE_WORKS.md, README_EVAL.md, and key runtime/retrieval/LLM modules for facts.
- Acceptance criteria:
  - Key architecture, planning, retrieval, evaluation, and tooling details are extracted with file references.
  - Open-ended/narrative routing mechanisms and current limitations are identified.

### Phase 2: Interview narrative framing
- Scope: Build the "story" the candidate should tell (product lens, engineering trade-offs, eval discipline).
- Acceptance criteria:
  - Clear, structured talking points mapped to Mistral FDE expectations (customer empathy, deployment pragmatism).

### Phase 3: Comprehensive Q&A bank
- Scope: Draft a large question set with model answers across design, trade-offs, retrieval, eval, ops, and product.
- Acceptance criteria:
  - Each question has a concise, technically grounded model answer.
  - Answers reference concrete implementation details in this repo.

### Phase 4: Open-ended query deep dive
- Scope: Provide a pragmatic implementation path for open-ended, no-ticker queries in this codebase.
- Acceptance criteria:
  - Clear data flow, ranking logic, and system changes described.
  - Risks/edge cases and eval additions are called out.

### Phase 5: Documentation
- Scope: Append a brief LOGBOOK entry summarizing work and observations.
- Acceptance criteria:
  - LOGBOOK entry notes that only documentation/analysis artifacts were produced.

## Files to change
- agent_logs/plans/17Feb2026_mistral_fde_interview_prep.md
- agent_logs/LOGBOOK.md

## New files
- None beyond the plan file above.

## Technical approach (summary)
- Use existing runtime/planner/retrieval/LLM/eval code to ground the Q&A.
- Emphasize tools-first routing, hybrid retrieval (pgvector + BM25), evidence discipline, and eval reliability.
- For open-ended sector queries, propose a two-stage "candidate discovery -> evidence-backed ranking" approach using the indexed ticker catalog plus finance tool metadata (sector/industry) and filing retrieval for justification.

## Suggested add-ons (not in scope)
- Create a lightweight interview slide deck.
- Add a demo script that exercises the open-ended query path.
- Build a benchmark of open-ended sector prompts for eval coverage.
