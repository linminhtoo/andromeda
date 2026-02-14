# PostgreSQL Schema Namespacing for Experiment Isolation (2026-02-13)

## Goal
Enable `build_index.sh` / `build_index.py` to isolate index builds by PostgreSQL schema, so one Postgres instance can host multiple experimental corpora (different context/HNSW settings) safely.

## Scope
- Add a schema selector to indexing CLI and shell wrapper.
- Ensure DB connections create/use the selected schema automatically.
- Keep backward compatibility when schema is omitted (current behavior).
- Document new operational workflow.

## files_to_change
- `src/finrag/db.py`
- `src/finrag/retriever.py`
- `scripts/build_index.py`
- `scripts/build_index.sh`
- `.env.example`
- `README.md`
- `CHANGELOG.md`
- `experiments/LOGBOOK.md`

## new_files
- `experiments/20260213_validate_postgres_schema_namespacing.sh`

## Technical approach
1. Add optional `postgres_schema` plumbing:
   - `build_index.py` flag `--postgres-schema` (fallback from env `POSTGRES_SCHEMA`).
   - Pass through `PostgresHybridRetriever` to `PostgresDB`.
2. In `PostgresDB.connect()`:
   - open connection
   - `CREATE SCHEMA IF NOT EXISTS <schema>` when schema configured
   - `SET search_path TO <schema>, public`
   - return configured connection
3. Update `build_index.sh`:
   - accept `POSTGRES_SCHEMA` env and pass to `build_index.py` when set.
4. Update docs and changelog:
   - usage examples and env knobs.

## Phases

### Phase 1: DB + retriever plumbing
Acceptance criteria:
- `PostgresDB` supports optional schema and sets search path.
- `PostgresHybridRetriever` forwards schema to `PostgresDB`.

### Phase 2: CLI + shell ergonomics
Acceptance criteria:
- `build_index.py --help` shows schema flag.
- `build_index.sh` supports `POSTGRES_SCHEMA` passthrough.

### Phase 3: Validation + docs
Acceptance criteria:
- `pre-commit run --all` passes.
- `pytest tests/` passes.
- smoke runs for distinct schemas succeed.
- README/CHANGELOG describe workflow clearly.

## Risks / notes
- Existing DSNs with custom `search_path` options may conflict with explicit runtime `SET search_path`; explicit script-provided schema will be authoritative in-session.
- Schema names are treated as SQL identifiers (quoted safely).

## Future work (not in this scope)
- Add runtime app/eval schema switch flags to make serving and index-building share identical experiment selection.
- Add optional auto-generated schema names from run parameters.
