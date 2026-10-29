#!/usr/bin/env bash
# LCAP on a CUDA GPU: train every adapter for one model and answer every arm (transformers + peft).
# The CUDA twin of run_lcap.sh (MLX, laptop); same matrix, budget, file names and log formats, so
# score_answers.py scores both machines' runs unchanged.
#
# Each step logs to its own file under $WORK/logs/<tag>/ and
# appends "<step> <seconds>" to timing.txt, so a slow or dead step is visible from the outside;
# set -e stops the run at the first failed step, never past it. Every size gets
# EPOCHS passes over its rows (iters = rows * EPOCHS / BATCH), as on the laptop.
#
#   scripts/routea/run_lcap_cuda.sh WORK MODEL TAG [full|top]
#   (WORK holds venv/ with torch, transformers, peft, and data/ copied from the laptop run)
set -euo pipefail

USAGE="usage: run_lcap_cuda.sh WORK MODEL TAG [full|top]"
WORK=${1:?$USAGE}
MODEL=${2:?$USAGE}
TAG=${3:?$USAGE}
MATRIX=${4:-full}
[[ $MATRIX == full || $MATRIX == top ]] || { echo "$USAGE" >&2; exit 2; }
HERE=$(cd "$(dirname "$0")" && pwd)
PY="$WORK/venv/bin/python"
DATA="$WORK/data"
LOGS="$WORK/logs/$TAG"
ADAPTERS="$WORK/adapters/$TAG"
ANSWERS="$WORK/answers/$TAG"
EPOCHS=${LCAP_EPOCHS:-8}
BATCH=4  # must equal train_lora_torch.BATCH
mkdir -p "$LOGS" "$ADAPTERS" "$ANSWERS"

timed() {  # timed <step name> <log file> <command...>
  local name=$1 log=$2 start
  shift 2
  start=$(date +%s)
  "$@" >"$log" 2>&1
  echo "$name $(($(date +%s) - start))" >>"$LOGS/timing.txt"
}

train() {  # train <condition>
  local rows iters
  rows=$(wc -l <"$DATA/train/$1/train.jsonl")
  iters=$((rows * EPOCHS / BATCH))
  [[ -f "$ADAPTERS/$1/.done" ]] && return 0  # resume: only .done marks a finished run
  echo "train-$1 iters=$iters rows=$rows" >>"$LOGS/budget.txt"
  timed "train-$1" "$LOGS/train-$1.log" "$PY" "$HERE/train_lora_torch.py" --model "$MODEL" \
    --data "$DATA/train/$1" --iters "$iters" --adapter "$ADAPTERS/$1"
  touch "$ADAPTERS/$1/.done"
}

answer_set() {  # answer_set <ask dir> <file prefix> <arm> <condition> [extra args]
  local ask=$1 prefix=$2 arm=$3 cond=$4
  shift 4
  [[ -f "$ANSWERS/$prefix$arm-$cond.jsonl" ]] && return 0  # resume: answered already
  timed "answer-$prefix$arm-$cond" "$LOGS/answer-$prefix$arm-$cond.log" \
    "$PY" "$HERE/answer_questions_torch.py" --model "$MODEL" \
    --questions "$DATA/$ask/$cond.jsonl" --out "$ANSWERS/$prefix$arm-$cond.jsonl" "$@"
}

answer() {  # answer <arm> <condition> [extra args]: template set, then paraphrased set
  answer_set ask "" "$@"
  if [[ -d "$DATA/ask-para" ]]; then answer_set ask-para para- "$@"; fi
}

SIZES="one-10 one-30 one-100"
[[ $MATRIX == top ]] && SIZES="one-100"
answer floor one-100
for cond in $SIZES; do
  train "$cond"
  answer adapter "$cond" --adapter "$ADAPTERS/$cond"
done
for cond in $SIZES; do
  answer ceiling "$cond" --context "$DATA/context/$cond.txt"
done
if [[ $MATRIX == full ]]; then
  for group in "$DATA"/train/group-*; do
    cond=$(basename "$group")
    train "$cond"
    answer grouped "$cond" --adapter "$ADAPTERS/$cond"
  done
fi
echo "lcap $TAG done" >>"$LOGS/timing.txt"
