# 18Feb2026 local-model integration research

## Context
Need to survey the repo's current dependency stack and model-loading patterns to recommend low-friction open-source local models (HF transformers / sentence-transformers / cross-encoders) for NLI/evidence support and finance-oriented retrieval/reranking tasks. The report should map candidates to existing dependencies/code paths and clearly state the integration path.

## Files to change / new files
- `agent_logs/plans/18Feb2026_local-models.md` (this planning document)
- `agent_logs/LOGBOOK.md` (append an entry summarizing the research findings and next steps)
- None planned beyond documentation updates.

## Phases
1. **Dependency & model-loading inventory**
   *Scope:* Inspect `pyproject.toml`, `package.json`, `src/` modules, and any scripts that instantiate HF sentence/transformer models to understand supported frameworks and wrappers.
   *Acceptance criteria:* Document key libraries (e.g., `transformers`, `sentence-transformers`, `faiss`, etc.) and point to the code locations where embeddings/rerankers are instantiated.

2. **Candidate model matching**
   *Scope:* Identify open-source local models (HF checkpoints) that align with NLI/evidence support and finance retrieval/reranking, ensuring they are usable with the repo's stack (Python version, dependencies, libs).
   *Acceptance criteria:* Produce a shortlist of ≥3 models per task category, highlighting license, tokenizer compatibility, required tooling (e.g., CUDA, quantization) and why they fit the repo's stack.

3. **Integration recommendation**
   *Scope:* Tie each model back to the existing modules/dependency footprint, outlining minimal code to extend a current loader (embedding retriever, reranker) and noting any dependency gaps.
   *Acceptance criteria:* Provide a brief roadmap that references the specific files/classes/functions to update and suggests whether HF `AutoModel...`, `sentence-transformers`, or cross-encoder wrappers are the lowest-friction option.

## Potential Add-ons (not in current scope)
- Benchmark a selected model locally using existing eval harness to confirm quality/latency.
- Implement adapters or wrappers to load quantized variants via `bitsandbytes` or `transformers` quantization utilities.
