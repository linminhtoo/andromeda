from __future__ import annotations

import os
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from loguru import logger

from finrag.db import SparseSearchMethod

TickerIngestionStatus = Literal["queued", "running", "succeeded", "failed"]


@dataclass(frozen=True)
class TickerIngestionRuntimeConfig:
    """
    Runtime settings used by ticker ingestion indexing.

    Attributes
    ----------
    postgres_dsn : str
        PostgreSQL DSN used by `scripts.build_index`.
    postgres_schema : str | None
        Optional PostgreSQL schema name.
    sparse_search_method : SparseSearchMethod
        Sparse retrieval method expected by active schema/runtime.
    llm_provider : str | None
        Embedding provider name for index build.
    dense_model : str
        Embedding model used for chunk embeddings.
    dense_base_url : str | None
        Optional embedding base URL override for OpenAI-compatible endpoints.
    contextual_llm_provider : str | None
        Provider used by context generation calls.
    contextual_model : str | None
        Chat model used for context generation calls.
    contextual_base_url : str | None
        Optional context-generation base URL override.
    context_strategy : str
        Context strategy for chunk contextualization (`none`, `document`, `neighbors`, `metadata`).
    context_window : int
        Neighbor window for `neighbors` context strategy.
    context_metadata_key : str
        Metadata key used to persist generated context.
    context_max_tokens : int
        Max tokens for each context generation call.
    context_max_concurrency : int
        Max concurrent context generation calls.
    batch_size : int
        Batch size used for embedding/upsert.
    ingest_profile : str
        Name of persisted ingest profile used across pipeline steps.
    download_delay : float
        Delay between SEC requests.
    download_skip_existing : bool
        Skip downloads when destination files already exist.
    process_parser_mode : str
        Parser mode for HTML->markdown conversion.
    process_recursive : bool
        Recurse through HTML tree during conversion.
    process_continue_on_error : bool
        Continue batch conversion when one filing fails.
    chunker : str
        Chunker name used by `scripts.chunk`.
    chunk_max_tokens : int
        Max tokens per chunk.
    chunk_overlap_tokens : int
        Overlap tokens between chunks.
    chunk_recursive : bool
        Recurse markdown tree while chunking.
    chunk_doc_id_strategy : str
        Doc-id strategy for chunk export.
    chunk_split_markdown_tables : bool
        Whether to split oversized markdown tables.
    """

    postgres_dsn: str
    postgres_schema: str | None
    sparse_search_method: SparseSearchMethod
    llm_provider: str | None
    dense_model: str
    dense_base_url: str | None
    contextual_llm_provider: str | None
    contextual_model: str | None
    contextual_base_url: str | None
    context_strategy: str
    context_window: int
    context_metadata_key: str
    context_max_tokens: int
    context_max_concurrency: int
    batch_size: int
    ingest_profile: str
    download_delay: float
    download_skip_existing: bool
    process_parser_mode: str
    process_recursive: bool
    process_continue_on_error: bool
    chunker: str
    chunk_max_tokens: int
    chunk_overlap_tokens: int
    chunk_recursive: bool
    chunk_doc_id_strategy: str
    chunk_split_markdown_tables: bool


@dataclass(frozen=True)
class TickerIngestionPaths:
    """
    Filesystem layout for a single ingestion job run.
    """

    run_root: Path
    download_root: Path
    markdown_root: Path
    chunk_output_root: Path
    log_path: Path


@dataclass
class TickerIngestionJob:
    """
    In-memory state for a ticker ingestion background job.
    """

    job_id: str
    tickers: list[str]
    per_company: int
    status: TickerIngestionStatus
    stage: str
    message: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    run_root: str | None = None
    log_path: str | None = None
    doc_index_path: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """
        Return API-safe job payload.
        """

        return {
            "job_id": self.job_id,
            "tickers": list(self.tickers),
            "per_company": self.per_company,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "run_root": self.run_root,
            "log_path": self.log_path,
            "doc_index_path": self.doc_index_path,
        }


class TickerIngestionJobManager:
    """
    Manage ticker ingestion jobs executed in background threads.
    """

    def __init__(self, project_root: Path, jobs_root: Path | None = None):
        self.project_root = project_root.resolve()
        default_jobs_root = self.project_root / "data" / "on_the_fly_ingest"
        self.jobs_root = (jobs_root or default_jobs_root).resolve()
        self.jobs: dict[str, TickerIngestionJob] = {}
        self.jobs_lock = threading.Lock()

    def start_job(self, *, tickers: list[str], per_company: int, config: TickerIngestionRuntimeConfig) -> dict[str, Any]:
        """
        Create and start a ticker ingestion background job.
        """

        now_iso = now_utc_iso()
        job_id = uuid.uuid4().hex
        job = TickerIngestionJob(
            job_id=job_id,
            tickers=list(tickers),
            per_company=per_company,
            status="queued",
            stage="queued",
            message="Job queued",
            created_at=now_iso,
        )
        with self.jobs_lock:
            self.jobs[job_id] = job

        thread = threading.Thread(
            target=self.run_job,
            args=(job_id, list(tickers), per_company, config),
            daemon=True,
            name=f"ticker-ingest-{job_id[:8]}",
        )
        thread.start()
        return job.to_public_dict()

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """
        Return a public snapshot for the requested job.
        """

        with self.jobs_lock:
            job = self.jobs.get(job_id)
        if job is None:
            return None
        return job.to_public_dict()

    def update_job(
        self,
        job_id: str,
        *,
        status: TickerIngestionStatus | None = None,
        stage: str | None = None,
        message: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        run_root: str | None = None,
        log_path: str | None = None,
        doc_index_path: str | None = None,
    ) -> None:
        """
        Atomically update mutable fields on a tracked job.
        """

        with self.jobs_lock:
            if job_id not in self.jobs:
                return
            job = self.jobs[job_id]
            if status is not None:
                job.status = status
            if stage is not None:
                job.stage = stage
            if message is not None:
                job.message = message
            if started_at is not None:
                job.started_at = started_at
            if finished_at is not None:
                job.finished_at = finished_at
            if run_root is not None:
                job.run_root = run_root
            if log_path is not None:
                job.log_path = log_path
            if doc_index_path is not None:
                job.doc_index_path = doc_index_path

    def run_job(self, job_id: str, tickers: list[str], per_company: int, config: TickerIngestionRuntimeConfig) -> None:
        """
        Execute full download->process->chunk->index pipeline for one ticker job.
        """

        joined = "_".join(tickers[:3]) if tickers else "UNKNOWN"
        paths = build_job_paths(project_root=self.project_root, jobs_root=self.jobs_root, ticker=joined, job_id=job_id)
        paths.run_root.mkdir(parents=True, exist_ok=True)
        paths.log_path.parent.mkdir(parents=True, exist_ok=True)

        self.update_job(
            job_id,
            status="running",
            stage="download",
            message=f"Downloading filings from EDGAR ({', '.join(tickers)})",
            started_at=now_utc_iso(),
            run_root=str(paths.run_root),
            log_path=str(paths.log_path),
        )

        try:
            commands = [
                (
                    "download",
                    "Downloading filings from EDGAR",
                    build_download_command(
                        tickers=tickers,
                        per_company=per_company,
                        output_dir=paths.download_root,
                        delay=config.download_delay,
                        skip_existing=config.download_skip_existing,
                        ingest_profile=config.ingest_profile,
                    ),
                ),
                (
                    "process",
                    "Converting SEC HTML to markdown",
                    build_process_markdown_command(
                        html_dir=paths.download_root / "raw_htmls",
                        meta_dir=paths.download_root / "meta",
                        output_dir=paths.markdown_root,
                        parser_mode=config.process_parser_mode,
                        recursive=config.process_recursive,
                        continue_on_error=config.process_continue_on_error,
                        ingest_profile=config.ingest_profile,
                    ),
                ),
                (
                    "chunk",
                    "Chunking markdown filings",
                    build_chunk_command(
                        markdown_dir=paths.markdown_root / "processed_markdown",
                        metadata_dir=paths.markdown_root / "debug",
                        output_dir=paths.chunk_output_root,
                        chunker=config.chunker,
                        max_tokens=config.chunk_max_tokens,
                        overlap_tokens=config.chunk_overlap_tokens,
                        recursive=config.chunk_recursive,
                        doc_id_strategy=config.chunk_doc_id_strategy,
                        split_markdown_tables=config.chunk_split_markdown_tables,
                        ingest_profile=config.ingest_profile,
                    ),
                ),
                (
                    "index",
                    "Upserting chunks into PostgreSQL",
                    build_index_command(config=config, ingest_output_dir=paths.chunk_output_root),
                ),
            ]

            for stage, message, command in commands:
                self.update_job(job_id, stage=stage, message=message)
                run_subprocess(command=command, cwd=self.project_root, log_path=paths.log_path)

            doc_index_path = paths.chunk_output_root / "doc_index.jsonl"
            self.update_job(
                job_id,
                status="succeeded",
                stage="done",
                message="Ticker ingestion completed",
                finished_at=now_utc_iso(),
                doc_index_path=str(doc_index_path),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Ticker ingestion job failed (job_id={}): {}", job_id, exc)
            self.update_job(
                job_id,
                status="failed",
                message=f"{type(exc).__name__}: {exc}",
                finished_at=now_utc_iso(),
            )


def now_utc_iso() -> str:
    """
    Return current UTC timestamp in ISO-8601 format.
    """

    return datetime.now(timezone.utc).isoformat()


def timestamp_token() -> str:
    """
    Return filesystem-safe UTC timestamp token.
    """

    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def normalize_ticker(ticker: str) -> str:
    """
    Normalize and validate a stock ticker symbol.
    """

    candidate = str(ticker or "").strip().upper()
    if not candidate:
        raise ValueError("Ticker is required.")
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-")
    if any(ch not in allowed for ch in candidate):
        raise ValueError("Ticker must contain only A-Z, 0-9, '.', or '-'.")
    if len(candidate) > 12:
        raise ValueError("Ticker is too long.")
    return candidate


def build_job_paths(*, project_root: Path, jobs_root: Path, ticker: str, job_id: str) -> TickerIngestionPaths:
    """
    Resolve per-job directories and log file path.
    """

    token = timestamp_token()
    run_root = jobs_root / f"{ticker}_{token}_{job_id[:8]}"
    return TickerIngestionPaths(
        run_root=run_root,
        download_root=run_root / "download",
        markdown_root=run_root / "markdown",
        chunk_output_root=run_root / "chunked",
        log_path=run_root / "pipeline.log",
    )


def build_download_command(
    *,
    tickers: list[str],
    per_company: int,
    output_dir: Path,
    delay: float,
    skip_existing: bool,
    ingest_profile: str,
) -> list[str]:
    """
    Build `scripts.download` command for one or more tickers.
    """

    command = [
        sys.executable,
        "-m",
        "scripts.download",
        "--tickers",
        *tickers,
        "--output-dir",
        str(output_dir),
        "--per-company",
        str(per_company),
        "--delay",
        str(delay),
        "--ingest-profile",
        ingest_profile,
    ]
    if skip_existing:
        command.append("--skip-existing")
    return command


def build_process_markdown_command(
    *,
    html_dir: Path,
    meta_dir: Path,
    output_dir: Path,
    parser_mode: str,
    recursive: bool,
    continue_on_error: bool,
    ingest_profile: str,
) -> list[str]:
    """
    Build `scripts.process_html_to_markdown` command.
    """

    command = [
        sys.executable,
        "-m",
        "scripts.process_html_to_markdown",
        "--html-dir",
        str(html_dir),
        "--meta-dir",
        str(meta_dir),
        "--output-dir",
        str(output_dir),
        "--ingest-profile",
        ingest_profile,
        "--parser-mode",
        parser_mode,
    ]
    if recursive:
        command.append("--recursive")
    if continue_on_error:
        command.append("--continue-on-error")
    return command


def build_chunk_command(
    *,
    markdown_dir: Path,
    metadata_dir: Path,
    output_dir: Path,
    chunker: str,
    max_tokens: int,
    overlap_tokens: int,
    recursive: bool,
    doc_id_strategy: str,
    split_markdown_tables: bool,
    ingest_profile: str,
) -> list[str]:
    """
    Build `scripts.chunk` command for markdown chunk exports.
    """

    command = [
        sys.executable,
        "-m",
        "scripts.chunk",
        "--markdown-dir",
        str(markdown_dir),
        "--metadata-dir",
        str(metadata_dir),
        "--output-dir",
        str(output_dir),
        "--ingest-profile",
        ingest_profile,
        "--chunker",
        chunker,
        "--max-tokens",
        str(max_tokens),
        "--overlap-tokens",
        str(overlap_tokens),
        "--doc-id-strategy",
        doc_id_strategy,
    ]
    if recursive:
        command.append("--recursive")
    if split_markdown_tables:
        command.append("--split-markdown-tables")
    return command


def build_index_command(*, config: TickerIngestionRuntimeConfig, ingest_output_dir: Path) -> list[str]:
    """
    Build `scripts.build_index` command aligned with active runtime settings.
    """

    command = [
        sys.executable,
        "-m",
        "scripts.build_index",
        "--ingest-output-dir",
        str(ingest_output_dir),
        "--ingest-profile",
        config.ingest_profile,
        "--postgres-dsn",
        config.postgres_dsn,
        "--dense-model",
        config.dense_model,
        "--context",
        config.context_strategy,
        "--context-window",
        str(config.context_window),
        "--context-metadata-key",
        config.context_metadata_key,
        "--context-max-tokens",
        str(config.context_max_tokens),
        "--context-max-concurrency",
        str(config.context_max_concurrency),
        "--batch-size",
        str(config.batch_size),
        "--sparse-search-method",
        config.sparse_search_method,
    ]

    if config.postgres_schema:
        command.extend(["--postgres-schema", config.postgres_schema])
    if config.llm_provider:
        command.extend(["--llm-provider", config.llm_provider])
    if config.dense_base_url:
        command.extend(["--dense-base-url", config.dense_base_url])
    if config.contextual_llm_provider:
        command.extend(["--contextual-llm-provider", config.contextual_llm_provider])
    if config.contextual_model:
        command.extend(["--contextual-model", config.contextual_model])
    if config.contextual_base_url:
        command.extend(["--contextual-base-url", config.contextual_base_url])

    return command


def format_command(command: list[str]) -> str:
    """
    Render command list into a shell-like one-line string for logs.
    """

    return " ".join(subprocess.list2cmdline([piece]) for piece in command)


def run_subprocess(*, command: list[str], cwd: Path, log_path: Path) -> None:
    """
    Run subprocess command and append stdout/stderr to job log.
    """

    env = os.environ.copy()
    cmd_str = format_command(command)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n$ {cmd_str}\n")

    result = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    with log_path.open("a", encoding="utf-8") as handle:
        if result.stdout:
            handle.write(result.stdout)
            if not result.stdout.endswith("\n"):
                handle.write("\n")
        if result.stderr:
            handle.write(result.stderr)
            if not result.stderr.endswith("\n"):
                handle.write("\n")
        handle.write(f"[exit_code={result.returncode}]\n")

    if result.returncode == 0:
        return

    tail = ""
    if result.stderr:
        tail = "\n".join(result.stderr.strip().splitlines()[-10:])
    elif result.stdout:
        tail = "\n".join(result.stdout.strip().splitlines()[-10:])
    detail = f"Command failed ({result.returncode}): {cmd_str}"
    if tail:
        detail = f"{detail}\n{tail}"
    raise RuntimeError(detail)
