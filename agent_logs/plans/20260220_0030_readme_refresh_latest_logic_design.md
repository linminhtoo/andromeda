# README Refresh Plan (Latest Logic, Design, and Architecture)

Date: 2026-02-20
Owner: Codex agent
Scope: Documentation refresh only (`README.md` + logbook note)

## Objective
Update `README.md` so it accurately reflects the current architecture, runtime flow, and recent benchmark-backed changes (planner-first tools-first routing, retrieval/rerank flow, eval stack, and ingest-profile/schema guardrails).

## Technical Approach
- Use `README.md`, `CHANGELOG.md`, `agent_logs/LOGBOOK.md`, and recent benchmark reports as the source of truth.
- Refresh architecture sections with up-to-date module boundaries and runtime behavior.
- Replace/refresh architecture diagrams (Mermaid) for:
  - request/query execution pipeline
  - ingestion/indexing pipeline
  - retrieval + reranking + eval loop
- Add a concise "Recent Changes" section with concrete metric/results pointers from benchmark files.

## files_to_change
- `README.md`
- `agent_logs/LOGBOOK.md`

## new_files
- None

## Phases

### Phase 1: Source audit and change extraction
- Collect the most relevant recent changes from changelog/logbook/benchmarks.
- Identify stale or missing README sections.

Acceptance criteria:
- A clear shortlist of changes to reflect in README.
- Benchmark metrics selected with file references for traceability.

### Phase 2: README rewrite + architecture diagrams
- Update narrative sections to align with current runtime and eval design.
- Add/update Mermaid diagrams for core architecture and data flow.
- Keep content concise and implementation-accurate.

Acceptance criteria:
- README accurately documents current logic/design and modules.
- Diagrams render-valid Mermaid syntax and match text.
- Recent changes section includes benchmark-backed highlights.

### Phase 3: Validation and documentation hygiene
- Run repository-required checks (`pre-commit`, `pytest tests/`).
- Append a concise logbook entry describing doc refresh and key observations.

Acceptance criteria:
- `pre-commit run --all` passes.
- `pytest tests/` passes.
- Logbook entry appended without modifying existing entries.

## Suggestions / Future Work (not in this scope)
- Add versioned architecture snapshots per release tag to reduce drift risk.
- Add a script that auto-checks README architecture module lists against package layout.
- Add benchmark summary tables auto-generated from eval manifests.
