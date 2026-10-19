#!/usr/bin/env bash
# Run every model in bench/models.txt through OpenRouter, then grade and
# write web/data/leaderboard.json for the site.
#   export OPENROUTER_API_KEY=...
#   bash bench/run_all.sh
set -euo pipefail
cd "$(dirname "$0")/.."
: "${OPENROUTER_API_KEY:?Set OPENROUTER_API_KEY first}"
grep -v -E '^\s*(#|$)' bench/models.txt | while read -r model; do
  echo "== $model"
  python3 bench/run.py --provider openrouter --model "$model" --workers "${WORKERS:-8}" || true
done
python3 bench/leaderboard.py
