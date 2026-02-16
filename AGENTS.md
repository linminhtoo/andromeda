# AGENTS.md

Agents operating in this repository **must follow the rules in this file**.
Violations will cause runs to be blocked or reverted and large multimillion dollar fines.

---

## Style Guidelines

* Strictly follow existing style in the codebase.
* Ensure every function is properly documented following the existing style.
* Write in-line comments strategically, especially for key business logic. Do this sparingly, and strategically.
* Keep code concise, tasteful and elegant.
* Don't overcomplicate things. Don't implement more than you need to.
* Ensure code is readable by humans, easy to extend and maintain.
* Avoid prefixing functions, variables, classes with `_`. The only exception is when
there is already precedence (existing code) in the specific file in the codebase.
* Adhere to SOLID principles, especially the Single Responsibility Principle.
* Always import directly from the source module. Never re-export.
* Unless absolutely necessary, avoid the use of ugly `dict.get(query_key, None)` or
`getattr(self, query_attr, None)`. Instead, prefer explicit code that guarantees
key/attribute existence, such as by using `dataclass`, `TypedDict` and class attributes which are properly typed.
* Favor `Enum` over `Literal`.


## Environment Instructions
* Use `grep`. We do not have `rg`.
* Activate the python venv by running `source .venv/bin/activate` from the repository root.


## Lint Instructions
* At the very end when wrapping up complete your implementation, you must run the formatter and linter and ensure everything is passing.
    * Do not run the linter after every change. It is too slow.
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

* Before starting a big task, you should plan and document your plan as a markdown file in the `agent_logs/` folder.
Give your plan file a descriptive and time-stamped name, such as `refactor_10Feb2026.md`
* Make sure to reference `agent_logs/LOGBOOK.md` to learn from previous lessons and avoid repeating past mistakes.
* Implement the **entire phase**, not partial work
* During refactors/migrations, when removing existing comments especially TODO, which is not relevant to the current task,
you must ensure those comments continue to exist in the new/migrated function/code.
* Update `CHANGELOG.md` when behavior changes
* Agents must not commit or push. Only the coordinator may commit/push after review passes.
* Never modify repository files outside this git repository.
* You must write down key learning points and observations in a `agent_logs/LOGBOOK.md` at this repository's root level:
    - IMPORTANT: When you implement a new feature or make a breaking change, you need to
        highlight this in the `LOGBOOK.md`. State the previous state, what was changed, and why.
        This is needed to provide a clean lineage of design decisions taken during the course of development and iteration.
    - Note down any surprising facts you discovered about the codebase or its dependencies
    - Log all experiments conducted and results/metrics observed
    - Make it easy for someone else to pick up on your work
    - Keep your notes concise, but don't sacrifice important info.
    - If a `LOGBOOK.md` file already exists, append your observations as a new entry. Never delete existing entries.
    - IMPORTANT: you must preserve scripts you executed (EXCEPT pre-commit/pytest) under the `agent_logs/` folder.
        Name each script appropriately,
        including a timestamp and its intent (eg `run_improved_mlp_model_$now.sh`)
    - HOWEVER, do NOT bother with saving a script if it is just executing `pre-commit` and `pytest`.
        This is not noteworthy enough to be saved a script. Scripts are reserved for special scripts
        you created and ran, such as benchmarking, special testing, and so on.
* IMPORTANT CAVEAT:
    - Other agents/humans may be working on the codebase at the same time
    - Recognize that code changes not related to your scope of work may be done by them,
    including modifications to `LOGBOOK.md`, `agent_logs/`, `CHANGELOG.md` and so on.
    - NEVER undo others' work.
    - Keep calm and continue executing with your plan. You do not need to stop and ask me about it.

## Testing rules

* You must run the tests after wrapping up all changes, or before running an actual piece of work
which relies on recent changes to the codebase, to ensure that core functions work as expected.
    - You don't need to run the tests after every little change. Exercise judgement.
* First, activate the venv by running `source .venv/bin/activate` from the repository root.
* Then, run tests with `pytest -vvv tests/`.
* Fix failing tests before proceeding.
* Never bypass tests without explicit instruction.
