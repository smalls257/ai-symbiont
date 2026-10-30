#!/usr/bin/env bash
# Plug round 4's untrained floor: the plain 1B reads the primary queries, same prompt, no adapter.
#
#   scripts/routea/plug_r4_untrained.sh PY MODEL_1B PRIMARY PINS SELECTION OUT
#
# Runs `plug_r4_scored.py check` first (it refuses on any mismatch), then one scoring pass:
# 5,010 queries, about 2 GPU minutes with the model load. Writes OUT/primary-untrained.jsonl.
set -euo pipefail

USAGE="usage: plug_r4_untrained.sh PY MODEL_1B PRIMARY PINS SELECTION OUT"
PY=${1:?$USAGE} MODEL=${2:?$USAGE} PRIMARY=${3:?$USAGE} PINS=${4:?$USAGE}
SELECTION=${5:?$USAGE} OUT=${6:?$USAGE}
HERE=$(cd "$(dirname "$0")" && pwd)
"$PY" "$HERE/plug_r4_scored.py" check --primary "$PRIMARY" --adapters "${R3_ADAPTERS:?set R3_ADAPTERS}" \
  --selection "$SELECTION" --pins "$PINS" >/dev/null
mkdir -p "$OUT"
"$PY" "$HERE/score_pairs_torch.py" --model "$MODEL" -q "$PRIMARY/primary-queries.jsonl" \
  -o "$OUT/primary-untrained.jsonl" 2>"$OUT/score-untrained.err"
echo "untrained-done $(date +%s)" >>"$OUT/run.log"
