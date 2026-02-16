# Citation Source Jump Reliability Plan (15 Feb 2026)

## Scope
Fix citation click behavior so the source viewer reliably jumps to the intended chunk within markdown files.

## Technical approach
1. Preserve original chunk text in API payloads.
- Keep retrieval-enriched `text` for display/ranking context.
- Add `source_text` populated from the original stored chunk text (`DocChunk.text`).
- Use `source_text` for source-viewer span matching.

2. Add line-span metadata during markdown chunking.
- In `MarkdownTablePreservingChunker`, annotate each chunk metadata with:
  - `line_start` (1-based)
  - `line_end` (1-based, inclusive)
- Carry line spans for text and table chunks (and split text/table parts where applicable).

3. Surface line-span metadata in query responses.
- Extend UI metadata serialization in `query_runtime` to include line metadata keys.
- Keep backward compatibility (optional metadata fields).

4. Use deterministic line spans first in source viewer.
- In `source-viewer.ts`, when line spans exist, derive mark spans directly from source line offsets.
- Fallback to fuzzy text matching when line spans are unavailable.

5. Maintain runtime parity for streaming and non-stream responses.
- Add `source_text` to stream chunk payloads.

## Phases

### Phase 1: Backend payload and metadata propagation
Acceptance criteria:
- `TopChunk` and stream payload include `source_text`.
- Query response metadata can include line span fields when present.

### Phase 2: Markdown chunk line-span emission
Acceptance criteria:
- Markdown chunker writes `line_start`/`line_end` metadata for emitted chunks.
- Existing chunking tests pass or are updated for the new metadata behavior.

### Phase 3: Frontend source-viewer jump logic
Acceptance criteria:
- Citation jump uses line spans when available.
- If line spans are absent, existing fuzzy matching remains functional.
- Clicking citation scrolls to active chunk mark (not just opening file).

### Phase 4: Validation and documentation
Acceptance criteria:
- `source .venv/bin/activate && pre-commit run --all` passes.
- `source .venv/bin/activate && pytest -vvv tests/` passes.
- `CHANGELOG.md` updated for behavior change.
- `agent_logs/LOGBOOK.md` appended with key notes and validation results.
- Validation script saved under `agent_logs/`.

## files_to_change
- `src/finrag/dataclasses.py`
- `src/finrag/query_runtime.py`
- `src/finrag/query_streaming.py`
- `src/finrag/chunking.py`
- `src/finrag/static/ts/index/source-viewer.ts`
- `src/finrag/static/js/index/source-viewer.js` (generated via TS build)
- `src/finrag/static/js/index/main.js` (generated via TS build if affected)
- `CHANGELOG.md`
- `tests/test_chunking_markdown.py` (if assertions need extension)
- `tests/test_query_runtime.py` / `tests/test_query_streaming.py` (if present and needed)
- `agent_logs/LOGBOOK.md`

## new_files
- `agent_logs/refactor_15Feb2026_041500_citation_source_jump_line_spans.md`
- `agent_logs/20260215_*.sh` (validation command log script)

## Future suggestions (out of current scope)
- Persist char-offset spans in chunk metadata at chunking time for exact-position rendering without recomputation.
- Add UI e2e tests that assert citation click scroll target position in source viewer.
- Add docling chunker provenance mapping to source lines where feasible.
