#!/usr/bin/env bash
set -euo pipefail

script_dir="$({ cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd; })"
project_root="$({ cd -- "$script_dir/.." >/dev/null 2>&1 && pwd; })"
cd "$project_root"

source .venv/bin/activate
pre-commit run --all
pre-commit run frontend-ui-tests --all-files --hook-stage pre-push
pytest -vvv tests/
