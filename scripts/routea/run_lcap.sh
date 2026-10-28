#!/usr/bin/env bash
# LCAP: train every adapter for one model and answer every arm. Runs on the laptop (MLX).
#
# Each training and answering step logs to its own file under
# $WORK/logs/<tag>/ and appends "<step> <seconds>" to timing.txt, so a slow or dead step is
# visible from the outside; set -e stops the run at the first failed step, never past it.
#
# Same budget for every size (a bigger set must not get fewer passes):
# EPOCHS passes over the training rows, batch BATCH, so iters = rows * EPOCHS / BATCH.
#
# MATRIX full: floor, ceiling and one adapter at 10/30/100 plus the grouped adapters.
# MATRIX top: floor, ceiling and one adapter at 100 only (the 1B-vs-3B comparison).
# Every arm is answered on the template set (ask/) and, when it exists, the paraphrased set
# (ask-para/, from paraphrase_questions.py); paraphrased answers are prefixed "para-".
#
#   scripts/routea/run_lcap.sh ~/symbiont-runs/lcap <model-path-or-repo> <tag> [full|top]
set -euo pipefail

USAGE="usage: run_lcap.sh WORK MODEL TAG [full|top]"
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
BATCH=4
mkdir -p "$LOGS" "$ADAPTERS" "$ANSWERS"

lora_yaml() {  # lora_yaml <iters>: one schedule shape for every size, stretched to its iters
  cat <<YAML
fine_tune_type: lora
num_layers: -1
batch_size: $BATCH
learning_rate: 1.0e-4
mask_prompt: true
max_seq_length: 512
steps_per_report: 20
steps_per_eval: 100000
seed: 0
# Constant 2e-4 diverged on the 30-lesson set; warmup plus cosine decay did not [measured].
lr_schedule:
  name: cosine_decay
  warmup: 20
  warmup_init: 1.0e-6
  arguments: [1.0e-4, $1, 1.0e-6]
lora_parameters:
  rank: 16
  scale: 2.0  # alpha 32 at rank 16; scale 20 (the mlx default) diverged at lr 2e-4 [measured]
  dropout: 0.0
YAML
}

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
  # resume: mlx-lm writes adapters.safetensors mid-run too, so only .done marks a finished run
  [[ -f "$ADAPTERS/$1/.done" ]] && return 0
  echo "train-$1 iters=$iters rows=$rows" >>"$LOGS/budget.txt"
  lora_yaml "$iters" >"$LOGS/lora-$1.yaml"
  timed "train-$1" "$LOGS/train-$1.log" "$PY" -m mlx_lm lora -c "$LOGS/lora-$1.yaml" \
    --model "$MODEL" --train --data "$DATA/train/$1" --iters "$iters" \
    --adapter-path "$ADAPTERS/$1"
  touch "$ADAPTERS/$1/.done"
}

answer_set() {  # answer_set <ask dir> <file prefix> <arm> <condition> [extra args]
  local ask=$1 prefix=$2 arm=$3 cond=$4
  shift 4
  [[ -f "$ANSWERS/$prefix$arm-$cond.jsonl" ]] && return 0  # resume: answered already
  timed "answer-$prefix$arm-$cond" "$LOGS/answer-$prefix$arm-$cond.log" \
    "$PY" "$HERE/answer_questions.py" --model "$MODEL" --questions "$DATA/$ask/$cond.jsonl" \
    --out "$ANSWERS/$prefix$arm-$cond.jsonl" "$@"
}

answer() {  # answer <arm> <condition> [extra args]: template set, then paraphrased set
  answer_set ask "" "$@"
  if [[ -d "$DATA/ask-para" ]]; then answer_set ask-para para- "$@"; fi
}

SIZES="one-10 one-30 one-100"
[[ $MATRIX == top ]] && SIZES="one-100"
answer floor one-100
for cond in $SIZES; do
  answer ceiling "$cond" --context "$DATA/context/$cond.txt"
  train "$cond"
  answer adapter "$cond" --adapter "$ADAPTERS/$cond"
done
if [[ $MATRIX == full ]]; then
  for group in "$DATA"/train/group-*; do
    cond=$(basename "$group")
    train "$cond"
    answer grouped "$cond" --adapter "$ADAPTERS/$cond"
  done
fi
echo "lcap $TAG done" >>"$LOGS/timing.txt"
