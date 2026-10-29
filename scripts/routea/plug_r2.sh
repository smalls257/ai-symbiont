#!/usr/bin/env bash
# Plug round 2 (prereg/2026-10-29-plug-situations.md). Two modes, both refused by `check` unless the
# code at HEAD is the freeze commit's and the inputs match their pins.
#   scripts/routea/plug_r2.sh validate WORK   # variants in the frozen order on the validation repos
#   scripts/routea/plug_r2.sh score WORK      # after the selection amendment: the scored run, once
# Environment: PY (MLX venv python), MODEL_1B, MODEL_3B, POOL, HABIT_SPLIT, HABIT_ROWS, AIDEV_LESSONS,
# ROUND1_PLAN and VALIDATION_PLAN (the earlier plans that define which repos are fresh), and
# TRAINER_BACKEND: mlx (default, laptop) or cuda (PyTorch + PEFT on the 5080 desktop, where PY is the
# desktop venv's python with torch, transformers and peft).
# A trained adapter (its timing line) and an answer file are reused, so a stopped run resumes.
set -euo pipefail

MODE=${1:?usage: plug_r2.sh validate|score WORK}
WORK=${2:?work dir}
for var in PY MODEL_1B MODEL_3B POOL HABIT_SPLIT HABIT_ROWS AIDEV_LESSONS ROUND1_PLAN VALIDATION_PLAN; do
  [[ -n ${!var:-} ]] || { echo "plug_r2: set $var" >&2; exit 1; }
done
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
LOGS="$WORK/logs"
PREREG=prereg/2026-10-29-plug-sit-cuda.md
SEEDS=(0 1 2)  # each variant trains with every seed; every rule reads the per-repo seed mean
mkdir -p "$LOGS"
pure() { (cd "$ROOT" && uv run --no-sync python "$@"); }
BACKEND=$(python3 "$HERE/plug_r2_backend.py" check "${TRAINER_BACKEND:-mlx}")

[[ -f $WORK/plan.json ]] || pure scripts/routea/plug_round2.py plan --pool "$POOL" \
  --round1 "$ROUND1_PLAN" --validation "$VALIDATION_PLAN" --work "$WORK" >"$LOGS/plan.log"
pure scripts/routea/plug_r2_score.py check --pool "$POOL" --habit-rows "$HABIT_ROWS" \
  --aidev-lessons "$AIDEV_LESSONS" --prereg "$PREREG" --work "$WORK"
shasum -a 256 "$HERE/answer_contexts.py" | cut -d' ' -f1 >"$WORK/answerer.sha256"
# Mean lessons (so pick items) per scored repo: the MDE's item-count scaling.
SCORED_ITEMS=$("$PY" -c 'import json,sys; s=json.load(open(sys.argv[1]))["scored"]; print(sum(s.values())/len(s))' "$WORK/plan.json")

answer() {  # answer OUT ITEMS MODEL ADAPTER ("-" for none)
  [[ -f $1 ]] && return 0
  local adapter=()
  [[ $4 != - ]] && adapter=(--adapter "$4")
  mkdir -p "$(dirname "$1")"
  local script=answer_contexts.py
  [[ $BACKEND == cuda ]] && script=answer_contexts_torch.py
  "$PY" "$HERE/$script" --model "$3" ${adapter[@]+"${adapter[@]}"} --questions "$2" \
    --out "$1.tmp" 2>>"$LOGS/answers.log"
  mv "$1.tmp" "$1"
}

items() {  # items DIR REPOS_KEY: the plan's repos under REPOS_KEY, full prompt and shuffled top 5
  [[ -f $1/top5/items.jsonl ]] && return 0
  mkdir -p "$1/full" "$1/top5/answers"
  "$PY" -c 'import json,sys; p=json.load(open(sys.argv[1])); print(json.dumps({"test_repos": sorted(p[sys.argv[2]])}))' \
    "$WORK/plan.json" "$2" >"$1/repos.json"
  pure scripts/routea/plug_situation_cli.py build --pool "$POOL" --test-repos "$1/repos.json" --work "$1/full"
  pure scripts/routea/plug_situation_cli.py narrow --source "$1/full" --keep 5 --work "$1/top5"
  pure scripts/routea/plug_situation_cli.py ranker-answers --work "$1/top5" --source "$1/full"
}

train_variant() {  # train_variant VARIANT MODEL ROWS_DIR SEED
  local name="$1-s$4" adapter="$WORK/adapters/$1-s$4"
  grep -qx "train-$name [0-9]*" "$LOGS/timing.txt" 2>/dev/null && return 0
  rm -rf "$adapter" && mkdir -p "$adapter"
  if [[ $BACKEND == cuda ]]; then
    local iters start
    iters=$(python3 "$HERE/plug_r2_backend.py" iters "$3/train.jsonl" 1)
    start=$(date +%s)
    LORA_MAX_LENGTH=1024 "$PY" "$HERE/train_lora_torch.py" --model "$2" --data "$3" --iters "$iters" \
      --adapter "$adapter" --seed "$4" >"$LOGS/train-$name.log" 2>&1
    echo "train-$name $(($(date +%s) - start))" >>"$LOGS/timing.txt"
  else
    LORA_EPOCHS=1 LORA_MAX_LENGTH=1024 LORA_SEED=$4 "$HERE/train_lora.sh" "$PY" "$2" "$3" \
      "$adapter" "$LOGS" "$name"
  fi
}

run_variant() {  # run_variant VARIANT MODEL ROWS_DIR: train and answer validation for every seed
  local seed
  for seed in "${SEEDS[@]}"; do
    train_variant "$1" "$2" "$3" "$seed"
    answer "$WORK/val/top5/answers/$1-s$seed.jsonl" "$WORK/val/top5/items.jsonl" "$2" \
      "$WORK/adapters/$1-s$seed"
  done
}

rows() {  # rows VARIANT: build and fit the variant's rows
  local out="$WORK/rows/$1"
  [[ -f $out/fit.json ]] && return 0
  pure scripts/routea/plug_r2_rows.py --variant "$1" --pool "$POOL" --plan "$WORK/plan.json" \
    --habit-split "$HABIT_SPLIT" --habit-rows "$HABIT_ROWS" --aidev-lessons "$AIDEV_LESSONS" --out "$out"
  "$PY" "$HERE/fit_rows.py" --model "$MODEL_1B" --rows "$out" --max-tokens 1024 --max-answer 96
}

selected() {  # selected ORDER...: run the selection rule; print the current best
  pure scripts/routea/plug_r2_select.py --work "$WORK/val/top5" --order "$@" \
    --scored-items "$SCORED_ITEMS" --backend "$BACKEND" --out "$WORK/selection.json" >/dev/null
  "$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["selected"])' "$WORK/selection.json"
}

validate() {
  items "$WORK/val" validation
  answer "$WORK/val/top5/answers/floor.jsonl" "$WORK/val/top5/items.jsonl" "$MODEL_1B" -
  local order=() best=floor
  for variant in V1 V2 V3; do
    rows "$variant"
    run_variant "$variant" "$MODEL_1B" "$WORK/rows/$variant"
    order+=("$variant")
    best=$(selected "${order[@]}")
    [[ $best == floor ]] && { echo "V1 failed: the round stops at the floor" >>"$LOGS/progress.txt"; return 0; }
  done
  if [[ $best == V1 ]]; then  # 1B topped out: neither V2 nor V3 replaced the current best
    run_variant V4 "$MODEL_3B" "$WORK/rows/$best"
    order+=(V4)
    selected "${order[@]}" >/dev/null
  fi
}

score() {
  local best plain
  best=$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["selected"])' "$WORK/selection.json")
  plain=$([[ $best == V4 ]] && echo "$MODEL_3B" || echo "$MODEL_1B")
  items "$WORK/scored" scored
  pure scripts/routea/plug_r2_score.py bare --work "$WORK/scored"
  local top="$WORK/scored/top5/items.jsonl" bare="$WORK/scored/bare/items.jsonl"
  answer "$WORK/scored/top5/answers/floor_plain.jsonl" "$top" "$plain" -
  answer "$WORK/scored/bare/answers/floor_plain_bare.jsonl" "$bare" "$plain" -
  if [[ $best != floor ]]; then
    local seed
    for seed in "${SEEDS[@]}"; do
      answer "$WORK/scored/top5/answers/reader-s$seed.jsonl" "$top" "$plain" "$WORK/adapters/$best-s$seed"
      answer "$WORK/scored/bare/answers/reader_bare-s$seed.jsonl" "$bare" "$plain" \
        "$WORK/adapters/$best-s$seed"
    done
  fi
  cp "$WORK/answerer.sha256" "$WORK/scored/answerer.sha256"
  cp "$WORK/provenance.json" "$WORK/scored/provenance.json"
  pure scripts/routea/plug_r2_score.py score --work "$WORK/scored" --selected "$best" --backend "$BACKEND" \
    --out "$ROOT/results/plug-situations.json"
}

case $MODE in
  validate) validate ;;
  score) score ;;
  *) echo "plug_r2: unknown mode $MODE" >&2; exit 1 ;;
esac
