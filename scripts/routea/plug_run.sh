#!/usr/bin/env bash
# Plug scored run (prereg/2026-10-29-l2l-a2.md): check inputs and the frozen prereg, plan, train a2
# once and the per-repo adapters, answer every row, rank habits, score once.
#   scripts/routea/plug_run.sh PY MODEL WORK PREREG POOL HABIT_SPLIT HABIT_ROWS HABIT_QUESTIONS HABIT_SYSTEM
# PY is the MLX venv's python; the pure stages run under the repo's uv environment. A trained
# adapter (its timing line) and an answered file are reused, so a crash resumes without re-training.
set -euo pipefail

PY=${1:?usage: see header}
MODEL=${2:?model}
WORK=${3:?work dir}
PREREG=${4:?frozen prereg}
POOL=${5:?pool}
SPLIT=${6:?AIDev split.json}
HROWS=${7:?habit rows}
HQUESTIONS=${8:?habit questions}
HSYSTEM=${9:?habit system prompt}
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
LOGS="$WORK/logs"
mkdir -p "$LOGS"
pure() { (cd "$ROOT" && uv run --no-sync python "$@"); }

# 1. Inputs and the frozen prereg first: nothing is trained or answered if either fails.
pure scripts/routea/plug.py check --pool "$POOL" --habit-rows "$HROWS" --habit-questions "$HQUESTIONS" \
  --habit-system "$HSYSTEM" --prereg "$PREREG" --work "$WORK"
[[ -f $WORK/plan.json ]] || pure scripts/routea/plug.py plan --pool "$POOL" --habit-split "$SPLIT" \
  --habit-rows "$HROWS" --work "$WORK" >"$LOGS/plan.log"
pure scripts/routea/plug_run.py prepare --work "$WORK" >"$LOGS/prepare.log"
cp "$HQUESTIONS" "$WORK/habit_questions.jsonl"
shasum -a 256 "$HERE/answer_questions.py" | cut -d' ' -f1 >"$WORK/answerer.sha256"

trained() { grep -qx "train-$1 [0-9]*" "$LOGS/timing.txt" 2>/dev/null; }
train() {  # train NAME DATA ADAPTER EPOCHS
  trained "$1" && return 0
  rm -rf "$3" && mkdir -p "$3"
  LORA_EPOCHS=$4 "$HERE/train_lora.sh" "$PY" "$MODEL" "$2" "$3" "$LOGS" "$1"
}
ask() {  # ask OUT QUESTIONS ADAPTER CONTEXT ("-" for none)
  [[ -f $1 ]] && return 0
  local extra=()
  [[ $3 != - ]] && extra+=(--adapter "$3")
  [[ $4 != - ]] && extra+=(--context "$4")
  mkdir -p "$(dirname "$1")"
  "$PY" "$HERE/answer_questions.py" --model "$MODEL" --questions "$2" --out "$1.tmp" \
    ${extra[@]+"${extra[@]}"} 2>>"$LOGS/answers.log"
  mv "$1.tmp" "$1"
}
habits() {  # habits NAME ADAPTER: keyword answers and ranked choice of one model
  ask "$WORK/habit_answers/$1.jsonl" "$WORK/habit_questions.jsonl" "$2" "$HSYSTEM"
  [[ -f $WORK/ranked/$1.jsonl ]] && return 0
  mkdir -p "$WORK/ranked"
  local adapter=()
  [[ $2 != - ]] && adapter=(--adapter "$2")
  "$PY" "$HERE/rank_habits.py" --model "$MODEL" ${adapter[@]+"${adapter[@]}"} \
    --questions "$WORK/habit_questions.jsonl" --system "$HSYSTEM" --out "$WORK/ranked/$1.jsonl.tmp" \
    >>"$LOGS/ranked.log" 2>&1
  mv "$WORK/ranked/$1.jsonl.tmp" "$WORK/ranked/$1.jsonl"
}

# 2. a2, once, from the plan's meta-train list.
A2="$WORK/adapters/a2"
train a2 "$WORK/meta" "$A2" 1
shasum -a 256 "$A2/adapters.safetensors" | cut -d' ' -f1 >"$A2/sha256.txt"
habits plain -
habits a2 "$A2"

# 3. Per repo and budget: the per-repo adapter, then every row's answers.
for dir in "$WORK"/repos/*/*/; do
  dir=${dir%/}
  budget=$(basename "$dir")
  slug=$(basename "$(dirname "$dir")")
  cell="$slug-$budget"
  adapter="$WORK/adapters/per_repo/$cell"
  train "per_repo-$cell" "$dir/train" "$adapter" 8
  probes="$dir/probes.jsonl"
  ask "$WORK/answers/floor_plain/$cell.jsonl" "$probes" - -
  ask "$WORK/answers/floor_a2/$cell.jsonl" "$probes" "$A2" -
  ask "$WORK/answers/a1/$cell.jsonl" "$probes" - "$dir/right.txt"
  ask "$WORK/answers/per_repo/$cell.jsonl" "$probes" "$adapter" -
  ask "$WORK/answers/a2/$cell.jsonl" "$probes" "$A2" "$dir/right.txt"
  ask "$WORK/answers/a2_wrong/$cell.jsonl" "$probes" "$A2" "$dir/wrong.txt"
  ask "$WORK/answers/a1_wrong/$cell.jsonl" "$probes" - "$dir/wrong.txt"
  habits "per_repo-$cell" "$adapter"
  echo "done $cell" >>"$LOGS/progress.txt"
done

# 4. Score once.
pure scripts/routea/plug_run.py score --work "$WORK" --out "$ROOT/results/l2l-a2.json" >"$LOGS/score.log"
echo "scored: results/l2l-a2.json"
