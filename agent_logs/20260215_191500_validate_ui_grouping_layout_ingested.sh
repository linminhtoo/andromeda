#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate
npm run -s build:ts
PRE_COMMIT_HOME=/tmp/pre-commit-cache VIRTUALENV_OVERRIDE_APP_DATA=/tmp/virtualenv-app-data pre-commit run --all
pytest -vvv tests/
