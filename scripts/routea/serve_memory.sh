#!/usr/bin/env bash
# Serve Route A's memory model: mlx_lm.server on loopback with the trained adapter.
#
# Violation prevented: Silent Fallback (no adapter or no base-model marker stops here, so the
# service never talks to a base model that learned nothing) and Black Box (the server logs to
# MEMORY_DIR/logs/server.log). The host is fixed to 127.0.0.1: the egress policy refuses any
# other host for the memory model, and the server sees private session steps.
#
#   scripts/routea/serve_memory.sh MEMORY_DIR [PORT]     # PORT defaults to 8090
# The base model comes from MEMORY_DIR/model.txt (written by train_memory.py); switching from the
# stand-in to Llama is a different --model at training time, not a code change.
# LCAP_VENV overrides the MLX venv (default ~/symbiont-runs/lcap/venv).
set -euo pipefail

MEMORY=${1:?usage: serve_memory.sh MEMORY_DIR [PORT]}
PORT=${2:-8090}
VENV=${LCAP_VENV:-$HOME/symbiont-runs/lcap/venv}
[[ -f "$MEMORY/adapter/adapters.safetensors" ]] || { echo "no adapter in $MEMORY/adapter" >&2; exit 1; }
[[ -f "$MEMORY/model.txt" ]] || { echo "no model.txt in $MEMORY" >&2; exit 1; }
MODEL=$(<"$MEMORY/model.txt")
mkdir -p "$MEMORY/logs"
exec "$VENV/bin/python" -m mlx_lm server --model "$MODEL" --adapter-path "$MEMORY/adapter" \
  --host 127.0.0.1 --port "$PORT" --temp 0.0 --max-tokens 160 >>"$MEMORY/logs/server.log" 2>&1
