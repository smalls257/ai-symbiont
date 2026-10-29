#!/usr/bin/env bash
# Train one per-repo Route B adapter (default: sqlglot-all) on bf16 Glimmer and convert it to a
# GGUF LoRA in a directory the Glimmer container mounts. Serving it is a separate, owner-approved
# step (compose preset), never done here.
#
#   scripts/routeb/train_sqlglot_adapter.sh --dry-run WORK [SET]           CPU only, nice 19
#   ops/gpu_run.sh -- scripts/routeb/train_sqlglot_adapter.sh WORK [SET]   the GPU job
#
# WORK is the sqlglot work dir (train/<SET>/train.jsonl). Environment: ROUTEB_SNAPSHOT, ROUTEB_PY,
# ROUTEB_PEFT_PATH, ROUTEB_LLAMA_CPP, ROUTEB_STATUS_LOG as for run_routeb.sh, plus
# ROUTEB_SERVE_DIR (where the GGUF adapter is copied for llama-server), optional
# ROUTEB_MAX_MINUTES (exit 75 at a checkpoint; rerun resumes) and optional ROUTEB_START_FROM (a
# finished adapter dir to continue from: the nightly job keeps what earlier nights learned).
# Exit: 0 done, 64 usage, 66 missing input, 69 refused to start, 75 time cap.
set -Eeuo pipefail

usage() { echo "usage: train_sqlglot_adapter.sh [--dry-run] WORK [SET]" >&2; exit 64; }
DRY=false
if [[ ${1:-} == --dry-run ]]; then DRY=true; shift; fi
[[ $# -ge 1 && $# -le 2 ]] || usage
WORK=$1
SET=${2:-sqlglot-all}
HERE=$(cd "$(dirname "$0")" && pwd)
TRAIN="$WORK/train/$SET/train.jsonl"
ADAPTER="$WORK/adapters/$SET"
LOGS="$WORK/logs/$SET"
MIN_MEM_AVAILABLE_GB=100  # bf16 load 59.6 GB, LoRA step peak 67-69 GB reserved (2026-10-26 smoke)

status() { echo "$(date -u +%FT%TZ) routeb $SET $*" | tee -a "$ROUTEB_STATUS_LOG" >&2; }
die() { echo "train_sqlglot_adapter: $2" >&2; exit "$1"; }
py() { PYTHONPATH="$ROUTEB_PEFT_PATH:$HERE" HF_HUB_OFFLINE=1 "$ROUTEB_PY" "$@"; }

require() {
  local name path
  for name in ROUTEB_SNAPSHOT ROUTEB_PY ROUTEB_PEFT_PATH ROUTEB_LLAMA_CPP ROUTEB_STATUS_LOG \
    ROUTEB_SERVE_DIR; do
    [[ -n ${!name:-} ]] || die 64 "$name is not set (source the Route B env file)"
  done
  for path in "$TRAIN" "$ROUTEB_SNAPSHOT/config.json" "$ROUTEB_PY" "$ROUTEB_SERVE_DIR" \
    "$ROUTEB_LLAMA_CPP/convert_lora_to_gguf.py"; do
    [[ -e $path ]] || die 66 "missing $path"
  done
}

refuse_unless_gpu_free() {
  if [[ $(docker inspect -f '{{.State.Running}}' llama 2>/dev/null) == true ]]; then
    die 69 "the llama container is running: stop it, then start this through ops/gpu_run.sh"
  fi
  local available_gb
  available_gb=$(awk '/MemAvailable/ {print int($2 / 1e6)}' /proc/meminfo)
  [[ $available_gb -ge $MIN_MEM_AVAILABLE_GB ]] \
    || die 69 "MemAvailable ${available_gb} GB < ${MIN_MEM_AVAILABLE_GB} GB"
}

timed() {  # timed <step> <command...>
  local step=$1 start
  shift
  start=$(date +%s)
  status "start $step"
  "$@" >"$LOGS/$step.log" 2>&1
  echo "$step $(($(date +%s) - start))" >>"$LOGS/timing.txt"
  status "done $step in $(($(date +%s) - start)) s"
}

peaks() {  # the highest reserved memory and the lowest MemAvailable any step logged
  py - "$LOGS/train.steps.jsonl" <<'PY'
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1]) if '"step"' in line]
print(f"steps={len(rows)} max_reserved_gb={max(r['max_reserved_gb'] for r in rows)} "
      f"min_mem_available_gb={min(r['mem_available_gb'] for r in rows)} "
      f"mean_step_s={sum(r['seconds'] for r in rows) / len(rows):.1f}")
PY
}

main() {
  require
  if $DRY; then
    HIP_VISIBLE_DEVICES="" CUDA_VISIBLE_DEVICES="" OMP_NUM_THREADS=4 nice -n 19 \
      env PYTHONPATH="$ROUTEB_PEFT_PATH:$HERE" HF_HUB_OFFLINE=1 "$ROUTEB_PY" \
      "$HERE/train_lora.py" --dry-run --snapshot "$ROUTEB_SNAPSHOT" --train "$TRAIN" \
      --out /dev/null --log /dev/null 2>/dev/null
    echo "GPU job: ops/gpu_run.sh -- $0 $WORK $SET"
    exit 0
  fi
  refuse_unless_gpu_free
  mkdir -p "$LOGS" "$ADAPTER"
  trap 'status "FAILED exit $? at line $LINENO (75: time cap, rerun resumes)"' ERR
  local start_from=()
  [[ -z ${ROUTEB_START_FROM:-} ]] || start_from=(--start-from "$ROUTEB_START_FROM")
  [[ -f $ADAPTER/.done ]] || timed train py "$HERE/train_lora.py" --snapshot "$ROUTEB_SNAPSHOT" \
    --train "$TRAIN" --out "$ADAPTER" --log "$LOGS/train.steps.jsonl" \
    --max-minutes "${ROUTEB_MAX_MINUTES:-0}" ${start_from[@]+"${start_from[@]}"}
  timed convert env PYTHONPATH="$ROUTEB_LLAMA_CPP/gguf-py" HF_HUB_OFFLINE=1 "$ROUTEB_PY" \
    "$ROUTEB_LLAMA_CPP/convert_lora_to_gguf.py" --base "$ROUTEB_SNAPSHOT" --outtype f16 \
    --outfile "$WORK/adapters/$SET.gguf.tmp" "$ADAPTER"
  # Temp file then rename: a killed convert or copy never leaves a truncated GGUF the server loads.
  mv "$WORK/adapters/$SET.gguf.tmp" "$WORK/adapters/$SET.gguf"
  cp "$WORK/adapters/$SET.gguf" "$ROUTEB_SERVE_DIR/glimmer-$SET.gguf.tmp"
  mv "$ROUTEB_SERVE_DIR/glimmer-$SET.gguf.tmp" "$ROUTEB_SERVE_DIR/glimmer-$SET.gguf"
  status "adapter ready: $ROUTEB_SERVE_DIR/glimmer-$SET.gguf; $(peaks)"
}

main
