#!/usr/bin/env bash
# Run on any computer for a quick look:  ./run.sh   then open http://localhost:8080
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/uvicorn ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
export SIGNAGE_PORT="${SIGNAGE_PORT:-8080}"
exec .venv/bin/uvicorn --factory server.app:create_app --host 0.0.0.0 --port "$SIGNAGE_PORT"
