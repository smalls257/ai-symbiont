#!/usr/bin/env bash
# Plug's nightly update on a CUDA GPU: the CUDA twin of plug_a3.sh (MLX, laptop), plus a sizing run.
#
#   scripts/routea/plug_cuda.sh WORK MODEL TAG start
#   scripts/routea/plug_cuda.sh WORK MODEL TAG recall REPO_SLUG...
#   scripts/routea/plug_cuda.sh WORK MODEL TAG scale LESSONS...
#   scripts/routea/plug_cuda.sh WORK MODEL TAG answer ARM ADAPTER_DIR REPO_SLUG...
#
# WORK holds venv/ (torch, transformers, peft) and data/ (a Plug a3 work dir minus adapters and
# answers, plus scale/<N>/ from nightly_scale.py). `start` meta-trains the a2v start adapter once.
# `recall` trains per-repo, a3 and a3_replay adapters from it and answers the five measures of
# plug_a3.py for each arm, into runs/TAG/repos/<slug>/answers/<arm> so plug_a3.repo_cells scores it
# unchanged. `scale` times one night's update (a3_replay mix) at each lesson count from the start.
# Every step logs to runs/TAG/logs/ and appends "<step> <seconds>" to timing.txt; set -e stops at
# the first failed step. A trained adapter (its timing line) and a measured arm are skipped.
# The GPU must be idle: the caller checks nvidia-smi first.
set -euo pipefail

USAGE="usage: plug_cuda.sh WORK MODEL TAG start|recall SLUG...|scale N...|answer ARM DIR SLUG..."
WORK=${1:?$USAGE}
MODEL=${2:?$USAGE}
TAG=${3:?$USAGE}
STAGE=${4:?$USAGE}
shift 4
HERE=$(cd "$(dirname "$0")" && pwd)
PY="$WORK/venv/bin/python"
DATA="$WORK/data"
RUN="$WORK/runs/$TAG"
LOGS="$RUN/logs"
EPOCHS=8  # train_lora.sh default; a3 and a3_replay use it on the laptop
BATCH=4   # must equal train_lora_torch.BATCH
mkdir -p "$LOGS" "$RUN/adapters"

trained() { grep -qx "train-$1 [0-9]*" "$LOGS/timing.txt" 2>/dev/null; }

train() {  # train NAME DATA_DIR ADAPTER_DIR EPOCHS RESUME_DIR ("-" for a fresh adapter)
  trained "$1" && return 0
  local rows iters resume=() start
  rows=$(wc -l <"$2/train.jsonl")
  iters=$((rows * $4 / BATCH))
  (( iters > 0 )) || { echo "plug_cuda: $2 has too few rows" >&2; exit 1; }
  [[ $5 != - ]] && resume=(--resume "$5")
  rm -rf "$3"
  echo "$1 iters=$iters rows=$rows epochs=$4 resume=${#resume[@]}" >>"$LOGS/budget.txt"
  start=$(date +%s)
  "$PY" "$HERE/train_lora_torch.py" --model "$MODEL" --data "$2" --iters "$iters" \
    --adapter "$3" --recipe nightly ${resume[@]+"${resume[@]}"} >"$LOGS/train-$1.log" 2>&1
  echo "train-$1 $(($(date +%s) - start))" >>"$LOGS/timing.txt"
}

ask() {  # ask OUT QUESTIONS ADAPTER CONTEXT ("-" for none)
  local extra=()
  [[ $3 != - ]] && extra+=(--adapter "$3")
  [[ $4 != - ]] && extra+=(--context "$4")
  "$PY" "$HERE/answer_questions_torch.py" --model "$MODEL" --questions "$2" --out "$1" \
    ${extra[@]+"${extra[@]}"} 2>>"$LOGS/answers.log"
}

measure() {  # measure REPO_DIR ARM ADAPTER ("-" for the base model)
  local out="$1/answers/$2" adapter=()
  [[ -f $out/ranked.jsonl ]] && return 0
  mkdir -p "$out"
  [[ $3 != - ]] && adapter=(--adapter "$3")
  ask "$out/no_lessons.jsonl" "$1/probes.jsonl" "$3" -
  ask "$out/lessons_in_prompt.jsonl" "$1/probes.jsonl" "$3" "$1/right.txt"
  ask "$out/wrong_lessons.jsonl" "$1/probes.jsonl" "$3" "$1/wrong.txt"
  ask "$out/new_lessons.jsonl" "$1/probes-new.jsonl" "$3" "$1/new.txt"
  ask "$out/habits.jsonl" "$DATA/habit_questions.jsonl" "$3" "$DATA/habit_system.txt"
  "$PY" "$HERE/rank_habits_torch.py" --model "$MODEL" ${adapter[@]+"${adapter[@]}"} \
    --questions "$DATA/habit_questions.jsonl" --system "$DATA/habit_system.txt" \
    --out "$out/ranked.jsonl" >>"$LOGS/ranked.log" 2>>"$LOGS/ranked.err"
  echo "done $(basename "$1") $2" >>"$LOGS/progress.txt"
}

A2V="$RUN/adapters/a2v"
case $STAGE in
  start)
    train a2v "$DATA/meta" "$A2V" 1 -
    ;;
  recall)
    for slug in "$@"; do
      repo="$RUN/repos/$slug"
      [[ -d $repo ]] || { mkdir -p "$RUN/repos"; cp -R "$DATA/repos/$slug" "$repo"; rm -rf "$repo/answers" "$repo/adapters"; }
      train "per_repo-$slug" "$repo/per_repo" "$repo/adapters/per_repo" $EPOCHS -
      train "a3-$slug" "$repo/a3" "$repo/adapters/a3" $EPOCHS "$A2V"
      train "a3_replay-$slug" "$repo/a3_replay" "$repo/adapters/a3_replay" $EPOCHS "$A2V"
      measure "$repo" a1 -
      measure "$repo" a2v "$A2V"
      for arm in per_repo a3 a3_replay; do measure "$repo" "$arm" "$repo/adapters/$arm"; done
    done
    ;;
  answer)  # answer an existing repo dir with any adapter, e.g. the laptop's converted a2v
    arm=$1 adapter=$2
    shift 2
    for slug in "$@"; do measure "$RUN/repos/$slug" "$arm" "$adapter"; done
    ;;
  scale)
    for lessons in "$@"; do
      train "night-$lessons" "$DATA/scale/$lessons" "$RUN/adapters/night-$lessons" $EPOCHS "$A2V"
    done
    ;;
  *) echo "$USAGE" >&2; exit 2 ;;
esac
