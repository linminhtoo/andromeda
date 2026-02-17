#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate
pre-commit run --all
pytest src/test/ || true
pytest tests/
