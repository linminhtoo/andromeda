#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate

npm run -s check:ts
pre-commit run --all
pytest -vvv tests/
python scripts/test_vllm_tool_call_openai.py --max-tokens 96 --tool-choice auto
