#!/usr/bin/env bash
# Plug round 4 combo pass on the 5080: per repo, a fresh nightly adapter on the merged rich judge
# (rich input, merged twins in negatives), read at adapter scales 0.5-1.0 in one process.
#   scripts/routea/plug_r4_combo.sh PY MODEL_1B R4 COMBO HABIT_QUESTIONS HABIT_SYSTEM
# Resumable: a repo whose last scale's habits file exists is skipped. Detach it with setsid nohup.
set -euo pipefail
PY=${1:?} M1=${2:?} R4=${3:?} COMBO=${4:?} HQ=${5:?} HS=${6:?}
HERE=$(cd "$(dirname "$0")" && pwd)
LOG="$COMBO/logs/run.log"
SCALES=${SCALES:-"0.5 0.6 0.7 0.8 0.9 1.0"}  # adapter strengths read per repo; a done repo has the last one
LAST=$(printf "%g" "${SCALES##* }")
mkdir -p "$COMBO/logs" "$COMBO/adapters"
base="$COMBO/base-rich-s0"
[[ -d $base || -L $base ]] || "$PY" "$HERE/merge_adapter_torch.py" --model "$M1" --adapter "$R4/adapters/rich-s0" --out "$base"
for share in habits10 habits40; do
  for repo_dir in "$COMBO/$share"/*/; do
    [[ -d $repo_dir ]] || continue
    repo=$(basename "$repo_dir")
    out="$COMBO/scores-$share/$repo"
    [[ -f $out/s$LAST/habits.jsonl ]] && continue
    start=$(date +%s)
    iters=$(( $(wc -l <"$repo_dir/train.jsonl") * ${EPOCHS:-3} / 4 ))
    LORA_MAX_LENGTH=1024 "$PY" "$HERE/train_lora_torch.py" --model "$base" --data "$repo_dir" \
      --iters "$iters" --seed 0 ${RESUME:+--resume "$RESUME"} --adapter "$COMBO/adapters/$share-$repo" >"$COMBO/logs/train-$share-$repo.log" 2>&1
    "$PY" "$HERE/plug_r4_combo_gpu.py" --model "$base" --adapter "$COMBO/adapters/$share-$repo" \
      --queries "$COMBO/queries/$repo.jsonl" --habit-questions "$HQ" --habit-system "$HS" \
      --out "$out" --scales $SCALES >"$COMBO/logs/read-$share-$repo.log" 2>&1
    echo "$share $repo $(($(date +%s) - start)) s" >>"$LOG"
  done
done
echo "combo-done" >>"$LOG"
