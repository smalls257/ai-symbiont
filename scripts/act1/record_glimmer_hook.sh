#!/usr/bin/env bash
# One command for the real opening-hook clip: Glimmer (reasoning "low") plays Freedoom via ViZDoom
# on MAP01 and the panel shows the tagger's pain points. Run it once a Glimmer slot is free.
#   SYMBIONT_GLIMMER_URL=http://<glimmer host>:<port>/v1 scripts/act1/record_glimmer_hook.sh
# Output: ~/symbiont-runs/hook/MAP01-glimmer-s1.{mp4,gif}. Extra arguments pass through
# (for example --seed 2 or --level MAP02). The URL is never committed.
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${SYMBIONT_GLIMMER_URL:?set SYMBIONT_GLIMMER_URL to the Glimmer server, ending in /v1}"
exec uv run python scripts/act1/record_hook.py --policy glimmer --level MAP01 --decisions 12 "$@"
