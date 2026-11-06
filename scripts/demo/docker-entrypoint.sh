#!/bin/sh
# Container entrypoint: `demo` runs the keyless walkthrough; `live` opens a real Muse Code session
# (needs META_API_KEY); anything else runs as given, so `docker run ai-symbiont uv run pytest -q`
# and the default `symbiont serve` keep working.
set -eu
if [ "${1:-}" = "demo" ]; then
    exec python scripts/demo/keyless_demo.py
fi
if [ "${1:-}" = "live" ]; then
    exec python scripts/demo/live.py
fi
exec "$@"
