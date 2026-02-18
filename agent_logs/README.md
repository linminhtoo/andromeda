# agent_logs Organization

`agent_logs/` now uses a fully nested layout.

Only two files remain at top-level:
- `agent_logs/LOGBOOK.md`
- `agent_logs/README.md`

## Folder conventions (for new work)

- `agent_logs/plans/`: implementation plans before large changes.
- `agent_logs/scripts/`: reproducibility scripts executed for experiments.
  - `agent_logs/scripts/eval/`: eval generation/scoring/benchmark scripts.
  - `agent_logs/scripts/validation/`: validation and smoke-test scripts.
  - `agent_logs/scripts/misc/`: non-eval utility scripts.
- `agent_logs/audits/`: manual labeling files, audit CSVs, and review packs.
- `agent_logs/reports/`: metric summaries, dashboards, and comparison outputs.
- `agent_logs/artifacts/`: large generated helper artifacts not suited for top-level docs.
- `agent_logs/references/`: external reading notes and distilled takeaways.

## Naming convention

- Use timestamp prefixes and intent suffixes:
  - scripts: `YYYYMMDD_HHMMSS_<intent>.sh|py`
  - notes: `topic_DDMonYYYY.md` or `topic_YYYYMMDD.md`
  - reports: `metric_family_scope_YYYYMMDD.json|csv|md`
