from __future__ import annotations

import json

from finrag.chunking import MarkdownTableCodeFencer, MarkdownTablePreservingChunker


def test_markdown_table_code_fencer_wraps_tables_and_preserves_trailing_newline() -> None:
    md = "| A | B |\n|---|---|\n| 1 | 2 |\n\nafter\n"
    out = MarkdownTableCodeFencer(fence_lang="text").fence_tables(md)
    assert out.startswith("```text\n| A | B |")
    assert out.rstrip().endswith("after")
    assert out.endswith("\n")


def test_markdown_table_code_fencer_skips_existing_code_fences() -> None:
    md = "```text\n| A | B |\n|---|---|\n| 1 | 2 |\n```\n"
    out = MarkdownTableCodeFencer(fence_lang="text").fence_tables(md)
    assert out == md


def test_markdown_table_preserving_chunker_tracks_headings_pages_and_overlap(tmp_path) -> None:
    md = (
        '<span id="page-5-1"></span>\n'
        "# Item 1. Business\n"
        "\n"
        "one two three four\n"
        "\n"
        "five six seven eight\n"
        "\n"
        "| A | B |\n"
        "|---|---|\n"
        "| 1 | 2 |\n"
        "\n"
        "after table text\n"
    )
    md_path = tmp_path / "doc.md"
    md_path.write_text(md, encoding="utf-8")

    meta = {"table_of_contents": [{"title": "Item 1. Business", "page_id": 7}]}
    meta_path = tmp_path / "meta.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    c = MarkdownTablePreservingChunker(max_tokens=6, overlap_tokens=2, split_tables=False)
    chunks = c.chunk_document(str(md_path), doc_id="d1", metadata_json_path=str(meta_path))

    assert [ch.metadata.get("block_type") for ch in chunks] == ["text", "text", "table", "text"]
    assert chunks[0].metadata.get("line_start") == 4
    assert chunks[0].metadata.get("line_end") == 4
    assert chunks[1].metadata.get("line_start") == 6
    assert chunks[1].metadata.get("line_end") == 6
    assert chunks[2].metadata.get("line_start") == 8
    assert chunks[2].metadata.get("line_end") == 10
    assert chunks[3].metadata.get("line_start") == 12
    assert chunks[3].metadata.get("line_end") == 12
    assert all(ch.page_no == 7 for ch in chunks)
    assert chunks[0].headings == ["Item 1. Business"]
    assert chunks[1].headings == ["Item 1. Business"]
    assert chunks[2].headings == ["Item 1. Business"]

    # Overlap from first -> second text chunk (tail is "three four").
    assert chunks[1].text.startswith("three four")
    assert "five six" in chunks[1].text

    # Table chunk stays verbatim-ish and should not influence overlap for next chunk.
    assert chunks[2].text.startswith("| A | B |")
    assert chunks[3].text.startswith("after table")


def test_markdown_table_preserving_chunker_can_split_large_tables(tmp_path) -> None:
    md = "# H\n\n| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n| 5 | 6 |\n"
    md_path = tmp_path / "doc.md"
    md_path.write_text(md, encoding="utf-8")

    c = MarkdownTablePreservingChunker(max_tokens=8, overlap_tokens=0, split_tables=True)
    chunks = c.chunk_document(str(md_path), doc_id="d1")

    table_chunks = [ch for ch in chunks if ch.metadata.get("block_type") == "table"]
    assert len(table_chunks) >= 2
    for ch in table_chunks:
        lines = ch.text.splitlines()
        assert lines[0].strip().startswith("|")
        assert "---" in lines[1]


def test_markdown_table_preserving_chunker_splits_oversized_text_blocks(tmp_path) -> None:
    long_sentence = " ".join(f"w{i}" for i in range(40))
    md = f"# H\n\n{long_sentence}\n\n{long_sentence}\n"
    md_path = tmp_path / "doc.md"
    md_path.write_text(md, encoding="utf-8")

    c = MarkdownTablePreservingChunker(max_tokens=20, overlap_tokens=4, split_tables=False)
    chunks = c.chunk_document(str(md_path), doc_id="d1")

    assert chunks
    text_chunks = [ch for ch in chunks if (ch.metadata or {}).get("block_type") == "text"]
    assert len(text_chunks) >= 3
    for ch in text_chunks:
        assert c._count_tokens(ch.text) <= 24  # allows small overlap carry-in
