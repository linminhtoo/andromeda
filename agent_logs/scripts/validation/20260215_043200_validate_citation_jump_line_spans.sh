#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

npm run -s build:ts
source .venv/bin/activate
pre-commit run --all
pytest -vvv tests/
