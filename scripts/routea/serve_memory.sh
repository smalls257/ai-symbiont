#!/usr/bin/env bash
# Serve Route A's memory model: mlx_lm.server on loopback with the trained adapter.
#
# No adapter or base-model marker stops here, so the service never talks to a base model
# that learned nothing; the server logs to MEMORY_DIR/logs/server.log. The host is fixed to
# 127.0.0.1: egress refuses any other host, and the server sees private session steps.
#
#   scripts/routea/serve_memory.sh MEMORY_DIR [PORT]     # PORT defaults to 8090
# The base model comes from MEMORY_DIR/adapter.json (written by train_memory.py); switching from the
# stand-in to Llama is a different --model at training time, not a code change.
# LCAP_VENV overrides the MLX venv (default ~/symbiont-runs/lcap/venv).
set -euo pipefail

MEMORY=${1:?usage: serve_memory.sh MEMORY_DIR [PORT]}
PORT=${2:-8090}
VENV=${LCAP_VENV:-$HOME/symbiont-runs/lcap/venv}
[[ -f "$MEMORY/adapter/adapters.safetensors" ]] || { echo "no adapter in $MEMORY/adapter" >&2; exit 1; }
[[ -f "$MEMORY/adapter.json" ]] || { echo "no adapter.json in $MEMORY" >&2; exit 1; }
MODEL=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["model"])' "$MEMORY/adapter.json")
mkdir -p "$MEMORY/logs"
exec "$VENV/bin/python" -m mlx_lm server --model "$MODEL" --adapter-path "$MEMORY/adapter" \
  --host 127.0.0.1 --port "$PORT" --temp 0.0 --max-tokens 160 >>"$MEMORY/logs/server.log" 2>&1
