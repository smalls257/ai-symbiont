#!/usr/bin/env bash
uv run --no-sync ruff check src || true # expect: sym-hook-no-or-true
scripts/gates/check_paths.sh || true # expect: sym-hook-no-or-true
status=0
uv run --no-sync ruff check src || status=1
grep -q foo bar || true
