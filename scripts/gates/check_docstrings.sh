#!/usr/bin/env bash
# QG-RD-01 docstring coverage on the public API (interrogate, config in pyproject.toml).
# Public functions must state their why and failure mode. The changed src files must reach the fail-under bar together; the whole-tree
# figure is counted in baseline.json. Fails closed: no interrogate or config exits 2.
#   check_docstrings.sh FILE ...        default: changed src/symbiont python files
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

need_py_tool interrogate
grep -q '^\[tool.interrogate\]' "$ROOT/pyproject.toml" || gate_die "no [tool.interrogate] in pyproject.toml"
if [ "$#" -eq 0 ]; then
  require_base
  files=$(changed_matching '^src/symbiont/.*\.py$') || gate_die "cannot list changed files against '$BASE'"
  [ -n "$files" ] || { echo "QG-RD-01: no changed src files"; exit 0; }
  set -- $files
fi
exec uv run --no-sync interrogate "$@"
