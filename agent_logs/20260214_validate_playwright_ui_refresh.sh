#!/usr/bin/env bash
set -euo pipefail

script_dir="$({ cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd; })"
project_root="$({ cd -- "$script_dir/.." >/dev/null 2>&1 && pwd; })"
cd "$project_root"

npm run -s check:ts
npm run -s build:ts
npm run -s test:ui

source .venv/bin/activate
pre-commit run --all
pytest -vvv tests/
