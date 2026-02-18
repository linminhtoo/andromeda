"""
Convert SEC filing HTML documents into Markdown using `sec-parser`.

This replaces the old HTML->PDF->OCR path and parses SEC HTML directly.

Output layout (compatible with downstream chunk/index scripts):
  - <output>/processed_markdown/<relpath>.md
  - <output>/debug/<relpath_stem>/metadata.json
  - <output>/debug/<relpath_stem>/run_info.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import warnings
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from loguru import logger
from tqdm import tqdm

import sec_parser as sp

from andromeda.ingestion.ingest_profile import (
    ingest_profile_layout,
    resolve_ingest_profile_name,
    update_ingest_profile_step,
)

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_DATE_SUFFIX_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})$")
_FORM_IN_FILENAME_RE = re.compile(r"_(10-[KQ](?:/A)?|8-K|6-K|20-F|40-F|S-1|S-3|DEF 14A)_", re.IGNORECASE)
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")


@dataclass
class Args:
    html_dir: str
    output_dir: str | None
    ingest_profile: str | None
    meta_dir: str | None
    pattern: str
    recursive: bool
    year_cutoff: int | None
    max_files: int | None
    overwrite: bool
    include_irrelevant_elements: bool
    parser_mode: str
    continue_on_error: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ParserSelection:
    parser: Any
    parser_name: str
    suppress_invalid_section_warning: bool


@dataclass(frozen=True)
class ConversionResult:
    relpath: str
    source_html: str
    output_markdown: str
    metadata_path: str
    num_elements: int
    element_counts: dict[str, int]
    form_type: str | None
    parser: str
    markdown_chars: int
    table_count: int
    heading_count: int


@dataclass(frozen=True)
class ConversionFailure:
    relpath: str
    source_html: str
    error: str


def parse_args() -> Args:
    parser = argparse.ArgumentParser(description="Convert SEC filing HTML files to Markdown using sec-parser.")
    parser.add_argument("--html-dir", required=True, help="Directory containing SEC HTML files.")
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Output root directory (writes `processed_markdown/` and `debug/`). "
            "Defaults to profile-scoped `data/ingest_profiles/<profile>/sec_filings_md_secparser`."
        ),
    )
    parser.add_argument(
        "--ingest-profile",
        default=None,
        help=(
            "Profile name for persisting conversion settings to disk "
            "(default resolution: FINRAG_INGEST_PROFILE, then POSTGRES_SCHEMA, then `default`)."
        ),
    )
    parser.add_argument(
        "--meta-dir",
        default=None,
        help=(
            "Optional metadata directory with JSON sidecars matching HTML filenames. "
            "Defaults to sibling `<html-dir>/../meta` when it exists."
        ),
    )
    parser.add_argument("--pattern", default="*.htm*", help="Glob pattern for HTML files.")
    parser.add_argument("--recursive", action="store_true", help="Recurse into subdirectories.")
    parser.add_argument(
        "--year-cutoff",
        type=int,
        default=None,
        help="Only process filings with filename suffix YYYY-MM-DD where year >= cutoff.",
    )
    parser.add_argument("--max-files", type=int, default=None, help="Optional cap on number of HTML files.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing markdown outputs.")
    parser.add_argument(
        "--include-irrelevant-elements",
        action="store_true",
        help="Include sec-parser irrelevant elements (page headers/numbers/etc.).",
    )
    parser.add_argument(
        "--parser-mode",
        choices=["auto", "10q_only", "generic_10q"],
        default="auto",
        help=(
            "Parser selection mode: `auto` uses Edgar10QParser with form-aware fallbacks; "
            "`10q_only` always uses Edgar10QParser; `generic_10q` strips 10-Q top-section steps for all forms."
        ),
    )
    parser.add_argument(
        "--continue-on-error", action="store_true", help="Continue processing remaining files when one file fails."
    )

    ns = parser.parse_args()
    return Args(
        html_dir=ns.html_dir,
        output_dir=ns.output_dir,
        ingest_profile=(str(ns.ingest_profile).strip() if ns.ingest_profile is not None else None) or None,
        meta_dir=ns.meta_dir,
        pattern=ns.pattern,
        recursive=bool(ns.recursive),
        year_cutoff=ns.year_cutoff,
        max_files=ns.max_files,
        overwrite=bool(ns.overwrite),
        include_irrelevant_elements=bool(ns.include_irrelevant_elements),
        parser_mode=ns.parser_mode,
        continue_on_error=bool(ns.continue_on_error),
    )


def _setup_logging(project_root: Path) -> Path:
    logs_dir = project_root / "logs" / "process"
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"process_sec_parser_{ts}.log"

    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add(str(log_path), level="DEBUG")
    return log_path


def _iter_html_files(root: Path, *, pattern: str, recursive: bool) -> list[Path]:
    paths = list(root.rglob(pattern) if recursive else root.glob(pattern))
    return sorted(p for p in paths if p.is_file())


def _extract_year_from_filename(path: Path) -> int | None:
    m = _DATE_SUFFIX_RE.search(path.stem)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _infer_meta_root(html_root: Path, explicit_meta_dir: str | None) -> Path | None:
    if explicit_meta_dir:
        p = Path(explicit_meta_dir).expanduser().resolve()
        return p if p.exists() and p.is_dir() else None

    sibling_meta = (html_root.parent / "meta").resolve()
    if sibling_meta.exists() and sibling_meta.is_dir():
        return sibling_meta
    return None


def _load_meta_for_html(html_path: Path, *, html_root: Path, meta_root: Path | None) -> dict[str, Any] | None:
    if meta_root is None:
        return None
    rel = html_path.resolve().relative_to(html_root)
    meta_path = (meta_root / rel).with_suffix(".json")
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to load sidecar metadata for {html_path.name}: {exc}")
        return None


def detect_form_type(*, filename: str, metadata: dict[str, Any] | None) -> str | None:
    if metadata:
        form = metadata.get("form")
        if isinstance(form, str) and form.strip():
            return form.strip().upper()

    m = _FORM_IN_FILENAME_RE.search(filename)
    if m:
        return m.group(1).upper()
    return None


def _build_generic_10q_parser() -> Any:
    """
    Build a parser that skips 10-Q-specific top-section assumptions.

    This follows the approach in the sec-parser exploration notebook for
    parsing non-10-Q forms with Edgar10QParser.
    """

    try:
        from sec_parser.processing_steps import (  # type: ignore[attr-defined]
            IndividualSemanticElementExtractor,
            TopSectionManagerFor10Q,
            TopSectionTitleCheck,
        )
    except Exception:
        return sp.Edgar10QParser()

    def get_steps() -> list[Any]:
        base_parser = sp.Edgar10QParser()
        all_steps = base_parser.get_default_steps()
        steps_without_top_manager = [step for step in all_steps if not isinstance(step, TopSectionManagerFor10Q)]

        def get_checks_without_top_section_title_check() -> list[Any]:
            checks = base_parser.get_default_single_element_checks()
            return [check for check in checks if not isinstance(check, TopSectionTitleCheck)]

        updated_steps: list[Any] = []
        for step in steps_without_top_manager:
            if isinstance(step, IndividualSemanticElementExtractor):
                updated_steps.append(
                    IndividualSemanticElementExtractor(get_checks=get_checks_without_top_section_title_check)
                )
            else:
                updated_steps.append(step)
        return updated_steps

    return sp.Edgar10QParser(get_steps=get_steps)


def select_parser(*, form_type: str | None, parser_mode: str) -> ParserSelection:
    if parser_mode == "10q_only":
        return ParserSelection(
            parser=sp.Edgar10QParser(),
            parser_name="Edgar10QParser",
            suppress_invalid_section_warning=bool(form_type and form_type != "10-Q"),
        )

    if parser_mode == "generic_10q":
        return ParserSelection(
            parser=_build_generic_10q_parser(),
            parser_name="Edgar10QParser(generic_10q)",
            suppress_invalid_section_warning=False,
        )

    # parser_mode == "auto"
    if form_type == "10-Q":
        return ParserSelection(
            parser=sp.Edgar10QParser(), parser_name="Edgar10QParser", suppress_invalid_section_warning=False
        )

    if form_type == "10-K":
        return ParserSelection(
            parser=sp.Edgar10QParser(),
            parser_name="Edgar10QParser(fallback_for_10K)",
            suppress_invalid_section_warning=True,
        )

    # Other forms: use generic 10Q parser to avoid hard 10-Q section assumptions.
    return ParserSelection(
        parser=_build_generic_10q_parser(),
        parser_name="Edgar10QParser(generic_other_form)",
        suppress_invalid_section_warning=False,
    )


def _normalize_inline_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = text.replace("\u2009", " ")
    text = text.replace("\u2002", " ")
    text = re.sub(r"[\t ]+", " ", text)
    return text.strip()


def normalize_paragraph_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\xa0", " ")
    text = text.replace("\u2009", " ")
    text = text.replace("\u2002", " ")

    # SEC filings frequently use the bullet glyph inline without line breaks.
    text = re.sub(r"\s*•\s*", "\n- ", text)

    lines = [_normalize_inline_text(line) for line in text.split("\n")]
    text = "\n".join(line for line in lines if line)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_markdown_row(row: str) -> list[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [_normalize_inline_text(cell) for cell in row.split("|")]


def _render_markdown_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def normalize_markdown_table(table_markdown: str) -> str:
    """
    Normalize sec-parser table markdown for downstream table-preserving chunking.

    - trims whitespace / NBSP artifacts
    - drops columns that are empty in every row
    - guarantees a markdown separator row after the first row
    """

    raw_lines = [line for line in table_markdown.splitlines() if line.strip()]
    raw_lines = [line for line in raw_lines if "|" in line]
    if not raw_lines:
        return ""

    rows = [_parse_markdown_row(line) for line in raw_lines]
    if not rows:
        return ""

    max_cols = max(len(row) for row in rows)
    rows = [row + [""] * (max_cols - len(row)) for row in rows]

    keep_cols = [idx for idx in range(max_cols) if any(row[idx] for row in rows)]
    if keep_cols:
        rows = [[row[idx] for idx in keep_cols] for row in rows]

    # Trim shared empty columns on both sides.
    while rows and rows[0] and all(row[0] == "" for row in rows):
        rows = [row[1:] for row in rows]
    while rows and rows[0] and all(row[-1] == "" for row in rows):
        rows = [row[:-1] for row in rows]

    if not rows or not rows[0]:
        return ""

    rendered = [_render_markdown_row(row) for row in rows]
    separator = _render_markdown_row(["---"] * len(rows[0]))

    if len(rendered) == 1:
        rendered.append(separator)
    elif not _TABLE_SEPARATOR_RE.match(rendered[1]):
        rendered.insert(1, separator)

    return "\n".join(rendered).strip()


def _safe_level(element: Any, default: int = 0) -> int:
    raw = getattr(element, "level", default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def render_elements_to_markdown(elements: list[Any]) -> tuple[str, dict[str, int]]:
    blocks: list[str] = []
    block_stats = {"heading_count": 0, "table_count": 0}

    def append_block(text: str) -> None:
        normalized = text.strip()
        if not normalized:
            return
        if blocks and blocks[-1] == normalized:
            return
        blocks.append(normalized)

    for element in elements:
        cls_name = type(element).__name__

        if cls_name in {
            "IntroductorySectionElement",
            "PageHeaderElement",
            "PageNumberElement",
            "IrrelevantElement",
            "EmptyElement",
            "ImageElement",
        }:
            continue

        if cls_name == "TopSectionTitle":
            heading_level = min(max(1 + _safe_level(element, 0), 1), 6)
            heading_text = normalize_paragraph_text(getattr(element, "text", ""))
            if heading_text:
                append_block(f"{'#' * heading_level} {heading_text}")
                block_stats["heading_count"] += 1
            continue

        if cls_name == "TitleElement":
            heading_level = min(max(3 + _safe_level(element, 0), 1), 6)
            heading_text = normalize_paragraph_text(getattr(element, "text", ""))
            if heading_text:
                append_block(f"{'#' * heading_level} {heading_text}")
                block_stats["heading_count"] += 1
            continue

        if cls_name == "TableElement":
            table_text = ""
            try:
                table_text = normalize_markdown_table(element.table_to_markdown())
            except Exception:  # noqa: BLE001 - best-effort fallback
                table_text = ""
            if not table_text:
                table_text = normalize_paragraph_text(getattr(element, "text", ""))
            if table_text:
                append_block(table_text)
                block_stats["table_count"] += 1
            continue

        paragraph_text = normalize_paragraph_text(getattr(element, "text", ""))
        if paragraph_text:
            append_block(paragraph_text)

    markdown = "\n\n".join(blocks).strip()
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    if markdown:
        markdown += "\n"
    return markdown, block_stats


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()  # type: ignore[no-any-return]
        except Exception:  # noqa: BLE001
            pass
    return str(value)


def _process_one_file(
    *,
    html_file: Path,
    html_root: Path,
    meta_root: Path | None,
    markdown_root: Path,
    debug_root: Path,
    include_irrelevant_elements: bool,
    parser_mode: str,
) -> ConversionResult:
    rel = html_file.resolve().relative_to(html_root).as_posix()
    md_path = (markdown_root / rel).with_suffix(".md")
    debug_dir = debug_root / Path(rel).parent / Path(rel).stem
    debug_dir.mkdir(parents=True, exist_ok=True)

    html = html_file.read_text(encoding="utf-8", errors="ignore")
    sidecar_meta = _load_meta_for_html(html_file, html_root=html_root, meta_root=meta_root)
    form_type = detect_form_type(filename=html_file.name, metadata=sidecar_meta)

    parser_selection = select_parser(form_type=form_type, parser_mode=parser_mode)

    with warnings.catch_warnings():
        if parser_selection.suppress_invalid_section_warning:
            warnings.filterwarnings("ignore", message="Invalid section type for")

        elements = parser_selection.parser.parse(html, include_irrelevant_elements=include_irrelevant_elements)

    markdown, block_stats = render_elements_to_markdown(elements)

    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown, encoding="utf-8")

    element_counts = dict(Counter(type(el).__name__ for el in elements))

    metadata = {
        "source_html": str(html_file),
        "source_relpath": rel,
        "output_markdown": str(md_path),
        "form_type": form_type,
        "parser": parser_selection.parser_name,
        "num_elements": len(elements),
        "element_counts": element_counts,
        "heading_count": block_stats["heading_count"],
        "table_count": block_stats["table_count"],
        "markdown_chars": len(markdown),
        "table_of_contents": [],
        "input_sidecar_metadata": sidecar_meta or {},
    }

    metadata_path = debug_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8"
    )

    run_info = {
        "source_html": str(html_file),
        "source_relpath": rel,
        "output_markdown": str(md_path),
        "metadata_path": str(metadata_path),
        "form_type": form_type,
        "parser": parser_selection.parser_name,
        "include_irrelevant_elements": include_irrelevant_elements,
    }
    run_info_path = debug_dir / "run_info.json"
    run_info_path.write_text(
        json.dumps(run_info, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8"
    )

    return ConversionResult(
        relpath=rel,
        source_html=str(html_file),
        output_markdown=str(md_path),
        metadata_path=str(metadata_path),
        num_elements=len(elements),
        element_counts=element_counts,
        form_type=form_type,
        parser=parser_selection.parser_name,
        markdown_chars=len(markdown),
        table_count=block_stats["table_count"],
        heading_count=block_stats["heading_count"],
    )


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    profile_name = resolve_ingest_profile_name(args.ingest_profile)
    profile_layout = ingest_profile_layout(project_root=project_root, profile_name=profile_name)

    log_path = _setup_logging(project_root)

    html_root = Path(args.html_dir).expanduser().resolve()
    if not html_root.exists() or not html_root.is_dir():
        raise RuntimeError(f"--html-dir must be an existing directory: {html_root}")

    output_root = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir is not None
        else profile_layout.sec_filings_md_root
    )
    args.output_dir = str(output_root)
    markdown_root = output_root / "processed_markdown"
    debug_root = output_root / "debug"
    markdown_root.mkdir(parents=True, exist_ok=True)
    debug_root.mkdir(parents=True, exist_ok=True)

    meta_root = _infer_meta_root(html_root, args.meta_dir)

    logger.info(f"Project root: {project_root}")
    logger.info(f"Logging to: {log_path}")
    logger.info(f"HTML root: {html_root}")
    logger.info(f"Output root: {output_root}")
    logger.info(f"Meta root: {meta_root}")
    logger.info("Ingest profile: {}", profile_name)

    html_files = _iter_html_files(html_root, pattern=args.pattern, recursive=args.recursive)
    if args.year_cutoff is not None:
        before = len(html_files)
        html_files = [p for p in html_files if (_extract_year_from_filename(p) or 0) >= args.year_cutoff]
        logger.info(f"Year cutoff {args.year_cutoff}: {before} -> {len(html_files)} files")

    if args.max_files is not None:
        html_files = html_files[: max(0, args.max_files)]

    if not html_files:
        raise RuntimeError(f"No HTML files found under {html_root}")

    logger.info(f"Found {len(html_files)} HTML files")

    processed: list[ConversionResult] = []
    failures: list[ConversionFailure] = []

    for html_file in tqdm(html_files, desc="Converting HTML", unit="file"):
        rel = html_file.resolve().relative_to(html_root).as_posix()
        md_path = (markdown_root / rel).with_suffix(".md")
        if md_path.exists() and not args.overwrite:
            logger.info(f"Skipping existing markdown: {md_path}")
            continue

        try:
            result = _process_one_file(
                html_file=html_file,
                html_root=html_root,
                meta_root=meta_root,
                markdown_root=markdown_root,
                debug_root=debug_root,
                include_irrelevant_elements=args.include_irrelevant_elements,
                parser_mode=args.parser_mode,
            )
            processed.append(result)
            logger.success(
                f"Converted {result.relpath} -> {result.output_markdown} | parser={result.parser} "
                f"| elements={result.num_elements} | headings={result.heading_count} | tables={result.table_count}"
            )
        except Exception as exc:  # noqa: BLE001
            failure = ConversionFailure(relpath=rel, source_html=str(html_file), error=repr(exc))
            failures.append(failure)
            logger.exception(f"Failed converting {rel}: {exc}")
            if not args.continue_on_error:
                break

    run_info = {
        "args": args.to_dict(),
        "html_root": str(html_root),
        "output_root": str(output_root),
        "meta_root": str(meta_root) if meta_root else None,
        "processed_files": len(processed),
        "failed_files": len(failures),
        "log_path": str(log_path),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    run_info_path = output_root / "run_info.json"
    run_info_path.write_text(
        json.dumps(run_info, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8"
    )

    update_ingest_profile_step(
        project_root=project_root,
        profile_name=profile_name,
        step_name="process_html_to_markdown",
        settings=args.to_dict(),
        metadata={
            "output_root": str(output_root),
            "processed_files": len(processed),
            "failed_files": len(failures),
            "run_info_path": str(run_info_path),
        },
    )

    processed_index_path = output_root / "doc_index.jsonl"
    with processed_index_path.open("w", encoding="utf-8") as f:
        for rec in processed:
            row = {
                "source": rec.source_html,
                "relpath": rec.relpath,
                "markdown_path": rec.output_markdown,
                "metadata_path": rec.metadata_path,
                "form_type": rec.form_type,
                "parser": rec.parser,
                "num_elements": rec.num_elements,
                "table_count": rec.table_count,
                "heading_count": rec.heading_count,
            }
            f.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")

    errors_path = output_root / "errors.jsonl"
    with errors_path.open("w", encoding="utf-8") as f:
        for err in failures:
            f.write(json.dumps(asdict(err), ensure_ascii=False, default=_json_default) + "\n")

    logger.success(
        f"Done. processed={len(processed)} failed={len(failures)} | wrote {processed_index_path} {errors_path}"
    )

    if failures and not args.continue_on_error:
        raise RuntimeError(f"Conversion failed for {len(failures)} file(s). See logs and {errors_path}.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
