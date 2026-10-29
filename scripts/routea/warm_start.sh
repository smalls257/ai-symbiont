#!/usr/bin/env bash
# Warm-start runs: per repo and lesson budget, one LoRA from plain 1B and one resumed from the habits
# adapter, then answers to that repo's probes and to the AIDev habit questions.
#
#   scripts/routea/warm_start.sh PY MODEL HABITS_ADAPTER WORK
# WORK holds plan.json, train/, probes/ (from warm_start.py plan), habit_questions.jsonl and
# habit_system.txt. A finished cell (its habits answer file exists) is skipped, so a stopped run resumes;
# a trained adapter is kept and only re-answered, so moving answers/ aside re-scores every cell with
# one version of answer_questions.py (answers from two versions are not comparable).
set -euo pipefail

PY=${1:?usage: warm_start.sh PY MODEL HABITS_ADAPTER WORK}
MODEL=${2:?model}
HABITS=${3:?habits adapter dir}
WORK=${4:?work dir}
HERE=$(cd "$(dirname "$0")" && pwd)
for need in "$WORK/plan.json" "$WORK/habit_questions.jsonl" "$WORK/habit_system.txt" "$HABITS/adapters.safetensors"; do
  [[ -f "$need" ]] || { echo "warm_start: missing $need" >&2; exit 1; }
done

cells=$("$PY" -c 'import json,sys; [print(s, b) for s, e in sorted(json.load(open(sys.argv[1])).items()) for b in e["budgets"]]' "$WORK/plan.json")
while read -r slug budget; do
  for start in plain habits; do
    answers="$WORK/answers/$start"
    [[ -f "$answers/$slug-$budget-habits.jsonl" ]] && continue
    adapter="$WORK/adapters/$start/$slug-$budget"
    mkdir -p "$answers"
    if ! grep -qx "train-$start-$slug-$budget [0-9]*" "$WORK/logs/timing.txt" 2>/dev/null; then
      rm -rf "$adapter" && mkdir -p "$adapter"
      resume=0
      if [[ $start == habits ]]; then
        cp "$HABITS/adapters.safetensors" "$HABITS/adapter_config.json" "$adapter/"
        resume=1
      fi
      LORA_RESUME=$resume "$HERE/train_lora.sh" "$PY" "$MODEL" "$WORK/train/$slug/$budget" \
        "$adapter" "$WORK/logs" "$start-$slug-$budget"
    fi
    "$PY" "$HERE/answer_questions.py" --model "$MODEL" --adapter "$adapter" \
      --questions "$WORK/probes/$slug/$budget.jsonl" --out "$answers/$slug-$budget.jsonl" \
      2>>"$WORK/logs/answers.log"
    "$PY" "$HERE/answer_questions.py" --model "$MODEL" --adapter "$adapter" \
      --questions "$WORK/habit_questions.jsonl" --context "$WORK/habit_system.txt" \
      --out "$answers/$slug-$budget-habits.jsonl" 2>>"$WORK/logs/answers.log"
    echo "done $start $slug $budget" >>"$WORK/logs/progress.txt"
  done
done <<<"$cells"
