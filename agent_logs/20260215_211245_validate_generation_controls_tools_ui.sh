#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

npm run -s build:ts

source .venv/bin/activate
PRE_COMMIT_HOME=/tmp/pre-commit-cache pre-commit run --all
pytest -vvv tests/
