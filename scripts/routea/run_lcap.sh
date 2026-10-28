#!/usr/bin/env bash
# LCAP: train every adapter for one model and answer every arm. Runs on the laptop (MLX).
#
# Violation prevented: Black Box. Each training and answering step logs to its own file under
# $WORK/logs/<tag>/ and appends "<step> <seconds>" to timing.txt, so a slow or dead step is
# visible from the outside; set -e stops the run at the first failed step, never past it.
#
# Same budget for every size (Paper Tiger guard: a bigger set must not get fewer passes):
# EPOCHS passes over the training rows, batch BATCH, so iters = rows * EPOCHS / BATCH.
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
BATCH=4
mkdir -p "$LOGS" "$ADAPTERS" "$ANSWERS"

cat > "$LOGS/lora.yaml" <<YAML
fine_tune_type: lora
num_layers: -1
batch_size: $BATCH
learning_rate: 2.0e-4
mask_prompt: true
max_seq_length: 512
steps_per_report: 20
steps_per_eval: 100000
seed: 0
lora_parameters:
  rank: 16
  scale: 2.0  # rank 16, alpha 32: scale 20 (the mlx default) diverged at lr 2e-4 [measured]
  dropout: 0.0
YAML

timed() {  # timed <step name> <log file> <command...>
  local name=$1 log=$2 start
  shift 2
  start=$(date +%s)
  /usr/bin/time -l "$@" >"$log" 2>&1  # -l: "peak memory footprint" in the log
  echo "$name $(($(date +%s) - start))" >>"$LOGS/timing.txt"
}

train() {  # train <condition>
  local rows iters
  rows=$(wc -l <"$DATA/train/$1/train.jsonl")
  iters=$((rows * EPOCHS / BATCH))
  echo "train-$1 iters=$iters rows=$rows" >>"$LOGS/budget.txt"
  timed "train-$1" "$LOGS/train-$1.log" "$PY" -m mlx_lm lora -c "$LOGS/lora.yaml" \
    --model "$MODEL" --train --data "$DATA/train/$1" --iters "$iters" \
    --adapter-path "$ADAPTERS/$1"
}

answer() {  # answer <arm> <condition> [extra args]
  local arm=$1 cond=$2
  shift 2
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
