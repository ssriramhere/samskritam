#!/usr/bin/env bash
# Kept for convenience; bench/run_all.py does the work on every platform.
cd "$(dirname "$0")/.."
PY=$(command -v python3 >/dev/null 2>&1 && python3 -c "" 2>/dev/null && echo python3 || echo python)
exec "$PY" bench/run_all.py "$@"
