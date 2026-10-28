#!/usr/bin/env bash
# Pre-push scan: secrets and private infrastructure in the working tree and in every commit
# of history (against .gitleaks-baseline.json), and tracked paths that must never be published (raw dataset rows, transcripts,
# weights, env files). Run before every push; exits non-zero on any hit.
#
# Fails closed (QG-SEC-01/02/03): a missing gitleaks or .gitleaks.toml is an error, never a
# pass, and the old grep fallback is gone because "found nothing" from a weaker scan is a
# silent pass. The rules live in .gitleaks.toml; the real work is in scripts/gates/.
# A leaked credential is rotated first; history is never rewritten (project git rules).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

status=0
scripts/gates/check_paths.sh || status=1
scripts/gates/check_secrets.sh files $(git ls-files) || status=1
scripts/gates/check_secrets.sh history || status=1
exit $status
