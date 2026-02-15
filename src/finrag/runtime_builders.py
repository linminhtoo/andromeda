import os
import sys
import time
from pathlib import Path

from loguru import logger

from finrag.context_support import context_builder_from_metadata
from finrag.db import SparseSearchMethod
from finrag.ingest_profile import (
    ingest_profile_step_settings,
    load_ingest_profile,
    postgres_schema_for_ingest_profile,
    resolve_ingest_profile_name,
)
from finrag.ingestion_jobs import TickerIngestionRuntimeConfig
from finrag.llm_clients import LLMClient, get_llm_client
from finrag.retriever import CrossEncoderReranker, PostgresHybridRetriever


def setup_logging(*, project_root: Path) -> Path:
    """
    Configure app logging and return the current log file path.
    """

    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"main_app_{ts}.log"

    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add(str(log_path), level="DEBUG")
    return log_path


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def llm_provider_name() -> str:
    return (os.getenv("LLM_PROVIDER") or "openai").strip().lower()


def llm_chat_model() -> str | None:
    provider = llm_provider_name()
    if provider == "openai":
        return (os.getenv("OPENAI_CHAT_MODEL") or os.getenv("CHAT_MODEL") or "").strip() or None
    if provider == "mistral":
        return (os.getenv("MISTRAL_CHAT_MODEL") or os.getenv("CHAT_MODEL") or "").strip() or None
    return (os.getenv("CHAT_MODEL") or "").strip() or None


def llm_embed_model() -> str | None:
    provider = llm_provider_name()
    if provider == "openai":
        return (os.getenv("OPENAI_EMBED_MODEL") or os.getenv("EMBED_MODEL") or "").strip() or None
    if provider == "mistral":
        return (os.getenv("MISTRAL_EMBED_MODEL") or os.getenv("EMBED_MODEL") or "").strip() or None
    return (os.getenv("EMBED_MODEL") or "").strip() or None


def llm_for_embeddings() -> LLMClient:
    provider = os.getenv("LLM_PROVIDER")
    if llm_provider_name() == "openai":
        return get_llm_client(
            provider=provider,
            base_url=(os.getenv("OPENAI_EMBED_BASE_URL") or None),
            embed_model=llm_embed_model() or "text-embedding-3-large",
        )
    embed_model = llm_embed_model()
    return (
        get_llm_client(provider=provider, embed_model=embed_model) if embed_model else get_llm_client(provider=provider)
    )


def llm_for_chat() -> LLMClient:
    provider = os.getenv("LLM_PROVIDER")
    langsmith_trace = env_bool("LANGSMITH_TRACING", default=False)

    if llm_provider_name() == "openai":
        return get_llm_client(
            provider=provider,
            base_url=(os.getenv("OPENAI_CHAT_BASE_URL") or None),
            chat_model=llm_chat_model() or "gpt-4o-mini",
            langsmith_trace=langsmith_trace,
        )

    if langsmith_trace:
        logger.warning("LANGSMITH_TRACING is only supported for OpenAI provider at this time.")
    chat_model = llm_chat_model()
    return get_llm_client(provider=provider, chat_model=chat_model) if chat_model else get_llm_client(provider=provider)


def context_config() -> tuple[str, int, str]:
    strategy = os.getenv("CONTEXT_STRATEGY", "none").strip().lower()
    window_raw = os.getenv("CONTEXT_WINDOW", "1")
    try:
        window = int(window_raw)
    except ValueError as exc:
        raise RuntimeError("CONTEXT_WINDOW must be an integer") from exc
    metadata_key = os.getenv("CONTEXT_METADATA_KEY", "retrieval_context").strip() or "retrieval_context"
    return strategy, window, metadata_key


def sparse_search_method() -> SparseSearchMethod:
    """
    Resolve sparse retrieval method from environment.
    """

    raw_value = (os.getenv("POSTGRES_SPARSE_SEARCH_METHOD") or os.getenv("SPARSE_SEARCH_METHOD") or "bm25").strip()
    normalized = raw_value.lower()
    if normalized == "bm25":
        return "bm25"
    if normalized == "fts":
        return "fts"
    raise RuntimeError("POSTGRES_SPARSE_SEARCH_METHOD must be one of: bm25, fts")


def postgres_dsn() -> str:
    """
    Resolve PostgreSQL connection string from environment.
    """

    dsn = (os.getenv("POSTGRES_DSN") or os.getenv("DATABASE_URL") or "").strip()
    if not dsn:
        raise RuntimeError("Missing POSTGRES_DSN (or DATABASE_URL).")
    return dsn


def env_positive_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be > 0")
    return value


def coerce_positive_int(value: object, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        parsed = int(value)
    else:
        text = str(value).strip()
        if not text:
            return default
        try:
            parsed = int(text)
        except ValueError:
            return default
    if parsed <= 0:
        return default
    return parsed


def coerce_non_negative_float(value: object, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, float):
        parsed = value
    elif isinstance(value, int):
        parsed = float(value)
    else:
        text = str(value).strip()
        if not text:
            return default
        try:
            parsed = float(text)
        except ValueError:
            return default
    if parsed < 0.0:
        return default
    return parsed


def coerce_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def coerce_text(value: object, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    return text


def coerce_optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def coerce_sparse_search_method(value: object, default: SparseSearchMethod) -> SparseSearchMethod:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text == "bm25":
        return "bm25"
    if text == "fts":
        return "fts"
    return default


def build_ticker_ingestion_config(*, project_root: Path) -> TickerIngestionRuntimeConfig:
    """
    Build ingestion settings from persisted profile with env fallback.
    """

    strategy_default, window_default, context_key_default = context_config()
    profile_name = resolve_ingest_profile_name((os.getenv("FINRAG_INGEST_PROFILE") or "").strip() or None)
    profile = load_ingest_profile(project_root=project_root, profile_name=profile_name)
    download_settings = ingest_profile_step_settings(profile, "download")
    process_settings = ingest_profile_step_settings(profile, "process_html_to_markdown")
    chunk_settings = ingest_profile_step_settings(profile, "chunk")
    build_settings = ingest_profile_step_settings(profile, "build_index")

    if profile:
        logger.info("Loaded ingest profile `{}` for on-the-fly ingestion.", profile_name)
    else:
        logger.warning("Ingest profile `{}` not found; falling back to environment defaults.", profile_name)

    provider = coerce_optional_text(build_settings["llm_provider"] if "llm_provider" in build_settings else None)
    if provider is None:
        provider = (os.getenv("LLM_PROVIDER") or "").strip() or None
    provider_name = (provider or llm_provider_name() or "openai").strip().lower()

    dense_model = coerce_text(
        build_settings["dense_model"] if "dense_model" in build_settings else None,
        llm_embed_model() or "text-embedding-3-large",
    )
    dense_base_url = coerce_optional_text(build_settings["dense_base_url"] if "dense_base_url" in build_settings else None)
    if dense_base_url is None:
        dense_base_url = (os.getenv("OPENAI_EMBED_BASE_URL") or "").strip() or None

    contextual_model = coerce_optional_text(
        build_settings["contextual_model"] if "contextual_model" in build_settings else None
    )
    if contextual_model is None:
        contextual_model = llm_chat_model()

    contextual_provider = coerce_optional_text(
        build_settings["contextual_llm_provider"] if "contextual_llm_provider" in build_settings else None
    )
    if contextual_provider is None:
        contextual_provider = provider

    context_base_url = coerce_optional_text(
        build_settings["contextual_base_url"] if "contextual_base_url" in build_settings else None
    )
    if context_base_url is None:
        context_base_url = (os.getenv("OPENAI_CONTEXT_BASE_URL") or os.getenv("OPENAI_CHAT_BASE_URL") or "").strip() or None

    postgres_schema = coerce_optional_text(build_settings["postgres_schema"] if "postgres_schema" in build_settings else None)
    if postgres_schema is None:
        postgres_schema = (os.getenv("POSTGRES_SCHEMA") or "").strip() or None
    if postgres_schema is None:
        postgres_schema = postgres_schema_for_ingest_profile(profile_name)

    sparse_default = sparse_search_method()
    sparse_method = coerce_sparse_search_method(
        build_settings["sparse_search_method"] if "sparse_search_method" in build_settings else None, sparse_default
    )

    context_strategy = coerce_text(build_settings["context"] if "context" in build_settings else None, strategy_default)
    context_window = coerce_positive_int(
        build_settings["context_window"] if "context_window" in build_settings else None, window_default
    )
    context_metadata_key = coerce_text(
        build_settings["context_metadata_key"] if "context_metadata_key" in build_settings else None,
        context_key_default,
    )
    context_max_tokens = coerce_positive_int(
        build_settings["context_max_tokens"] if "context_max_tokens" in build_settings else None,
        env_positive_int("CONTEXT_MAX_TOKENS", 256),
    )
    context_max_concurrency = coerce_positive_int(
        build_settings["context_max_concurrency"] if "context_max_concurrency" in build_settings else None,
        env_positive_int("CONTEXT_MAX_CONCURRENCY", 64),
    )
    batch_size = coerce_positive_int(
        build_settings["batch_size"] if "batch_size" in build_settings else None,
        env_positive_int("FINRAG_INGEST_BATCH_SIZE", 256),
    )

    download_delay = coerce_non_negative_float(
        download_settings["delay"] if "delay" in download_settings else None,
        coerce_non_negative_float(os.getenv("FINRAG_INGEST_DOWNLOAD_DELAY"), 0.2),
    )
    download_skip_existing = coerce_bool(
        download_settings["skip_existing"] if "skip_existing" in download_settings else None,
        env_bool("FINRAG_INGEST_DOWNLOAD_SKIP_EXISTING", default=True),
    )

    process_parser_mode = coerce_text(
        process_settings["parser_mode"] if "parser_mode" in process_settings else None,
        (os.getenv("FINRAG_PROCESS_PARSER_MODE") or "auto").strip() or "auto",
    )
    process_recursive = coerce_bool(
        process_settings["recursive"] if "recursive" in process_settings else None,
        env_bool("FINRAG_PROCESS_RECURSIVE", default=True),
    )
    process_continue_on_error = coerce_bool(
        process_settings["continue_on_error"] if "continue_on_error" in process_settings else None,
        env_bool("FINRAG_PROCESS_CONTINUE_ON_ERROR", default=True),
    )

    chunker = coerce_text(
        chunk_settings["chunker"] if "chunker" in chunk_settings else None,
        (os.getenv("CHUNKER_NAME") or "markdown_table_preserving").strip() or "markdown_table_preserving",
    )
    chunk_max_tokens = coerce_positive_int(
        chunk_settings["max_tokens"] if "max_tokens" in chunk_settings else None,
        env_positive_int("CHUNK_MAX_TOKENS", 1024),
    )
    chunk_overlap_tokens = coerce_positive_int(
        chunk_settings["overlap_tokens"] if "overlap_tokens" in chunk_settings else None,
        env_positive_int("CHUNK_OVERLAP_TOKENS", 128),
    )
    chunk_recursive = coerce_bool(
        chunk_settings["recursive"] if "recursive" in chunk_settings else None,
        env_bool("FINRAG_CHUNK_RECURSIVE", default=True),
    )
    chunk_doc_id_strategy = coerce_text(
        chunk_settings["doc_id_strategy"] if "doc_id_strategy" in chunk_settings else None,
        (os.getenv("FINRAG_CHUNK_DOC_ID_STRATEGY") or "sha1_relpath").strip() or "sha1_relpath",
    )
    chunk_split_markdown_tables = coerce_bool(
        chunk_settings["split_markdown_tables"] if "split_markdown_tables" in chunk_settings else None,
        env_bool("FINRAG_CHUNK_SPLIT_MARKDOWN_TABLES", default=False),
    )

    return TickerIngestionRuntimeConfig(
        postgres_dsn=postgres_dsn(),
        postgres_schema=postgres_schema,
        sparse_search_method=sparse_method,
        llm_provider=provider,
        dense_model=dense_model,
        dense_base_url=(dense_base_url if provider_name == "openai" else None),
        contextual_llm_provider=contextual_provider,
        contextual_model=contextual_model,
        contextual_base_url=(context_base_url if provider_name == "openai" else None),
        context_strategy=context_strategy,
        context_window=context_window,
        context_metadata_key=context_metadata_key,
        context_max_tokens=context_max_tokens,
        context_max_concurrency=context_max_concurrency,
        batch_size=batch_size,
        ingest_profile=profile_name,
        download_delay=download_delay,
        download_skip_existing=download_skip_existing,
        process_parser_mode=process_parser_mode,
        process_recursive=process_recursive,
        process_continue_on_error=process_continue_on_error,
        chunker=chunker,
        chunk_max_tokens=chunk_max_tokens,
        chunk_overlap_tokens=chunk_overlap_tokens,
        chunk_recursive=chunk_recursive,
        chunk_doc_id_strategy=chunk_doc_id_strategy,
        chunk_split_markdown_tables=chunk_split_markdown_tables,
    )


def build_retriever() -> PostgresHybridRetriever:
    """
    Build PostgreSQL retriever from environment configuration.
    """

    _, _, context_key = context_config()
    postgres_schema = (os.getenv("POSTGRES_SCHEMA") or "").strip() or None
    if postgres_schema is None:
        ingest_profile = resolve_ingest_profile_name((os.getenv("FINRAG_INGEST_PROFILE") or "").strip() or None)
        postgres_schema = postgres_schema_for_ingest_profile(ingest_profile)
    method = sparse_search_method()
    retriever = PostgresHybridRetriever(
        llm_client=llm_for_embeddings(),
        dsn=postgres_dsn(),
        context_builder=context_builder_from_metadata(key=context_key),
        retrieval_context_key=context_key,
        postgres_schema=postgres_schema,
        sparse_search_method=method,
    )
    if postgres_schema:
        logger.info("Using PostgreSQL retriever (schema={}, sparse_search_method={})", postgres_schema, method)
    else:
        logger.info("Using PostgreSQL retriever (sparse_search_method={})", method)
    return retriever


def build_reranker() -> CrossEncoderReranker:
    reranker_model = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2").strip()
    logger.info("Using reranker model: {}", reranker_model)
    return CrossEncoderReranker(model_name=reranker_model)
