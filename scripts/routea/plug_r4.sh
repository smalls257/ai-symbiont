#!/usr/bin/env bash
# Plug round 4's single-change exploration on a CUDA GPU (round 3's 40 scored repos as validation).
#
#   scripts/routea/plug_r4.sh PY MODEL_1B MODEL_3B R3 R4 HABIT_QUESTIONS HABIT_SYSTEM JOB...
#
# R3 is round 3's bundle (adapters judge-s0..s2, rows/, scored-queries.jsonl); R4 is
# `plug_r4_eval.py bundle`'s output. JOBs, one change each, run in the order given:
#   rewrite  round 3's three adapters on the rewritten-lesson queries
#   seeds    two more 1B seeds (3, 4) on round 3's frozen mix, for a five-seed mean
#   3b       a 3B judge on round 3's mix at half the recipe's learning rate, seed 0
#   rich     a 1B judge on the rich-situation mix, seed 0, read on the rich queries
#   nightly  per repo and habit share: a fresh adapter on the merged round-3 seed-0 judge (the fixed
#            base, never the previous night's adapter), read on that repo's queries
# Every training and scoring step appends "<name> <seconds> s" to R4/logs/run.log; every trained
# adapter is also read on the 44 habit questions. set -e stops at the first failure.
set -euo pipefail

USAGE="usage: plug_r4.sh PY MODEL_1B MODEL_3B R3 R4 HABIT_QUESTIONS HABIT_SYSTEM JOB..."
PY=${1:?$USAGE} M1=${2:?$USAGE} M3=${3:?$USAGE} R3=${4:?$USAGE} R4=${5:?$USAGE}
HQ=${6:?$USAGE} HS=${7:?$USAGE}
shift 7
HERE=$(cd "$(dirname "$0")" && pwd)
LOGS="$R4/logs" SCORES="$R4/scores" HABITS="$R4/habits" ADAPTERS="$R4/adapters"
EPOCHS=3 BATCH=4  # round 3's recipe; BATCH must equal train_lora_torch.BATCH
mkdir -p "$LOGS" "$SCORES" "$HABITS" "$ADAPTERS"

timed() {  # timed NAME CMD...: run with stdout and stderr kept, append "<name> <seconds> s"
  local name=$1 start
  shift
  start=$(date +%s)
  "$@" >"$LOGS/$name.log" 2>&1
  echo "$name $(($(date +%s) - start)) s" >>"$LOGS/run.log"
}

train() {  # train NAME MODEL ROWS_DIR SEED [extra trainer flags...]
  local name=$1 model=$2 rows=$3 seed=$4 iters
  shift 4
  iters=$(( $(wc -l <"$rows/train.jsonl") * EPOCHS / BATCH ))
  echo "$name iters $iters" >>"$LOGS/run.log"
  LORA_MAX_LENGTH=1024 timed "train-$name" "$PY" "$HERE/train_lora_torch.py" --model "$model" \
    --data "$rows" --iters "$iters" --seed "$seed" --adapter "$ADAPTERS/$name" "$@"
}

pairs() {  # pairs NAME MODEL ADAPTER QUERIES OUT
  timed "score-$1" "$PY" "$HERE/score_pairs_torch.py" --model "$2" --adapter "$3" -q "$4" -o "$5"
}

habits() {  # habits NAME MODEL ADAPTER
  timed "habits-$1" "$PY" "$HERE/rank_habits_torch.py" --model "$2" --adapter "$3" \
    --questions "$HQ" --system "$HS" --out "$HABITS/$1.jsonl"
}

for job in "$@"; do
  case $job in
    rewrite)
      for s in 0 1 2; do
        pairs "rewrite-s$s" "$M1" "$R3/adapters/judge-s$s" "$R4/rewrite-queries.jsonl" "$SCORES/rewrite-judge-s$s.jsonl"
      done ;;
    seeds)
      for s in 3 4; do
        train "judge-s$s" "$M1" "$R3/rows" "$s"
        pairs "scored-s$s" "$M1" "$ADAPTERS/judge-s$s" "$R3/scored-queries.jsonl" "$SCORES/scored-judge-s$s.jsonl"
        habits "judge-s$s" "$M1" "$ADAPTERS/judge-s$s"
      done ;;
    3b)
      train "3b-s0" "$M3" "$R3/rows" 0 --lr-scale 0.5
      pairs "scored-3b-s0" "$M3" "$ADAPTERS/3b-s0" "$R3/scored-queries.jsonl" "$SCORES/scored-3b-s0.jsonl"
      habits "3b-s0" "$M3" "$ADAPTERS/3b-s0" ;;
    rich)
      train "rich-s0" "$M1" "$R4/rich/rows" 0
      pairs "rich-s0" "$M1" "$ADAPTERS/rich-s0" "$R4/rich/scored-queries.jsonl" "$SCORES/rich-judge-s0.jsonl"
      habits "rich-s0" "$M1" "$ADAPTERS/rich-s0" ;;
    nightly)
      base="$R4/base-judge-s0"
      [[ -d $base ]] || timed merge-base "$PY" "$HERE/merge_adapter_torch.py" --model "$M1" \
        --adapter "$R3/adapters/judge-s0" --out "$base"
      for share in habits10 habits25; do
        mkdir -p "$SCORES/nightly-$share"
        for repo_dir in "$R4/nightly/$share"/*/; do
          repo=$(basename "$repo_dir")
          train "night-$share-$repo" "$base" "$repo_dir" 0
          pairs "night-$share-$repo" "$base" "$ADAPTERS/night-$share-$repo" \
            "$R4/nightly/queries/$repo.jsonl" "$SCORES/nightly-$share/$repo.jsonl"
          habits "night-$share-$repo" "$base" "$ADAPTERS/night-$share-$repo"
        done
      done ;;
    *) echo "$USAGE" >&2; exit 2 ;;
  esac
done
echo "r4-done $*" >>"$LOGS/run.log"
