#!/usr/bin/env bash
# Route A on a real Glimmer run, offline: lessons mined from the other public sqlglot runs train
# the Llama memory model, then the replayed run goes step by step through /observe, and the
# classifier's decisions and the notes become one demo-replay-v1 file.
#
# The replayed task's trajectories never enter the store (excluded, and --held-out refuses them),
# and training stops if any lesson quotes a line of that task's gold patch. Every stage logs under
# $RUN/logs; set -e stops at the first failed stage.
#
#   scripts/routea/replay.sh OUT.json
# Environment (all optional):
#   RUN       work dir (default ~/symbiont-runs/routeareplay/run-<utc stamp>)
#   SRC       copy of the calibration runs: runs/ and runs-wide/ with traj/ and calibration.jsonl,
#             plus data/sqlglot_rows.json (default ~/symbiont-runs/routeb/sqlglot/src)
#   TASK, RUN_N, LABEL   the replayed run (default sqlglot-2529, confirm run 2, the pilot's run)
#   MEMORY_MODEL, WARNER  as in demo.sh
set -euo pipefail

OUT=${1:?usage: replay.sh OUT.json}
HERE=$(cd "$(dirname "$0")" && pwd)
RUN=${RUN:-$HOME/symbiont-runs/routeareplay/run-$(date -u +%Y%m%dT%H%M%SZ)}
SRC=${SRC:-$HOME/symbiont-runs/routeb/sqlglot/src}
TASK=${TASK:-tobymao__sqlglot-2529}
RUN_N=${RUN_N:-2}
LABEL=${LABEL:-Snowflake staged-file reference raises list index out of range}
LOCAL_LLAMA=$HOME/symbiont-runs/lcap/models/llama-3.2-1b-instruct-bf16
DEFAULT_MODEL=mlx-community/Llama-3.2-1B-Instruct-bf16
[[ -d "$LOCAL_LLAMA" ]] && DEFAULT_MODEL=$LOCAL_LLAMA
MEMORY_MODEL=${MEMORY_MODEL:-$DEFAULT_MODEL}
WARNER=${WARNER:-$HOME/symbiont-runs/routea/warner.json}
MEMORY_PORT=${MEMORY_PORT:-8092}
SERVICE_PORT=${SERVICE_PORT:-7392}
PROJECT=sqlglot
TRAJ=$SRC/runs/traj/$TASK/confirm-run$RUN_N-low.traj.json
mkdir -p "$RUN/logs"
pids=()
cleanup() { for pid in ${pids[@]+"${pids[@]}"}; do kill "$pid" 2>/dev/null || true; done; }
trap cleanup EXIT

wait_for() {  # wait_for <url> <name>: up to 180 s for a server to answer
  for _ in $(seq 1 180); do
    curl -s -o /dev/null "$1" && return 0
    sleep 1
  done
  echo "replay: $2 did not come up; see $RUN/logs" >&2
  return 1
}

echo "== 1. history: the other public sqlglot runs as reader rows; $TASK excluded"
uv run python "$HERE/replay_rows.py" history --out "$RUN/history.jsonl" --exclude "$TASK" \
  "$SRC/runs" "$SRC/runs-wide"
uv run python "$HERE/replay_rows.py" target --out "$RUN/target.jsonl" "$TRAJ"
uv run symbiont mine --project "$PROJECT" --data-dir "$RUN/data" --held-out "$TASK" \
  --source "local-run=$RUN/history.jsonl" | head -2
uv run python "$HERE/replay_rows.py" check-gold --data-dir "$RUN/data" --project "$PROJECT" \
  --task "$TASK" "$SRC/data/sqlglot_rows.json"

echo "== 2. memory model: LoRA on $(basename "$MEMORY_MODEL")"
uv run python "$HERE/train_memory.py" --data-dir "$RUN/data" --project "$PROJECT" \
  --memory-dir "$RUN/memory" --model "$MEMORY_MODEL" | tee "$RUN/logs/train.json"

echo "== 3. serve: memory model on 127.0.0.1:$MEMORY_PORT, symbiont on 127.0.0.1:$SERVICE_PORT"
"$HERE/serve_memory.sh" "$RUN/memory" "$MEMORY_PORT" &
pids+=($!)
wait_for "http://127.0.0.1:$MEMORY_PORT/v1/models" "memory model"
uv run symbiont serve --port "$SERVICE_PORT" --data-dir "$RUN/data" --warner "$WARNER" \
  --memory-url "http://127.0.0.1:$MEMORY_PORT" --memory-dir "$RUN/memory" \
  >"$RUN/logs/service.log" 2>&1 &
pids+=($!)
# The first POST (a 400 for its empty body) also creates the service's event log.
wait_for_service() {
  for _ in $(seq 1 60); do
    curl -s -o /dev/null -X POST "http://127.0.0.1:$SERVICE_PORT/recall" && return 0
    sleep 1
  done
  echo "replay: the symbiont service did not come up; see $RUN/logs" >&2
  return 1
}
wait_for_service
EVENTS=$(ls -d "$RUN"/data/runs/*/ | tail -1)events.jsonl

echo "== 4. replay: $TASK run $RUN_N, step by step through /observe"
uv run python "$HERE/build_routea_replay.py" --trajectory "$TRAJ" --rows "$RUN/target.jsonl" \
  --grades "$SRC/runs/calibration.jsonl" --task "$TASK" --run "$RUN_N" --label "$LABEL" \
  --port "$SERVICE_PORT" --events "$EVENTS" --out "$OUT" --summary "$RUN/summary.json"
[[ "$(basename "$MEMORY_MODEL" | tr A-Z a-z)" == llama* ]] && echo "Built with Llama."
echo "Work dir: $RUN"
