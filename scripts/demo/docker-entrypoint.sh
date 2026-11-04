#!/bin/sh
# Container entrypoint: `demo` runs the keyless walkthrough; anything else runs as given, so
# `docker run ai-symbiont uv run pytest -q` and the default `symbiont serve` keep working.
set -eu
if [ "${1:-}" = "demo" ]; then
    exec python scripts/demo/keyless_demo.py
fi
exec "$@"
