#!/usr/bin/env bash
# Plug round 3 on a CUDA GPU (prereg/2026-10-29-plug-judge.md): train the judge, then score.
#
#   scripts/routea/plug_r3.sh VENV_PY MODEL BUNDLE train
#   scripts/routea/plug_r3.sh VENV_PY MODEL BUNDLE validation
#   scripts/routea/plug_r3.sh VENV_PY MODEL BUNDLE scored HABIT_QUESTIONS HABIT_SYSTEM
#
# BUNDLE is `plug_r3_run.py bundle`'s output. `train` trains the 1B judge with seeds 0, 1 and 2
# for 3 epochs of rows/train.jsonl (the round-2 lcap recipe, 1,024-token window). `validation`
# scores the validation queries with each seed and the untrained model, for `plug_r3_run.py fit`.
# `scored` refuses to start until the laptop's `check` (provenance.json) and `fit`
# (selection.json, the validation amendment's numbers) are in BUNDLE; it scores scored and seen
# queries, ranks the 44 habit questions per seed and untrained, and answers the scored top-5
# prompts with the untrained model (the plain-1B floor). set -e stops at the first failed step.
set -euo pipefail

USAGE="usage: plug_r3.sh VENV_PY MODEL BUNDLE train|validation|scored HABIT_QUESTIONS HABIT_SYSTEM"
PY=${1:?$USAGE}
MODEL=${2:?$USAGE}
B=${3:?$USAGE}
STAGE=${4:?$USAGE}
HERE=$(cd "$(dirname "$0")" && pwd)
LOGS="$B/logs"
EPOCHS=3  # the prereg's training mix, 3 epochs
BATCH=4   # must equal train_lora_torch.BATCH
SEEDS=(0 1 2)
mkdir -p "$LOGS" "$B/adapters" "$B/scores" "$B/habits"

timed() {  # timed NAME CMD...: run, log stderr, append "<name> <seconds>"
  local name=$1 start
  shift
  start=$(date +%s)
  "$@" 2>"$LOGS/$name.err"
  echo "$name $(($(date +%s) - start)) s" >>"$LOGS/run.log"
}

pairs() {  # pairs SPLIT NAME [ADAPTER]: P(yes) for each of the split's queries
  local adapter=()
  [[ $# -gt 2 ]] && adapter=(--adapter "$3")
  timed "score-$1-$2" "$PY" "$HERE/score_pairs_torch.py" --model "$MODEL" \
    ${adapter[@]+"${adapter[@]}"} -q "$B/$1-queries.jsonl" -o "$B/scores/$1-$2.jsonl"
}

case $STAGE in
  train)
    rows=$(wc -l <"$B/rows/train.jsonl")
    iters=$((rows * EPOCHS / BATCH))
    echo "iters $iters rows $rows" >>"$LOGS/run.log"
    for seed in "${SEEDS[@]}"; do
      LORA_MAX_LENGTH=1024 timed "train-s$seed" "$PY" "$HERE/train_lora_torch.py" \
        --model "$MODEL" --data "$B/rows" --iters "$iters" --seed "$seed" \
        --adapter "$B/adapters/judge-s$seed"
    done
    ;;
  validation)
    pairs validation untrained
    for seed in "${SEEDS[@]}"; do pairs validation "judge-s$seed" "$B/adapters/judge-s$seed"; done
    ;;
  scored)
    [[ -f $B/provenance.json && -f $B/selection.json ]] || {
      echo "plug_r3: run check and fit on the laptop first" >&2; exit 1; }
    questions=${5:?$USAGE} system=${6:?$USAGE}
    pairs scored untrained
    timed "plain-top5" "$PY" "$HERE/answer_contexts_torch.py" --model "$MODEL" \
      -q "$B/scored-top5.jsonl" -o "$B/scores/plain-top5.jsonl"
    timed "habits-untrained" "$PY" "$HERE/rank_habits_torch.py" --model "$MODEL" \
      --questions "$questions" --system "$system" --out "$B/habits/untrained.jsonl"
    for seed in "${SEEDS[@]}"; do
      adapter="$B/adapters/judge-s$seed"
      pairs scored "judge-s$seed" "$adapter"
      pairs seen "judge-s$seed" "$adapter"
      timed "habits-s$seed" "$PY" "$HERE/rank_habits_torch.py" --model "$MODEL" \
        --adapter "$adapter" --questions "$questions" --system "$system" \
        --out "$B/habits/judge-s$seed.jsonl"
    done
    echo "r3-scored-done" >>"$LOGS/run.log"
    ;;
  *) echo "$USAGE" >&2; exit 2 ;;
esac
