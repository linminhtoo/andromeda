# vLLM Tool Calling Probe Plan (15 Feb 2026 00:46:17)

## Objective
Create a standalone script to verify whether the currently configured vLLM chat model can perform OpenAI-style tool/function calling.

## Phase 1: Add standalone probe script
Acceptance criteria:
- Script runs independently from `src/finrag` runtime code.
- Uses OpenAI-compatible client initialization pattern used in the repo (`api_key` + `base_url`).
- Sends a chat request with `tools`, executes local tool implementation, and sends tool result back.
- Prints clear PASS/FAIL-oriented output.

files_to_change:
- `scripts/test_vllm_tool_call_openai.py`

new_files:
- `scripts/test_vllm_tool_call_openai.py`

## Phase 2: Repo documentation/log updates
Acceptance criteria:
- Update `agent_logs/LOGBOOK.md` with previous state, changes, why, and validation outcomes.
- Update `CHANGELOG.md` under `Unreleased` if needed for newly added script.
- Preserve validation command script under `agent_logs/`.

files_to_change:
- `agent_logs/LOGBOOK.md`
- `CHANGELOG.md`
- `agent_logs/20260215_validate_vllm_tool_probe.sh`

new_files:
- `agent_logs/20260215_validate_vllm_tool_probe.sh`

## Phase 3: Validation
Acceptance criteria:
- Run formatter/linter via `source .venv/bin/activate && pre-commit run --all`.
- Run tests via `source .venv/bin/activate && pytest -vvv tests/`.
- Record results in `agent_logs/LOGBOOK.md`.

## Technical approach
- Use `dotenv` to load `.env` from repo root.
- Resolve endpoint from CLI arg first, then `OPENAI_CHAT_BASE_URL`, then `OPENAI_BASE_URL`.
- Resolve model from CLI arg first, then `OPENAI_CHAT_MODEL`.
- Use `chat.completions.create(..., tools=[...], tool_choice=...)`.
- Implement one local test function (`lookup_quote`) and dispatch by function name.
- Append assistant tool calls + tool results to messages and request final assistant answer.

## Suggestions for future work (not in this scope)
- Add a second probe mode for multimodal tool-calling input.
- Add optional streaming mode and parser diagnostics for malformed tool arguments.
