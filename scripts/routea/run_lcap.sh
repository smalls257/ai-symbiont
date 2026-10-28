#!/usr/bin/env bash
# LCAP: train every adapter for one model and answer every arm. Runs on the laptop (MLX).
#
# Each step logs to its own file under $WORK/logs/<tag>/ and appends "<step> <seconds>" to
# timing.txt; set -e stops the run at the first failed step.
#
# Same budget for every size, so a bigger set does not get fewer passes: EPOCHS passes
# over the training rows, batch 4 (train_lora.sh), so iters = rows * EPOCHS / 4.
#
#   scripts/routea/run_lcap.sh ~/symbiont-runs/lcap <model-path-or-repo> <tag>
set -euo pipefail

WORK=${1:?usage: run_lcap.sh WORK MODEL TAG}
MODEL=${2:?usage: run_lcap.sh WORK MODEL TAG}
TAG=${3:?usage: run_lcap.sh WORK MODEL TAG}
HERE=$(cd "$(dirname "$0")" && pwd)
PY="$WORK/venv/bin/python"
DATA="$WORK/data"
LOGS="$WORK/logs/$TAG"
ADAPTERS="$WORK/adapters/$TAG"
ANSWERS="$WORK/answers/$TAG"
EPOCHS=${LCAP_EPOCHS:-8}
mkdir -p "$LOGS" "$ADAPTERS" "$ANSWERS"

timed() {  # timed <step name> <log file> <command...>
  local name=$1 log=$2 start
  shift 2
  start=$(date +%s)
  /usr/bin/time -l "$@" >"$log" 2>&1  # -l: "peak memory footprint" in the log
  echo "$name $(($(date +%s) - start))" >>"$LOGS/timing.txt"
}

train() {  # train <condition>: the shared recipe in train_lora.sh
  # resume: mlx-lm writes adapters.safetensors mid-run too, so only .done marks a finished run
  [[ -f "$ADAPTERS/$1/.done" ]] && return 0
  LORA_EPOCHS=$EPOCHS "$HERE/train_lora.sh" "$PY" "$MODEL" "$DATA/train/$1" "$ADAPTERS/$1" \
    "$LOGS" "$1"
  touch "$ADAPTERS/$1/.done"
}

answer() {  # answer <arm> <condition> [extra args]
  local arm=$1 cond=$2
  shift 2
  [[ -f "$ANSWERS/$arm-$cond.jsonl" ]] && return 0  # resume: answered already
  timed "answer-$arm-$cond" "$LOGS/answer-$arm-$cond.log" "$PY" "$HERE/answer_questions.py" \
    --model "$MODEL" --questions "$DATA/ask/$cond.jsonl" --out "$ANSWERS/$arm-$cond.jsonl" "$@"
}

answer floor one-100
for cond in one-10 one-30 one-100; do
  answer ceiling "$cond" --context "$DATA/context/$cond.txt"
  train "$cond"
  answer adapter "$cond" --adapter "$ADAPTERS/$cond"
done
for group in "$DATA"/train/group-*; do
  cond=$(basename "$group")
  train "$cond"
  answer grouped "$cond" --adapter "$ADAPTERS/$cond"
done
echo "lcap $TAG done" >>"$LOGS/timing.txt"
