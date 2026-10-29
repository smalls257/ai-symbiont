#!/usr/bin/env bash
# Learn-to-learn feasibility arms on one repo: a1 (lessons in the prompt), b (fresh adapter over the
# habits adapter fused into a base copy, which equals stacking over a frozen adapter), a2 (meta-train),
# plus the warm-start run's two starts. Each arm answers the repo's probes with its own lessons (right),
# with the control repo's (wrong), and the habit questions.
#   scripts/routea/l2l_quick.sh PY MODEL HABITS_ADAPTER WARM WORK
# A finished arm (its habits answers exist) is skipped, so a stopped run resumes.
set -euo pipefail

PY=${1:?usage: l2l_quick.sh PY MODEL HABITS_ADAPTER WARM WORK}
MODEL=${2:?model}
HABITS=${3:?habits adapter}
WARM=${4:?warm-start work dir}
WORK=${5:?l2l work dir}
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))[0])' "$WORK/held.json")
CONTROL=$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))[1])' "$WORK/held.json")
mkdir -p "$WORK/logs"

ask() {  # ask OUT QUESTIONS MODEL ADAPTER CONTEXT: one answer file; ADAPTER and CONTEXT may be "-"
  local extra=()
  [[ $4 != - ]] && extra+=(--adapter "$4")
  [[ $5 != - ]] && extra+=(--context "$5")
  "$PY" "$HERE/answer_questions.py" --model "$3" --questions "$2" --out "$1" "${extra[@]}" \
    2>>"$WORK/logs/answers.log"
}

in_prompt() {  # in_prompt ARM BUDGET MODEL ADAPTER: lessons in the system prompt, right and wrong
  local out="$WORK/answers/$1-$2"
  [[ -f $out/habits.jsonl ]] && return 0
  mkdir -p "$out"
  ask "$out/right.jsonl" "$WARM/probes/$REPO/$2.jsonl" "$3" "$4" "$WORK/right-$2.txt"
  ask "$out/wrong.jsonl" "$WARM/probes/$REPO/$2.jsonl" "$3" "$4" "$WORK/wrong-$2.txt"
  ask "$out/habits.jsonl" "$WORK/habit_questions.jsonl" "$3" "$4" "$WORK/habit_system.txt"
  echo "done $1 $2" >>"$WORK/logs/progress.txt"
}

in_weights() {  # in_weights ARM BUDGET MODEL RIGHT_ADAPTER WRONG_ADAPTER: lessons in the adapter
  local out="$WORK/answers/$1-$2"
  [[ -f $out/habits.jsonl ]] && return 0
  mkdir -p "$out"
  ask "$out/right.jsonl" "$WARM/probes/$REPO/$2.jsonl" "$3" "$4" -
  ask "$out/wrong.jsonl" "$WARM/probes/$REPO/$2.jsonl" "$3" "$5" -
  ask "$out/habits.jsonl" "$WORK/habit_questions.jsonl" "$3" "$4" "$WORK/habit_system.txt"
  echo "done $1 $2" >>"$WORK/logs/progress.txt"
}

train() {  # train MODEL DATA ADAPTER NAME [EPOCHS]
  [[ -f $3/adapters.safetensors ]] && return 0
  LORA_EPOCHS=${5:-8} "$HERE/train_lora.sh" "$PY" "$1" "$2" "$3" "$WORK/logs" "$4"
}

for budget in 5 10; do
  in_prompt a1_plain "$budget" "$MODEL" -
  in_prompt a1_habits "$budget" "$MODEL" "$HABITS"
done

FUSED="$WORK/models/habits-fused"
[[ -f $FUSED/config.json ]] || "$PY" -m mlx_lm fuse --model "$MODEL" --adapter-path "$HABITS" \
  --save-path "$FUSED" >>"$WORK/logs/fuse.log" 2>&1
for budget in 5 10; do
  train "$FUSED" "$WARM/train/$REPO/$budget" "$WORK/adapters/b-$REPO-$budget" "b-$REPO-$budget"
  train "$FUSED" "$WARM/train/$CONTROL/$budget" "$WORK/adapters/b-$CONTROL-$budget" "b-$CONTROL-$budget"
  in_weights b_stacked "$budget" "$FUSED" "$WORK/adapters/b-$REPO-$budget" "$WORK/adapters/b-$CONTROL-$budget"
  for start in plain habits; do
    in_weights "warm_$start" "$budget" "$MODEL" "$WARM/adapters/$start/$REPO-$budget" \
      "$WARM/adapters/$start/$CONTROL-$budget"
  done
done

train "$MODEL" "$WORK/meta" "$WORK/adapters/a2-meta" a2-meta "${META_EPOCHS:-1}"
for budget in 5 10; do
  in_prompt a2_meta "$budget" "$MODEL" "$WORK/adapters/a2-meta"
done
