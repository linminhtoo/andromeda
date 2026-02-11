from __future__ import annotations

from scripts.process_html_to_markdown import (
    detect_form_type,
    normalize_markdown_table,
    render_elements_to_markdown,
)


class TopSectionTitle:
    def __init__(self, text: str, level: int):
        self.text = text
        self.level = level


class TitleElement:
    def __init__(self, text: str, level: int):
        self.text = text
        self.level = level


class TextElement:
    def __init__(self, text: str):
        self.text = text


class TableElement:
    def __init__(self, markdown: str):
        self._markdown = markdown
        self.text = markdown

    def table_to_markdown(self) -> str:
        return self._markdown


class IntroductorySectionElement:
    def __init__(self, text: str):
        self.text = text


def test_detect_form_type_prefers_metadata_then_filename() -> None:
    assert (
        detect_form_type(
            filename="AMD_000000248825000012_10-K_2025-02-05.html",
            metadata={"form": "10-Q"},
        )
        == "10-Q"
    )
    assert (
        detect_form_type(
            filename="AMD_000000248825000012_10-K_2025-02-05.html",
            metadata=None,
        )
        == "10-K"
    )


def test_normalize_markdown_table_adds_separator_and_drops_empty_columns() -> None:
    raw = "|  | Revenue |  |\n|  | 10 |  |\n|  | 20 |  |\n"
    out = normalize_markdown_table(raw)

    lines = out.splitlines()
    assert lines[0] == "| Revenue |"
    assert lines[1] == "| --- |"
    assert lines[2] == "| 10 |"
    assert lines[3] == "| 20 |"


def test_render_elements_to_markdown_builds_headings_text_and_tables() -> None:
    elements = [
        IntroductorySectionElement("skip me"),
        TopSectionTitle("PART I", level=0),
        TopSectionTitle("Item 1", level=1),
        TitleElement("Business", level=0),
        TextElement("one bullet•two bullet"),
        TableElement("|  | A |  |\n|  | 1 |  |\n"),
    ]

    markdown, stats = render_elements_to_markdown(elements)

    assert "# PART I" in markdown
    assert "## Item 1" in markdown
    assert "### Business" in markdown
    assert "one bullet" in markdown
    assert "- two bullet" in markdown

    # Table should be normalized into a valid markdown table block.
    assert "| A |" in markdown
    assert "| --- |" in markdown
    assert "| 1 |" in markdown

    assert stats["heading_count"] == 3
    assert stats["table_count"] == 1
