# HTML->Markdown->Chunking Analysis and Improvement Memo Plan

Date: 2026-02-20
Owner: Codex agent
Scope: Documentation-only analysis of current ingestion/chunking and improvement ideas

## Objective
Write `IMPROVE_CHUNKING.md` explaining:
- how SEC HTML is converted to markdown,
- how markdown is chunked,
- what special handling currently improves chunk quality,
- what should be improved next.

## Technical Approach
- Read pipeline sources (`scripts/process_html_to_markdown.py`, `scripts/chunk.py`, `src/andromeda/processing/chunking.py`, `src/andromeda/processing/chunk_postprocess.py`, `scripts/build_index.py`).
- Cross-check behavior with tests (`tests/test_sec_html_to_markdown.py`, `tests/test_chunking_markdown.py`, `tests/test_chunk_postprocess.py`).
- Produce a practical recommendation list ordered by expected impact.

## files_to_change
- `IMPROVE_CHUNKING.md`
- `agent_logs/LOGBOOK.md`

## new_files
- `agent_logs/plans/20260220_0115_improve_chunking_memo.md`

## Phases

### Phase 1: Pipeline mapping
- Document each stage and handoff artifact from HTML to indexed chunks.

Acceptance criteria:
- Clear stage map with scripts/modules and responsibilities.

### Phase 2: Quality mechanism audit
- Enumerate current “good chunk” mechanisms and known failure points.

Acceptance criteria:
- Explicit list of implemented safeguards and identified gaps.

### Phase 3: Improvement memo
- Write prioritized improvements with rationale and quick-win vs longer-term options.

Acceptance criteria:
- `IMPROVE_CHUNKING.md` is actionable and aligned with current code/tests.

### Phase 4: Validation
- Run required repository checks and append logbook entry.

Acceptance criteria:
- `pre-commit run --all` passes.
- `pytest tests/` passes.
