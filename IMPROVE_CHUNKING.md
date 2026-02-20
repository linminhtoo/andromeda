# Improve Chunking: HTML -> Markdown -> Retrieval Chunks

Date: 2026-02-20
Scope: Analysis + brainstorming (no code changes in this document)

## 1) Current Pipeline (What Happens Today)

### Stage A: SEC HTML -> Markdown
Primary script: `scripts/process_html_to_markdown.py`

1. Enumerates filing HTML files and optional sidecar metadata.
2. Detects form type from sidecar metadata or filename (`detect_form_type`).
3. Chooses parser mode (`select_parser`) with 10-Q parser defaults and fallbacks for non-10-Q forms.
4. Parses HTML into sec-parser elements.
5. Renders elements to markdown (`render_elements_to_markdown`):
   - drops irrelevant structural noise (headers/page numbers/irrelevant/image placeholders),
   - converts section/title elements into markdown headings,
   - normalizes paragraph text (whitespace/bullet normalization),
   - normalizes table markdown (`normalize_markdown_table`) so downstream table chunking is stable.
6. Writes:
   - `processed_markdown/*.md`
   - debug sidecars `debug/*/metadata.json`, `debug/*/run_info.json`

Key refs:
- `scripts/process_html_to_markdown.py:267`
- `scripts/process_html_to_markdown.py:339`
- `scripts/process_html_to_markdown.py:392`
- `scripts/process_html_to_markdown.py:470`

### Stage B: Markdown -> DocChunk JSONL
Primary script: `scripts/chunk.py`

1. Loads markdown files and selects chunker:
   - default `markdown_table_preserving`
   - optional `docling_hybrid`
2. Runs postprocessor pipeline:
   - `DocumentContextPostprocessor`
   - `SectionLinkPostprocessor`
   - `HeuristicSummaryPostprocessor`
3. Writes per-doc chunk JSONL under `chunks/` and `doc_index.jsonl` manifest.

Key refs:
- `scripts/chunk.py:283`
- `scripts/chunk.py:292`
- `scripts/chunk.py:395`
- `scripts/chunk.py:417`

### Stage C: Optional contextualization + index build
Primary script: `scripts/build_index.py`

1. Rehydrates `DocChunk` rows from `chunks/*.jsonl`.
2. Optionally applies context strategy (`none`, `document`, `neighbors`, `metadata`) and stores to metadata key (`retrieval_context` by default).
3. Indexer resolves retrieval payload (`retrieval_text`, `retrieval_context`, combined embedding text) and stores in Postgres.
4. Retrieval/rerank later reuse this same metadata.

Key refs:
- `scripts/build_index.py:584`
- `src/andromeda/processing/context_support.py:72`
- `src/andromeda/retrieval/retriever.py:144`
- `src/andromeda/retrieval/retriever.py:184`

## 2) What Special Handling Is Already Producing Better Chunks

### HTML->Markdown normalization
- Table normalization removes empty columns and enforces separator rows, giving consistent markdown tables.
- Paragraph normalization handles SEC bullet glyphs and whitespace artifacts.
- Duplicate consecutive blocks are suppressed to reduce repeated noise.

### Table-preserving markdown chunker behavior
Primary class: `MarkdownTablePreservingChunker` (`src/andromeda/processing/chunking.py:191`)

- Parses markdown into explicit block kinds: `page`, `heading`, `table`, `text`.
- Preserves table blocks as standalone chunks (optionally split only when oversized).
- Tracks heading hierarchy (`headings`) for each chunk.
- Tracks `line_start` / `line_end` metadata for source jumps and debugging.
- Supports page inference from inline page markers and TOC metadata.
- Uses HuggingFace tokenizer-based token counting (not whitespace counting).
- Applies overlap only between text chunks and deliberately resets overlap around tables.

### Oversize control and readability heuristics
- Oversized text blocks are split sentence-first, then token-window fallback.
- Oversized tables can be row-split while preserving header/separator.

### Postprocessing enrichment for retrieval quality
- `DocumentContextPostprocessor` attaches ticker/company/filing metadata and period-derived fields.
- `SectionLinkPostprocessor` adds stable section IDs and adjacency links.
- `HeuristicSummaryPostprocessor` builds `retrieval_text` prefix (doc context + section + page + optional summary) used downstream for embedding/sparse retrieval.

## 3) Gaps and Risks in Current Chunk Quality

1. Text summary path is effectively disabled for non-table chunks.
- `_summarize_text` currently raises `RuntimeError`, so text chunks do not get useful summaries.
- Ref: `src/andromeda/processing/chunk_postprocess.py:457`

2. Table detection in postprocessor is partially heuristic and marked broken.
- `_looks_like_pipe_table` has explicit `FIXME/TODO`; misses mixed text+table cases.
- Ref: `src/andromeda/processing/chunk_postprocess.py:423`

3. Regex-heavy markdown parsing can be brittle on real filing edge cases.
- Headings, tables, sentence splitting, and page markers rely on regex rules.
- Complex nested tables/lists/HTML-in-markdown can still degrade block boundaries.

4. Chunk boundaries are token-safe but not fact-safe.
- Numeric facts (metric/value/period/unit) may still split from nearby qualifiers or table headers in hard cases.

5. Repeated boilerplate is not explicitly deduplicated semantically.
- Risk factors/disclaimers often recur; duplicates can consume retrieval budget.

6. Default chunk ID strategy in `scripts/chunk.sh` is UUID.
- IDs are not stable across reruns unless strategy is overridden, complicating longitudinal analysis and label reuse.

7. No first-class chunk-quality KPI report at chunking time.
- We lack automatic gates for chunk length distribution, table integrity, heading coverage, duplication, and period/value preservation.

## 4) Improvement Ideas (Prioritized)

### Priority 0: Quick wins

1. Replace failing text summary path with deterministic extractive summary.
- Implement non-LLM summary fallback for prose chunks.
- Keep it short and deterministic to avoid noise.

2. Remove heuristic table detection in postprocessor when block metadata is available.
- Prefer `block_type` from chunker as source of truth.
- Fall back conservatively only when metadata is missing.

3. Add chunk quality report command.
- Emit per-run metrics: token quantiles, chunk counts by block type, duplicate ratio, average heading depth, percent chunks with doc metadata, percent oversized chunks.

4. Promote stable doc IDs for benchmark/eval profiles.
- Use `sha1_relpath` by default for reproducible corpora where appropriate.

### Priority 1: Structural robustness

1. Move markdown block parsing from regex to a markdown AST parser.
- Use a parser that preserves tables/headings/list blocks robustly.
- Keep page-marker support as an explicit extension.

2. Add financial-table aware metadata extraction.
- Capture table title, header rows, units/scales, and optional normalized metric labels.
- Store structured table metadata on chunks for better retrieval/rerank features.

3. Add semantic near-duplicate suppression.
- Within document: suppress repeated boilerplate chunks or mark as low-priority retrieval candidates.

### Priority 2: Retrieval-oriented chunk semantics

1. Add fact-aware split safeguards for numeric statements.
- Keep value + metric + period + unit together when possible.
- Especially for financial statements and MD&A numeric commentary.

2. Add retrieval_text budget controls.
- Cap/weight prefixes (doc context/section/page/summary) so signal does not overwhelm core chunk text.

3. Add corpus-level calibration loop.
- Use retrieval eval slices to tune chunk parameters by query type (factual vs narrative vs comparison) rather than one global setting.

## 5) Practical “Good Chunk” Acceptance Criteria

A chunking profile should be considered good when all are true:

1. Tables survive with parseable headers/rows in chunk text.
2. Numeric fact queries retrieve at least one chunk containing metric+value+period together.
3. Chunk length distribution avoids extreme tails and frequent truncation artifacts.
4. Duplicate/chatter chunks are low in top-k retrieval for representative query sets.
5. Source traceability remains strong (`line_start`, `line_end`, page, headings).

## 6) Suggested Next Increment (Low Risk)

1. Fix `HeuristicSummaryPostprocessor` text summary path and table detection reliability.
2. Add chunk quality diagnostics to chunk/build-index run outputs.
3. Re-run retrieval eval on factual queries and compare pre/post changes.

This gives measurable gains without redesigning the full parser/chunker stack.

## 7) Deep Dive: How the Current Chunker Works (with Code References)

### 7.1 Which chunker is used by default

- The chunk CLI defaults to `markdown_table_preserving` (`scripts/chunk.py:122`, `scripts/chunk.py:124`).
- Default chunk budget at CLI level is `max_tokens=1024`, `overlap_tokens=128` (`scripts/chunk.py:157`, `scripts/chunk.py:158`).
- `scripts/chunk.sh` also defaults to markdown-table-preserving unless overridden (`scripts/chunk.sh:19`).
- Chunker selection is wired in `_build_chunker(...)` (`scripts/chunk.py:292`, `scripts/chunk.py:295`).

### 7.2 Boundary detection in `MarkdownTablePreservingChunker`

Core parser:
- `MarkdownTablePreservingChunker` class (`src/andromeda/processing/chunking.py:191`).
- Block iterator that drives boundaries: `_iter_blocks(...)` (`src/andromeda/processing/chunking.py:355`).

Boundary rules:
1. Page markers:
- Detects `<span id=\"page-x-y\"></span>` and emits a `page` block (`src/andromeda/processing/chunking.py:363`).
2. Headings:
- Markdown heading regex `#...######` emits a `heading` block (`src/andromeda/processing/chunking.py:206`, `src/andromeda/processing/chunking.py:374`).
3. Tables:
- A table starts only when current line has `|` and next line matches markdown separator pattern (`src/andromeda/processing/chunking.py:346`, `src/andromeda/processing/chunking.py:353`).
- Table block consumes contiguous pipe rows (`src/andromeda/processing/chunking.py:386`).
4. Text paragraphs:
- Text runs until blank line, page marker, heading, or table-start (`src/andromeda/processing/chunking.py:397`, `src/andromeda/processing/chunking.py:408`).

### 7.3 How chunk assembly works (flush strategy)

Assembly happens in `chunk_document(...)` (`src/andromeda/processing/chunking.py:448`):

- Maintains a text buffer (`buf_parts`, `buf_tokens`) and emits a chunk on `flush_buffer()` (`src/andromeda/processing/chunking.py:457`, `src/andromeda/processing/chunking.py:463`).
- Flush is forced when a heading appears (`src/andromeda/processing/chunking.py:506`, `src/andromeda/processing/chunking.py:507`).
- Flush is forced before each table block (`src/andromeda/processing/chunking.py:522`, `src/andromeda/processing/chunking.py:523`).
- Emitted chunk metadata includes:
  - `block_type` (`text` or `table`),
  - `line_start` / `line_end`,
  - `headings` snapshot,
  - `page_no` (`src/andromeda/processing/chunking.py:475`, `src/andromeda/processing/chunking.py:527`).

### 7.4 Oversized text handling

Text oversize logic:
- `_split_long_text_block(...)` (`src/andromeda/processing/chunking.py:290`).

Strategy:
1. If block already fits token budget, return as-is (`src/andromeda/processing/chunking.py:299`).
2. Otherwise split by sentence and pack sentences under `max_tokens` (`src/andromeda/processing/chunking.py:302`, `src/andromeda/processing/chunking.py:320`).
3. If one sentence is still too large, split by token windows (`src/andromeda/processing/chunking.py:326`, `src/andromeda/processing/chunking.py:334`).
4. Window stride uses `max_tokens - overlap_tokens` (bounded to at least 1) (`src/andromeda/processing/chunking.py:331`).

During buffer fill:
- If adding the next part would exceed budget, flush and continue (`src/andromeda/processing/chunking.py:558`).

### 7.5 Oversized table handling

Table oversize logic:
- `_split_table_if_needed(...)` (`src/andromeda/processing/chunking.py:415`).

Behavior:
- If `split_tables` is disabled, table stays whole (`src/andromeda/processing/chunking.py:416`).
- If enabled and table exceeds `max_tokens`, split by rows while repeating header + separator per chunk (`src/andromeda/processing/chunking.py:430`, `src/andromeda/processing/chunking.py:437`).

### 7.6 Overlap handling details

Overlap mechanism:
- Tail overlap text is extracted from previous emitted text chunk token tail (`_tail_overlap`) (`src/andromeda/processing/chunking.py:281`).
- Carry overlap is prepended to the next text chunk only when safe for budget (`src/andromeda/processing/chunking.py:552`, `src/andromeda/processing/chunking.py:554`).
- After table emission, carry is explicitly reset, so table content is not blended into subsequent text overlap (`src/andromeda/processing/chunking.py:542`).

### 7.7 Heading/page propagation

- Heading stack is maintained hierarchically (pop to level, append title) (`src/andromeda/processing/chunking.py:513`, `src/andromeda/processing/chunking.py:515`).
- Page is inferred both from inline markers and TOC metadata sidecar:
  - load TOC map (`src/andromeda/processing/chunking.py:248`),
  - apply TOC heading->page mapping on heading transitions (`src/andromeda/processing/chunking.py:517`, `src/andromeda/processing/chunking.py:519`).

### 7.8 Docling hybrid mode (non-default path)

If `--chunker docling_hybrid` is selected:
- Uses Docling `HybridChunker` with `merge_peers=True` (`src/andromeda/processing/chunking.py:51`, `src/andromeda/processing/chunking.py:54`).
- Boundary/splitting are delegated to Docling internals, not custom markdown block parsing (`src/andromeda/processing/chunking.py:149`, `src/andromeda/processing/chunking.py:156`).
- Optional table fencing can be applied before Docling markdown conversion (`src/andromeda/processing/chunking.py:107`, `src/andromeda/processing/chunking.py:111`, `src/andromeda/processing/chunking.py:576`).

### 7.9 Where this behavior is validated in tests

- Boundary + heading/page + overlap behavior:
  - `tests/test_chunking_markdown.py:22`
- Oversized table splitting:
  - `tests/test_chunking_markdown.py:70`
- Oversized text block splitting:
  - `tests/test_chunking_markdown.py:86`
