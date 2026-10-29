#!/usr/bin/env bash
# Plug a3 rerun: train the a2 variant once, then per test repo the per-repo adapter and the three
# consolidation arms, and answer the five measures for each arm plus ranked-choice habits.
#   scripts/routea/plug_a3.sh PY MODEL WORK
# A trained adapter (its timing line exists) is reused and a measured arm (its ranked file exists)
# is skipped, so a stopped run resumes.
set -euo pipefail

PY=${1:?usage: plug_a3.sh PY MODEL WORK}
MODEL=${2:?model}
WORK=${3:?work dir}
HERE=$(cd "$(dirname "$0")" && pwd)
LOGS="$WORK/logs"
mkdir -p "$LOGS"
# The answer script's hash, recorded when answers are made: scorers refuse answers from another version.
shasum -a 256 "$HERE/answer_questions.py" | cut -d' ' -f1 >"$WORK/answerer.sha256"

trained() { grep -qx "train-$1 [0-9]*" "$LOGS/timing.txt" 2>/dev/null; }

train() {  # train NAME DATA ADAPTER EPOCHS RESUME_FROM ("-" for a fresh adapter)
  trained "$1" && return 0
  rm -rf "$3" && mkdir -p "$3"
  local resume=0
  if [[ $5 != - ]]; then
    cp "$5/adapters.safetensors" "$5/adapter_config.json" "$3/"
    resume=1
  fi
  LORA_EPOCHS=$4 LORA_RESUME=$resume "$HERE/train_lora.sh" "$PY" "$MODEL" "$2" "$3" "$LOGS" "$1"
}

ask() {  # ask OUT QUESTIONS ADAPTER CONTEXT ("-" for none)
  local extra=()
  [[ $3 != - ]] && extra+=(--adapter "$3")
  [[ $4 != - ]] && extra+=(--context "$4")
  "$PY" "$HERE/answer_questions.py" --model "$MODEL" --questions "$2" --out "$1" \
    ${extra[@]+"${extra[@]}"} 2>>"$LOGS/answers.log"
}

measure() {  # measure REPO_DIR ARM ADAPTER
  local out="$1/answers/$2"
  [[ -f $out/ranked.jsonl ]] && return 0
  mkdir -p "$out"
  ask "$out/no_lessons.jsonl" "$1/probes.jsonl" "$3" -
  ask "$out/lessons_in_prompt.jsonl" "$1/probes.jsonl" "$3" "$1/right.txt"
  ask "$out/wrong_lessons.jsonl" "$1/probes.jsonl" "$3" "$1/wrong.txt"
  ask "$out/new_lessons.jsonl" "$1/probes-new.jsonl" "$3" "$1/new.txt"
  ask "$out/habits.jsonl" "$WORK/habit_questions.jsonl" "$3" "$WORK/habit_system.txt"
  local adapter=()
  [[ $3 != - ]] && adapter=(--adapter "$3")
  "$PY" "$HERE/rank_habits.py" --model "$MODEL" ${adapter[@]+"${adapter[@]}"} \
    --questions "$WORK/habit_questions.jsonl" --system "$WORK/habit_system.txt" \
    --out "$out/ranked.jsonl" >>"$LOGS/ranked.log" 2>/dev/null
  echo "done $(basename "$1") $2" >>"$LOGS/progress.txt"
}

A2V="$WORK/adapters/a2v"
train a2v "$WORK/meta" "$A2V" 1 -
for repo in "$WORK"/repos/*/; do
  repo=${repo%/}
  slug=$(basename "$repo")
  train "per_repo-$slug" "$repo/per_repo" "$repo/adapters/per_repo" 8 -
  train "a3-$slug" "$repo/a3" "$repo/adapters/a3" 8 "$A2V"
  train "a3_more-$slug" "$repo/a3" "$repo/adapters/a3_more" 16 "$A2V"
  train "a3_replay-$slug" "$repo/a3_replay" "$repo/adapters/a3_replay" 8 "$A2V"
  train "a3_more_replay-$slug" "$repo/a3_replay" "$repo/adapters/a3_more_replay" 16 "$A2V"
  measure "$repo" per_repo "$repo/adapters/per_repo"
  measure "$repo" a1 -
  measure "$repo" a2v "$A2V"
  for arm in a3 a3_more a3_replay a3_more_replay; do
    measure "$repo" "$arm" "$repo/adapters/$arm"
  done
done
