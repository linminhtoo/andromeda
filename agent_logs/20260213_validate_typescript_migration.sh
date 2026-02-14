#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

npm run -s build:ts

bash ./scripts/launch_app.sh >/tmp/finrag_validate_launch_app.log 2>&1 &
APP_PID=$!
for _ in {1..90}; do
  if curl -fsS http://127.0.0.1:8236/health >/tmp/finrag_validate_health_main.json 2>/dev/null; then
    break
  fi
  sleep 1
done
curl -fsS http://127.0.0.1:8236/ >/tmp/finrag_validate_main_root.html
curl -fsS http://127.0.0.1:8236/review >/tmp/finrag_validate_main_review.html
curl -fsS http://127.0.0.1:8236/static/js/index/main.js >/tmp/finrag_validate_main_index_main.js
curl -fsS http://127.0.0.1:8236/static/js/review/main.js >/tmp/finrag_validate_main_review_main.js
kill "$APP_PID"
wait "$APP_PID" || true

bash ./scripts/launch_review.sh >/tmp/finrag_validate_launch_review.log 2>&1 &
REVIEW_PID=$!
for _ in {1..90}; do
  if curl -fsS http://127.0.0.1:8237/health >/tmp/finrag_validate_health_review.json 2>/dev/null; then
    break
  fi
  sleep 1
done
curl -fsS http://127.0.0.1:8237/review >/tmp/finrag_validate_review.html
curl -fsS http://127.0.0.1:8237/static/js/review/main.js >/tmp/finrag_validate_review_main.js
kill "$REVIEW_PID"
wait "$REVIEW_PID" || true

source .venv/bin/activate
pre-commit run --all
pytest tests/
