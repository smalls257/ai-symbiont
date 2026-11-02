#!/usr/bin/env bash
# Tier 1 of REPRODUCE.md. Needs only uv; no GPU, no API key, no network after `uv sync`.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
uv sync --group dev --quiet
exec uv run python scripts/reproduce/see_it_work.py
