#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate
pre-commit run --all
npx pyright
