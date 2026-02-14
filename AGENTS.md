# AGENTS.md

Agents operating in this repository **must follow the rules in this file**.
Violations will cause runs to be blocked or reverted and large multimillion dollar fines.

---

## Style Guidelines

* Strictly follow existing style in the codebase.
* Ensure every function is properly documented following the existing style.
* Keep code concise.
* Don't overcomplicate things. Don't implement more than you need to.
* Ensure code is readable by humans, easy to extend and maintain.
* Avoid prefixing functions, variables, classes with `_`. The only exception is when
there is already precedence (existing code) in the specific file in the codebase.
* Adhere to SOLID principles, especially the Single Responsibility Principle.
* Always import directly from the source module. Never re-export.
* After each change, you must run the linter. See instructions under "Lint Instructions".
* Unless absolutely necessary, avoid the use of ugly dict.get(query_key, None) or
getattr(self, query_attr, None). Instead, prefer explicit code that guarantees
key/attribute existence, such as by typing dictionaries and class attributes properly.


## Environment Instructions
* Use `grep`. We do not have `rg`.
* Activate the python venv by running `source .venv/bin/activate` from the repository root.


## Lint Instructions
* After every change, you must run the formatter and linter and ensure everything is passing.
* First, activate the python venv by running `source .venv/bin/activate` from the repository root.
* Then, run `pre-commit run --all`.
* We use the pyright pre-commit hook to catch typing issues. There may be a large number of such errors. Try your best to fix them where possible, and document your findings in the `agent_logs/LOGBOOK.md`. If fixing a particular error is too tedious, make a judgement as to whether you should just ignore it in-line, or modify the pyright config (if applicable).


## Planning rules

* Phases must be scoped and independently testable
* Each phase should have clear acceptance criteria
* Planning output must not modify repository code
* Must list files to change (`files_to_change`, `new_files`)
* Must describe a coherent technical approach
* Must not assume unstated infrastructure or permissions
* Must be concise where possible
* List potential add-ons/future work but make it clear that they are suggestions and not to be done in the current scope.
* Document your plan properly (see the "Implementation rules" section below)

## Implementation rules

* Before starting a big task, you should plan and document your plan as a markdown file in the `agent_logs/` folder. Give your plan file a descriptive and time-stamped name, such as `refactor_10Feb2026.md`
* Make sure to reference `agent_logs/LOGBOOK.md` to learn from previous lessons and avoid repeating past mistakes.
* Implement the **entire phase**, not partial work
* Update `CHANGELOG.md` when behavior changes
* Agents must not commit or push. Only the coordinator may commit/push after review passes.
* Never modify repository files outside this `lrdml` git repository.
* You must write down key learning points and observations in a `agent_logs/LOGBOOK.md` at this repository's root level:
    - IMPORTANT: When you implement a new feature or make a breaking change, you need to 
        highlight this in the `LOGBOOK.md`. State the previous state, what was changed, and why.
        This is needed to provide a clean lineage of design decisions taken during the course of development and iteration.
    - Note down any surprising facts you discovered about the codebase or its dependencies
    - Log all experiments conducted and results/metrics observed
    - Make it easy for someone else to pick up on your work
    - Keep your notes concise, but don't sacrifice important info.
    - If a `LOGBOOK.md` file already exists, append your observations as a new entry. Never delete existing entries.
    - IMPORTANT: you must preserve scripts you executed under the `agent_logs/` folder. Name each script appropriately,
        including a timestamp and its intent (eg `run_improved_mlp_model_$now.sh`)
* IMPORTANT CAVEAT:
    - Other agents/humans may be working on the codebase at the same time
    - Recognize that code changes not related to your scope of work may be done by them, including modifications to this `LOGBOOK.md` file.
    - NEVER undo others' work.

## Testing rules

* First, activate the venv by running `source .venv/bin/activate` from the repository root.
* Then, run tests with `pytest src/test/`.
* Fix failing tests before proceeding.
* Never bypass tests without explicit instruction.
