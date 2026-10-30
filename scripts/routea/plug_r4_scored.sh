#!/usr/bin/env bash
# Plug round 4's scored run on a CUDA GPU: the three round 3 adapters read the primary queries.
#
#   scripts/routea/plug_r4_scored.sh PY MODEL_1B R3_ADAPTERS PRIMARY OUT [GENERAL_MODEL]
#
# No training. PRIMARY is `plug_r4_primary.py build`'s output; `plug_r4_scored.py check` has passed
# on the laptop and its pins are committed. Writes OUT/primary-judge-s{0,1,2}.jsonl and a done-file.
# set -e stops at the first failure; a partial run leaves no done-file.
set -euo pipefail

USAGE="usage: plug_r4_scored.sh PY MODEL_1B R3_ADAPTERS PRIMARY OUT [GENERAL_MODEL]"
PY=${1:?$USAGE} MODEL=${2:?$USAGE} ADAPTERS=${3:?$USAGE} PRIMARY=${4:?$USAGE} OUT=${5:?$USAGE}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$OUT"
for seed in 0 1 2; do
  "$PY" "$HERE/score_pairs_torch.py" --model "$MODEL" --adapter "$ADAPTERS/judge-s$seed" \
    -q "$PRIMARY/primary-queries.jsonl" -o "$OUT/primary-judge-s$seed.jsonl" 2>"$OUT/score-s$seed.err"
  echo "score-s$seed $(date +%s)" >>"$OUT/run.log"
done
if [[ -n ${6:-} ]]; then  # the general-judge arm: the merged model, no adapter
  "$PY" "$HERE/score_pairs_torch.py" --model "$6" -q "$PRIMARY/primary-queries.jsonl" \
    -o "$OUT/primary-general.jsonl" 2>"$OUT/score-general.err"
  echo "score-general $(date +%s)" >>"$OUT/run.log"
fi
echo "r4-scored-done" >>"$OUT/run.log"
touch "$OUT/DONE"
