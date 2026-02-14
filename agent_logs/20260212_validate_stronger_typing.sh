#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."
source .venv/bin/activate

pre-commit run --all
pytest tests/
