#!/usr/bin/env bash
# Tier 3 of REPRODUCE.md. Usage: scripts/reproduce/rerun_learning.sh data [WORKDIR]
#                                scripts/reproduce/rerun_learning.sh prerequisites ITEMS ARTIFACTS
#                                scripts/reproduce/rerun_learning.sh compare DECISION.json
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
uv sync --group dev --quiet
stage=${1:?usage: rerun_learning.sh data|prerequisites|compare ...}
shift
case $stage in
  data) exec uv run --with duckdb python scripts/reproduce/rerun_learning.py data --work "${1:-data/repro/work}" ;;
  prerequisites) exec uv run python scripts/reproduce/rerun_learning.py prerequisites --items "$1" --artifacts "$2" ;;
  compare) exec uv run python scripts/reproduce/rerun_learning.py compare "$1" ;;
  *) echo "unknown stage: $stage" >&2; exit 2 ;;
esac
