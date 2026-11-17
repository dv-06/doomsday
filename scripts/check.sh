#!/usr/bin/env bash
# Full local check: backend tests + config validation + frontend typecheck/build.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python}"
if [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe; fi
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; fi

echo "== pytest =="
PYTHONPATH=backend "$PY" -m pytest backend/tests -q

echo "== validate config + snapshot =="
PYTHONPATH=backend "$PY" -m doomsday_watch --config config/monitor.json --data data validate

echo "== frontend typecheck + build =="
cd frontend
npm run typecheck
npm run build
echo "All checks passed."
