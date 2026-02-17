# Doc Refresh + Structure Cleanup Plan (18 Feb 2026, 03:05)

## Scope
- Refresh `README_EVAL.md` to reflect current best settings, answering hyperparameters, and current metric interpretation.
- Provide one-command style orchestration for full eval suite runs (generation + scoring across all metric families).
- Refresh `README.md` with a coherent technical narrative of backend/runtime/eval evolution.
- Reorganize `agent_logs/` into a nested hierarchy without breaking existing reproducibility references.
- Improve `src/` package organization with minimal behavior change and clear grouping.

## Constraints
- Preserve reproducibility and historical traceability in `agent_logs/LOGBOOK.md`.
- Do not break existing scripts/tests that rely on canonical module paths.
- Keep implementation pragmatic; avoid a broad rewrite.

## Phase 1: Baseline Audit + Canonical Settings Extraction
- Read latest eval documentation, run scripts, and score summaries to identify canonical "best known" setup.
- Confirm currently preferred judge/runtime settings:
  - generation preset + answering hyperparameters
  - concurrency/timeout/retry
  - judge context/timeout/retry/workers
- Acceptance criteria:
  - We can point to concrete run directories and metric files for each claim.

files_to_change:
- `README_EVAL.md`
- `README.md`
- `agent_logs/LOGBOOK.md` (append summary entry)

new_files:
- none

## Phase 2: Full Eval Suite Single-Pass Harness
- Add one reproducible orchestration script that runs generation + scoring for:
  - single-ticker suite (factual/open/refusal/distractor)
  - multi-ticker comparison suite
  - optional open-ended stress set
- Script must capture run paths and include judge settings aligned with latest guidance.
- Acceptance criteria:
  - One script invocation produces all run dirs and summaries needed for "full suite" review.
  - Script is documented in `README_EVAL.md`.

files_to_change:
- `agent_logs/` (new timestamped run script)
- `README_EVAL.md`

new_files:
- `agent_logs/<timestamp>_run_full_eval_suite_single_pass.sh`

## Phase 3: agent_logs Reorganization (Non-Breaking)
- Create nested folders (e.g., `plans/`, `scripts/`, `audits/`, `reports/`, `artifacts/`, `references/`).
- Keep existing top-level files untouched to avoid breaking explicit references in `LOGBOOK.md`.
- Add index docs and path conventions so new artifacts are stored in nested folders.
- Acceptance criteria:
  - `agent_logs/` becomes navigable.
  - Historical file paths remain valid.

files_to_change:
- `agent_logs/README.md` (new)
- `agent_logs/LOGBOOK.md` (append notes)

new_files:
- `agent_logs/README.md`
- `agent_logs/plans/.gitkeep`
- `agent_logs/scripts/.gitkeep`
- `agent_logs/audits/.gitkeep`
- `agent_logs/reports/.gitkeep`
- `agent_logs/artifacts/.gitkeep`
- `agent_logs/references/.gitkeep`

## Phase 4: src Layout Improvement (Low-Risk Grouping)
- Introduce clearer package grouping by moving selected modules into subpackages while preserving compatibility.
- Preferred minimal move set:
  - query pipeline modules into `src/andromeda/query/`
  - keep thin compatibility imports only where required for existing entrypoints/tests.
- Update imports and tests accordingly.
- Acceptance criteria:
  - `pytest -vvv tests/` passes.
  - Import paths are consistent and readable.

files_to_change:
- `src/andromeda/query_runtime.py`
- `src/andromeda/query_streaming.py`
- `src/andromeda/query_conversation.py`
- `src/andromeda/runtime_builders.py`
- `src/andromeda/main.py`
- any direct import callsites in `src/`, `scripts/`, `tests/`

new_files:
- `src/andromeda/query/__init__.py`
- `src/andromeda/query/runtime.py`
- `src/andromeda/query/streaming.py`
- `src/andromeda/query/conversation.py`

## Phase 5: Validation + Final Documentation Updates
- Run formatting/linting/tests at end only.
- Append concise summary to `agent_logs/LOGBOOK.md` including outcomes and any tradeoffs.
- Acceptance criteria:
  - `pre-commit run --all` passes.
  - `pytest -vvv tests/` passes.
  - README docs are internally consistent and reproducible.

## Future work (not in current scope)
- Add automated drift checks that validate README command snippets against scripts in CI.
- Add periodic dashboard snapshots for "metric frontier" trend visualization in a stable report directory.
