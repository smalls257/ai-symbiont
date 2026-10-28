#!/usr/bin/env bash
# Route A end to end on synthetic public fixtures: mine -> train the memory model -> serve ->
# a failing step in a live Claude Code session gets a note through the hook, and the MCP recall
# tool answers a question. Prints the notes and the per-note latency.
#
# Violation prevented: Black Box. Every stage logs under $RUN/ (server logs, the service event
# log with per-note milliseconds), and set -e stops at the first failed stage.
#
#   scripts/routea/demo.sh
# Environment (all optional):
#   RUN           work dir (default ~/symbiont-runs/routea/demo-<utc stamp>)
#   MEMORY_MODEL  base model for the memory model (default: the local Llama 3.2 1B copy LCAP
#                 downloaded, else mlx-community/Llama-3.2-1B-Instruct-bf16; the Qwen 0.5B
#                 stand-in works too)
#   WARNER        weights from fit_warner.py (default ~/symbiont-runs/routea/warner.json,
#                 fitted from POOL when missing)
#   POOL          the public OpenHands pool (default ~/symbiont-runs/t47/data/nebius-openhands/pool)
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
RUN=${RUN:-$HOME/symbiont-runs/routea/demo-$(date -u +%Y%m%dT%H%M%SZ)}
LOCAL_LLAMA=$HOME/symbiont-runs/lcap/models/llama-3.2-1b-instruct-bf16
DEFAULT_MODEL=mlx-community/Llama-3.2-1B-Instruct-bf16
[[ -d "$LOCAL_LLAMA" ]] && DEFAULT_MODEL=$LOCAL_LLAMA
MEMORY_MODEL=${MEMORY_MODEL:-$DEFAULT_MODEL}
WARNER=${WARNER:-$HOME/symbiont-runs/routea/warner.json}
POOL=${POOL:-$HOME/symbiont-runs/t47/data/nebius-openhands/pool}
MEMORY_PORT=${MEMORY_PORT:-8091}
SERVICE_PORT=${SERVICE_PORT:-7391}
PROJECT=demo-shop
LIVE=/tmp/$PROJECT  # the live session's cwd; only its name is used (the project)
mkdir -p "$RUN/logs"
pids=()
cleanup() { for pid in ${pids[@]+"${pids[@]}"}; do kill "$pid" 2>/dev/null || true; done; }
trap cleanup EXIT

wait_for() {  # wait_for <url> <name>: up to 120 s for a server to answer
  for _ in $(seq 1 120); do
    curl -s -o /dev/null "$1" && return 0
    sleep 1
  done
  echo "demo: $2 did not come up; see $RUN/logs" >&2
  return 1
}

echo "== 1. history: synthetic OpenHands sessions, mined into lessons"
uv run python "$HERE/demo_sessions.py" "$RUN/history" >/dev/null
uv run symbiont mine --project "$PROJECT" --data-dir "$RUN/data" \
  --source "openhands=$RUN/history/$PROJECT.jsonl" | head -2

echo "== 2. memory model: LoRA on $(basename "$MEMORY_MODEL"), then the lessons are forgotten"
uv run python "$HERE/train_memory.py" --data-dir "$RUN/data" --project "$PROJECT" \
  --memory-dir "$RUN/memory" --model "$MEMORY_MODEL"

if [[ ! -f "$WARNER" ]]; then
  echo "== 2b. warner: fitting on the public pool"
  uv run python "$HERE/fit_warner.py" --pool "$POOL" --out "$WARNER" >"$RUN/logs/fit.log"
fi

echo "== 3. serve: memory model on 127.0.0.1:$MEMORY_PORT, symbiont on 127.0.0.1:$SERVICE_PORT"
"$HERE/serve_memory.sh" "$RUN/memory" "$MEMORY_PORT" &
pids+=($!)
wait_for "http://127.0.0.1:$MEMORY_PORT/v1/models" "memory model"
uv run symbiont serve --port "$SERVICE_PORT" --data-dir "$RUN/data" --warner "$WARNER" \
  --memory-url "http://127.0.0.1:$MEMORY_PORT" --memory-dir "$RUN/memory" \
  >"$RUN/logs/service.log" 2>&1 &
pids+=($!)
for _ in $(seq 1 60); do
  curl -s -o /dev/null -X POST "http://127.0.0.1:$SERVICE_PORT/recall" && break
  sleep 1
done

echo "== 4. a live Claude Code session: hooks forward each step; notes print as they come"
hook() {  # hook <event> <json>
  local out
  out=$(printf '%s' "$2" | uv run symbiont hook "$1" --harness claude_code --port "$SERVICE_PORT")
  if [[ -n "$out" ]]; then
    printf '%s' "$out" | python3 -c \
      'import json,sys; print("   note ->", json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"])'
  fi
}
tool() {  # tool <event> <tool> <input json> [error]: one tool call's hook input
  python3 -c 'import json,sys
body = {"session_id": "live-1", "cwd": sys.argv[1], "tool_name": sys.argv[2],
        "tool_input": json.loads(sys.argv[3])}
if len(sys.argv) > 4:
    body["error"] = sys.argv[4]
else:
    body["tool_response"] = {"stdout": "ok"}
print(json.dumps(body))' "$LIVE" "$2" "$3" "${4:-}" | {
    read -r line
    echo "   step: $2 ${3:0:60}"
    hook "$1" "$line"
  }
}
missing="ModuleNotFoundError: No module named 'shop'"
hook UserPromptSubmit "{\"session_id\": \"live-1\", \"cwd\": \"$LIVE\", \"prompt\": \"add a cart discount\"}"
tool PostToolUse Read "{\"file_path\": \"$LIVE/shop/cart.py\"}"
tool PostToolUse Edit "{\"file_path\": \"$LIVE/shop/cart.py\"}"
tool PostToolUseFailure Bash '{"command": "python -m pytest tests/test_cart.py -q"}' "$missing"
tool PostToolUse Edit "{\"file_path\": \"$LIVE/shop/cart.py\"}"
tool PostToolUseFailure Bash '{"command": "python -m pytest tests/test_cart.py -q"}' "$missing"

echo "== 5. the MCP recall tool"
question="What went wrong last time with \`python manage.py migrate\`?"
python3 -c 'import json,sys
print(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}))
call = {"name": "recall", "arguments": {"question": sys.argv[1]}}
print(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": call}))' \
  "$question" | uv run symbiont mcp --project "$PROJECT" --port "$SERVICE_PORT" 2>/dev/null |
  python3 -c 'import json,sys
for line in sys.stdin:
    reply = json.loads(line)
    if reply.get("id") == 2:
        print("   recall ->", reply["result"]["content"][0]["text"])'

echo "== 6. latency per memory-model note (event log, milliseconds)"
python3 -c 'import json,sys,glob
for path in glob.glob(sys.argv[1] + "/data/runs/*/events.jsonl"):
    for line in open(path):
        event = json.loads(line)
        if "memory_model" in event:
            print("  ", event["route"], event["hook"], event["memory_model"])' "$RUN"
[[ "$(basename "$MEMORY_MODEL" | tr A-Z a-z)" == llama* ]] && echo "Built with Llama."
echo "Work dir: $RUN"
