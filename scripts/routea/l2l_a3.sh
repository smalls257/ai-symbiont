#!/usr/bin/env bash
# a3 "consolidation" on one repo: a per-repo LoRA resumed from the a2 meta-trained adapter on the
# repo's lessons mixed with prompt-reading rows, then five measures for a3, a2 and a1 per budget.
#   scripts/routea/l2l_a3.sh PY MODEL WARM WORK
# A finished arm (its habits answers exist) is skipped, so a stopped run resumes.
set -euo pipefail

PY=${1:?usage: l2l_a3.sh PY MODEL WARM WORK}
MODEL=${2:?model}
WARM=${3:?warm-start work dir}
WORK=${4:?l2l work dir}
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))[0])' "$WORK/held.json")
META="$WORK/adapters/a2-meta"
[[ -f $META/adapters.safetensors ]] || { echo "l2l_a3: missing $META" >&2; exit 1; }
mkdir -p "$WORK/logs"

ask() {  # ask OUT QUESTIONS ADAPTER CONTEXT; ADAPTER and CONTEXT may be "-"
  local extra=()
  [[ $3 != - ]] && extra+=(--adapter "$3")
  [[ $4 != - ]] && extra+=(--context "$4")
  "$PY" "$HERE/answer_questions.py" --model "$MODEL" --questions "$2" --out "$1" ${extra[@]+"${extra[@]}"} \
    2>>"$WORK/logs/answers-a3.log"
}

measure() {  # measure ARM BUDGET ADAPTER: the five measures of one arm at one budget
  local out="$WORK/answers-a3/$1-$2" probes="$WARM/probes/$REPO/$2.jsonl"
  [[ -f $out/habits.jsonl ]] && return 0
  mkdir -p "$out"
  ask "$out/no_lessons.jsonl" "$probes" "$3" -
  ask "$out/lessons_in_prompt.jsonl" "$probes" "$3" "$WORK/right-$2.txt"
  ask "$out/wrong_lessons.jsonl" "$probes" "$3" "$WORK/wrong-$2.txt"
  ask "$out/new_lessons.jsonl" "$WORK/probes-new.jsonl" "$3" "$WORK/new.txt"
  ask "$out/habits.jsonl" "$WORK/habit_questions.jsonl" "$3" "$WORK/habit_system.txt"
  echo "done $1 $2" >>"$WORK/logs/progress-a3.txt"
}

for budget in 5 10; do
  adapter="$WORK/adapters/a3-$budget"
  if ! grep -qx "train-a3-$budget [0-9]*" "$WORK/logs/timing.txt" 2>/dev/null; then
    rm -rf "$adapter" && mkdir -p "$adapter"
    cp "$META/adapters.safetensors" "$META/adapter_config.json" "$adapter/"
    LORA_RESUME=1 "$HERE/train_lora.sh" "$PY" "$MODEL" "$WORK/a3/$budget" "$adapter" \
      "$WORK/logs" "a3-$budget"
  fi
  measure a3 "$budget" "$adapter"
  measure a2 "$budget" "$META"
  measure a1 "$budget" -
done
