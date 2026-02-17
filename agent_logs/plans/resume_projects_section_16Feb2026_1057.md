# Resume Projects Section Update Plan (16 Feb 2026 10:57)

## Objective
Add a high-impact `Projects` section to `resume_without_bold.tex` based on actual work in this repository, with diverse talking-point options suitable for a Forward Deployed LLM Engineer final round.

## Technical approach
- Review repository artifacts (`README.md`, `CHANGELOG.md`, `src/andromeda/*`, `scripts/*`, `agent_logs/LOGBOOK.md`) to identify defensible project claims.
- Insert a concise `Projects` section in resume style consistent with existing formatting.
- Emphasize end-to-end ownership, production architecture, experimentation workflow, and measurable outcomes.
- Keep alternatives diverse by offering multiple framing options in accompanying notes (architecture-heavy, product/agent-heavy, eval/experimentation-heavy).

## Phases

### Phase 1: Evidence extraction
Acceptance criteria:
- Identify 3-4 concrete project narratives with technical specificity grounded in repo code/docs.
- Collect reusable bullet candidates with no unverifiable claims.

### Phase 2: Resume integration
Acceptance criteria:
- `resume_without_bold.tex` contains a new `Projects` section.
- Wording is concise, interview-friendly, and consistent with existing resume tone.

### Phase 3: Validation and documentation
Acceptance criteria:
- Run `source .venv/bin/activate && pre-commit run --all`.
- Run `source .venv/bin/activate && pytest -vvv tests/`.
- Append a concise entry to `agent_logs/LOGBOOK.md` documenting what changed and why.

## Files
- files_to_change:
  - `resume_without_bold.tex`
  - `agent_logs/LOGBOOK.md`
- new_files:
  - `agent_logs/resume_projects_section_16Feb2026_1057.md`

## Suggested future add-ons (not in current scope)
- Tailor one additional resume variant specifically for Palantir/FDSE-style mission language.
- Add a one-page interview “project stories” sheet with architecture diagrams and tradeoffs.
