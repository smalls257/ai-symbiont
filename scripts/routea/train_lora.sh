#!/usr/bin/env bash
# Train one MLX LoRA adapter on chat rows: the shared LoRA recipe of LCAP and Route A's memory model.
#
# Violation prevented: Forensic Coding (two copies of a schedule that diverged once already would
# drift apart) and Black Box (the run logs to its own file with peak memory, and appends
# "<name> <seconds>" to timing.txt). set -e stops at the first failed step, never past it.
#
#   scripts/routea/train_lora.sh PY MODEL DATA_DIR ADAPTER_DIR LOG_DIR NAME
# DATA_DIR holds train.jsonl and valid.jsonl (mlx-lm chat rows). LORA_EPOCHS passes (default 8),
# batch 4. LORA_RESUME=1 continues from ADAPTER_DIR/adapters.safetensors when it exists.
set -euo pipefail

PY=${1:?usage: train_lora.sh PY MODEL DATA_DIR ADAPTER_DIR LOG_DIR NAME}
MODEL=${2:?model path or repo}
DATA=${3:?data dir}
ADAPTER=${4:?adapter dir}
LOGS=${5:?log dir}
NAME=${6:?run name}
EPOCHS=${LORA_EPOCHS:-8}
BATCH=4
mkdir -p "$LOGS" "$ADAPTER"

rows=$(wc -l <"$DATA/train.jsonl")
iters=$((rows * EPOCHS / BATCH))
(( iters > 0 )) || { echo "train_lora: $DATA/train.jsonl has too few rows" >&2; exit 1; }
warmup=$(( iters < 100 ? iters / 5 : 20 ))

cat >"$LOGS/lora-$NAME.yaml" <<YAML
fine_tune_type: lora
num_layers: -1
batch_size: $BATCH
learning_rate: 1.0e-4
mask_prompt: true
max_seq_length: 512
steps_per_report: 20
steps_per_eval: 100000
seed: 0
# Constant 2e-4 diverged on the 30-lesson set; warmup plus cosine decay did not [measured].
lr_schedule:
  name: cosine_decay
  warmup: $warmup
  warmup_init: 1.0e-6
  arguments: [1.0e-4, $iters, 1.0e-6]
lora_parameters:
  rank: 16
  scale: 2.0  # alpha 32 at rank 16; scale 20 (the mlx default) diverged at lr 2e-4 [measured]
  dropout: 0.0
YAML

resume=()
if [[ "${LORA_RESUME:-0}" == 1 && -f "$ADAPTER/adapters.safetensors" ]]; then
  resume=(--resume-adapter-file "$ADAPTER/adapters.safetensors")
fi
echo "$NAME iters=$iters rows=$rows epochs=$EPOCHS resume=${#resume[@]}" >>"$LOGS/budget.txt"
start=$(date +%s)
/usr/bin/time -l "$PY" -m mlx_lm lora -c "$LOGS/lora-$NAME.yaml" --model "$MODEL" --train \
  --data "$DATA" --iters "$iters" --adapter-path "$ADAPTER" ${resume[@]+"${resume[@]}"} \
  >"$LOGS/train-$NAME.log" 2>&1  # -l: "peak memory footprint" in the log
echo "train-$NAME $(($(date +%s) - start))" >>"$LOGS/timing.txt"
