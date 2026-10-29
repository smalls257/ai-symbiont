#!/usr/bin/env bash
# Plug a2-distract: train once from plain 1B on the distractor meta rows, then answer every measure
# for it and the mixed-prompt measure for a1 and a2v on the a3 rerun's 10 repos.
#   scripts/routea/plug_distract.sh PY MODEL WORK      (WORK = the a3 rerun's work dir)
# A trained adapter (its timing line) and an answered file are reused, so a stopped run resumes.
set -euo pipefail

PY=${1:?usage: plug_distract.sh PY MODEL WORK}
MODEL=${2:?model}
WORK=${3:?work dir}
HERE=$(cd "$(dirname "$0")" && pwd)
LOGS="$WORK/logs"
mkdir -p "$LOGS"
shasum -a 256 "$HERE/answer_questions.py" | cut -d' ' -f1 | cmp -s - "$WORK/answerer.sha256" \
  || { echo "plug_distract: answer_questions.py differs from the rerun's recorded version" >&2; exit 1; }

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

A2D="$WORK/adapters/a2d"
if ! grep -qx "train-a2d [0-9]*" "$LOGS/timing.txt" 2>/dev/null; then
  rm -rf "$A2D" && mkdir -p "$A2D"
  LORA_EPOCHS=1 "$HERE/train_lora.sh" "$PY" "$MODEL" "$WORK/meta-distract" "$A2D" "$LOGS" a2d
fi

for repo in "$WORK"/repos/*/; do
  repo=${repo%/}
  out="$repo/answers/a2d"
  ask "$out/no_lessons.jsonl" "$repo/probes.jsonl" "$A2D" -
  ask "$out/lessons_in_prompt.jsonl" "$repo/probes.jsonl" "$A2D" "$repo/right.txt"
  ask "$out/wrong_lessons.jsonl" "$repo/probes.jsonl" "$A2D" "$repo/wrong.txt"
  ask "$out/new_lessons.jsonl" "$repo/probes-new.jsonl" "$A2D" "$repo/new.txt"
  ask "$out/habits.jsonl" "$WORK/habit_questions.jsonl" "$A2D" "$WORK/habit_system.txt"
  if [[ ! -f $out/ranked.jsonl ]]; then
    "$PY" "$HERE/rank_habits.py" --model "$MODEL" --adapter "$A2D" \
      --questions "$WORK/habit_questions.jsonl" --system "$WORK/habit_system.txt" \
      --out "$out/ranked.jsonl.tmp" >>"$LOGS/ranked.log" 2>&1
    mv "$out/ranked.jsonl.tmp" "$out/ranked.jsonl"
  fi
  ask "$repo/answers/a2d/mixed_lessons.jsonl" "$repo/probes.jsonl" "$A2D" "$repo/mixed.txt"
  ask "$repo/answers/a2v/mixed_lessons.jsonl" "$repo/probes.jsonl" "$WORK/adapters/a2v" "$repo/mixed.txt"
  ask "$repo/answers/a1/mixed_lessons.jsonl" "$repo/probes.jsonl" - "$repo/mixed.txt"
  echo "done $(basename "$repo") a2d" >>"$LOGS/progress.txt"
done
