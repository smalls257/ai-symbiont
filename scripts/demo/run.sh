#!/bin/sh
# The keyless demo on this machine: no API key, no network beyond loopback.
set -eu
cd "$(dirname "$0")/../.."
exec uv run python scripts/demo/keyless_demo.py
