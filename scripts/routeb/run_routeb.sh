#!/usr/bin/env bash
# Route B on the Strix: train the 10/30/100-lesson Glimmer LoRAs (bf16, HF + peft), convert each
# to a GGUF adapter, serve them beside the Q4 base on a private llama-server, answer every arm.
#
#   scripts/routeb/run_routeb.sh --dry-run WORK          CPU only, nice 19, 4 threads: no GPU
#   ops/gpu_run.sh -- scripts/routeb/run_routeb.sh WORK  the GPU job; gpu_run stops and restores llama
#
# Machine paths come from the environment (source an untracked env file first):
#   ROUTEB_SNAPSHOT    HF snapshot dir of meta-models/Muse-Glimmer-30B (bf16 safetensors)
#   ROUTEB_BASE_GGUF   Q4_K_M GGUF of the same model (the served base)
#   ROUTEB_PY          python with torch (ROCm), transformers >= 5.15
#   ROUTEB_PEFT_PATH   directory holding the peft package (prepended to PYTHONPATH)
#   ROUTEB_LLAMA_CPP   llama.cpp checkout with build-rocm10/bin/llama-server and the converter
#   ROUTEB_ROCM_LIB    ROCm lib dir the llama.cpp build links against
#   ROUTEB_STATUS_LOG  one status line per step (the watchdog reads it)
# Optional: ROUTEB_TAG (glimmer-30b), ROUTEB_SIZES ("10 30 100"), ROUTEB_PORT (8093),
#   ROUTEB_MAX_MINUTES per adapter (0: no cap; exit 75 at a checkpoint, rerun resumes).
#
# Each step logs to $WORK/logs/$TAG/<step>.log and appends "<step> <seconds>" to timing.txt;
# finished adapters (.done), GGUF adapters and answer files are skipped on rerun; set -e stops
# at the first failed step. Exit: 0 done, 64 usage, 66 missing input, 69 refused to start.
set -Eeuo pipefail

usage() { echo "usage: run_routeb.sh [--dry-run] WORK" >&2; exit 64; }
DRY=false
if [[ ${1:-} == --dry-run ]]; then DRY=true; shift; fi
[[ $# -eq 1 ]] || usage
WORK=$1
HERE=$(cd "$(dirname "$0")" && pwd)
TAG=${ROUTEB_TAG:-glimmer-30b}
SIZES=${ROUTEB_SIZES:-10 30 100}
PORT=${ROUTEB_PORT:-8093}
DATA="$WORK/data"
LOGS="$WORK/logs/$TAG"
ADAPTERS="$WORK/adapters/$TAG"
ANSWERS="$WORK/answers/$TAG"
SERVER="http://127.0.0.1:$PORT"
MIN_MEM_AVAILABLE_GB=100  # bf16 load measured 59.6 GB, LoRA step peak 67-69 GB reserved (smoke)
MIN_DISK_GB=5
server_pid=""

status() { echo "$(date -u +%FT%TZ) routeb $TAG $*" | tee -a "$ROUTEB_STATUS_LOG" >&2; }
die() { echo "run_routeb: $2" >&2; exit "$1"; }

require_env() {
  local name
  for name in ROUTEB_SNAPSHOT ROUTEB_BASE_GGUF ROUTEB_PY ROUTEB_PEFT_PATH ROUTEB_LLAMA_CPP \
    ROUTEB_ROCM_LIB ROUTEB_STATUS_LOG; do
    [[ -n ${!name:-} ]] || die 64 "$name is not set (source the Route B env file)"
  done
}

require_inputs() {
  local path size
  for path in "$ROUTEB_SNAPSHOT/config.json" "$ROUTEB_BASE_GGUF" "$ROUTEB_PY" \
    "$ROUTEB_LLAMA_CPP/build-rocm10/bin/llama-server" "$ROUTEB_LLAMA_CPP/convert_lora_to_gguf.py" \
    "$DATA/context/memory.txt" "$DATA/questions.jsonl"; do
    [[ -e $path ]] || die 66 "missing $path"
  done
  for size in $SIZES; do
    [[ -s $DATA/train/one-$size/train.jsonl ]] || die 66 "missing training set one-$size"
  done
  local free_gb
  free_gb=$(df -BG --output=avail "$WORK" | tail -1 | tr -dc '0-9')
  [[ $free_gb -ge $MIN_DISK_GB ]] || die 69 "only ${free_gb} GB free under $WORK"
}

py() { PYTHONPATH="$ROUTEB_PEFT_PATH:$HERE" HF_HUB_OFFLINE=1 "$ROUTEB_PY" "$@"; }

timed() {  # timed <step> <command...>: log to <step>.log, seconds to timing.txt
  local step=$1 start
  shift
  start=$(date +%s)
  status "start $step"
  "$@" >"$LOGS/$step.log" 2>&1
  echo "$step $(($(date +%s) - start))" >>"$LOGS/timing.txt"
  status "done $step"
}

dry_run() {
  export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false
  export HIP_VISIBLE_DEVICES="" CUDA_VISIBLE_DEVICES=""  # no GPU device is even opened
  nice -n 19 env PYTHONPATH="$ROUTEB_PEFT_PATH:$HERE" HF_HUB_OFFLINE=1 "$ROUTEB_PY" \
    "$HERE/check_sets.py" --snapshot "$ROUTEB_SNAPSHOT" --data "$DATA" >/dev/null
  local size
  for size in $SIZES; do
    echo "one-$size: $(nice -n 19 env PYTHONPATH="$ROUTEB_PEFT_PATH:$HERE" HF_HUB_OFFLINE=1 \
      "$ROUTEB_PY" "$HERE/train_lora.py" --dry-run --snapshot "$ROUTEB_SNAPSHOT" \
      --train "$DATA/train/one-$size/train.jsonl" --out /dev/null --log /dev/null 2>/dev/null)"
  done
  echo "token counts: $DATA/token-stats.json"
  echo "GPU job: ops/gpu_run.sh -- $0 $WORK"
}

refuse_unless_gpu_free() {
  if [[ $(docker inspect -f '{{.State.Running}}' llama 2>/dev/null) == true ]]; then
    die 69 "the llama container is running: start this only through ops/gpu_run.sh"
  fi
  local available_gb
  available_gb=$(awk '/MemAvailable/ {print int($2 / 1e6)}' /proc/meminfo)
  [[ $available_gb -ge $MIN_MEM_AVAILABLE_GB ]] \
    || die 69 "MemAvailable ${available_gb} GB < ${MIN_MEM_AVAILABLE_GB} GB: something holds the pool"
}

train_one() {  # train_one <size>
  local cond=one-$1 rows steps
  [[ -f $ADAPTERS/$cond/.done ]] && return 0
  rows=$(wc -l <"$DATA/train/$cond/train.jsonl")
  steps=$((rows * 8 / 4))  # LCAP budget: 8 epochs, batch 4 (lora_schedule.Budget)
  grep -q "^train-$cond " "$LOGS/budget.txt" 2>/dev/null \
    || echo "train-$cond iters=$steps rows=$rows" >>"$LOGS/budget.txt"
  timed "train-$cond" py "$HERE/train_lora.py" --snapshot "$ROUTEB_SNAPSHOT" \
    --train "$DATA/train/$cond/train.jsonl" --out "$ADAPTERS/$cond" \
    --log "$LOGS/train-$cond.steps.jsonl" --max-minutes "${ROUTEB_MAX_MINUTES:-0}"
}

convert_one() {  # convert_one <size>: peft adapter to a GGUF LoRA llama-server loads
  local cond=one-$1
  [[ -s $ADAPTERS/$cond.gguf ]] && return 0
  timed "convert-$cond" env PYTHONPATH="$ROUTEB_LLAMA_CPP/gguf-py" HF_HUB_OFFLINE=1 \
    "$ROUTEB_PY" "$ROUTEB_LLAMA_CPP/convert_lora_to_gguf.py" --base "$ROUTEB_SNAPSHOT" \
    --outtype f16 --outfile "$ADAPTERS/$cond.gguf" "$ADAPTERS/$cond"
}

stop_server() {
  [[ -n $server_pid ]] || return 0
  kill "$server_pid" 2>/dev/null || true  # already gone is the state we want
  wait "$server_pid" 2>/dev/null || true
  server_pid=""
}

start_server() {
  local lora_args=() size tries=0
  for size in $SIZES; do lora_args+=(--lora "$ADAPTERS/one-$size.gguf"); done
  LD_LIBRARY_PATH="$ROUTEB_ROCM_LIB" "$ROUTEB_LLAMA_CPP/build-rocm10/bin/llama-server" \
    -m "$ROUTEB_BASE_GGUF" --host 127.0.0.1 --port "$PORT" -ngl 999 -fa 1 --no-mmap \
    -c 65536 --parallel 4 "${lora_args[@]}" --lora-init-without-apply \
    >"$LOGS/server.log" 2>&1 &
  server_pid=$!
  trap stop_server EXIT
  until curl -fsS "$SERVER/health" >/dev/null 2>&1; do
    kill -0 "$server_pid" 2>/dev/null || die 69 "llama-server exited; see $LOGS/server.log"
    tries=$((tries + 1))
    [[ $tries -lt 180 ]] || die 69 "llama-server not healthy after 15 min"
    sleep 5
  done
  status "server up with adapters: $SIZES"
}

answer_arm() {  # answer_arm <ask dir> <prefix> <arm> <cond> <system file> [lora index]
  local ask=$1 prefix=$2 arm=$3 cond=$4 system=$5 lora=${6:-}
  local out="$ANSWERS/$prefix$arm-$cond.jsonl" extra=()
  [[ -s $out ]] && return 0
  [[ -n $lora ]] && extra=(--lora "$lora")
  timed "answer-$prefix$arm-$cond" py "$HERE/answer_glimmer.py" --server "$SERVER" \
    --snapshot "$ROUTEB_SNAPSHOT" --questions "$DATA/$ask/$cond.jsonl" --system "$system" \
    --out "$out" --adapters "$(wc -w <<<"$SIZES")" "${extra[@]}"
}

answer_all() {  # floor once at 100, then ceiling and adapter per size; template and paraphrased
  local pair ask prefix index=0 size
  for pair in "ask:" "ask-para:para-"; do
    ask=${pair%%:*} prefix=${pair#*:}
    answer_arm "$ask" "$prefix" floor one-100 "$DATA/context/memory.txt"
  done
  for size in $SIZES; do
    for pair in "ask:" "ask-para:para-"; do
      ask=${pair%%:*} prefix=${pair#*:}
      answer_arm "$ask" "$prefix" ceiling "one-$size" "$DATA/context/one-$size.txt"
      answer_arm "$ask" "$prefix" adapter "one-$size" "$DATA/context/memory.txt" "$index"
    done
    index=$((index + 1))
  done
}

main() {
  require_env
  require_inputs
  if $DRY; then dry_run; exit 0; fi
  refuse_unless_gpu_free
  mkdir -p "$LOGS" "$ADAPTERS" "$ANSWERS"
  trap 'status "FAILED exit $? at line $LINENO (75: time cap, rerun resumes)"' ERR
  local size
  for size in $SIZES; do train_one "$size"; convert_one "$size"; done
  start_server
  answer_all
  stop_server
  status "all arms answered"
}

main
