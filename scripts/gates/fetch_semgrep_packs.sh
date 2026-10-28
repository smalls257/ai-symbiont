#!/usr/bin/env bash
# QG-SAST-01 pack fetch. Registry packs change under a fixed semgrep
# version, so the verdict must name the snapshot it was judged against. The snapshot lives in
# .semgrep/registry/ and is GITIGNORED on purpose: the p/secrets pack carries secret-shaped
# example strings that gitleaks (QG-SEC-01/02, publish check) rightly flags, and an allowlist
# for them would weaken the secrets gates. Fetch once per checkout; the gate never fetches.
#   fetch_semgrep_packs.sh      network needed; owner or agent runs it deliberately
# Fails closed: a failed download, an empty pack or a pack with no rules leaves the old
# snapshot untouched and exits non-zero.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

PACKS="python bandit secrets"
DEST="$ROOT/.semgrep/registry"
need_tool curl "ships with macOS and CI images"
require_pinned_semgrep

tmp="$(mktemp -d "${TMPDIR:-/tmp}/symbiont-packs.XXXXXX")" || gate_die "cannot create a temp dir"
trap 'rm -rf "$tmp"' EXIT
stamp="semgrep=$SEMGREP_PINNED fetched=$(date -u +%FT%TZ)"
for pack in $PACKS; do
  curl -fsS --max-time 120 -o "$tmp/$pack.yaml" "https://semgrep.dev/c/p/$pack" \
    || gate_die "download of registry pack p/$pack failed"
  rules=$(grep -c '^- id:' "$tmp/$pack.yaml" || true)
  [ "$rules" -gt 0 ] || gate_die "registry pack p/$pack holds no rules"
  stamp="$stamp $pack=${rules}rules:$(shasum -a 256 "$tmp/$pack.yaml" | cut -c1-12)"
done
mkdir -p "$DEST" || gate_die "cannot create $DEST"
for pack in $PACKS; do mv "$tmp/$pack.yaml" "$DEST/$pack.yaml" || gate_die "cannot store $pack"; done
echo "$stamp" > "$DEST/STAMP" || gate_die "cannot write the stamp"
echo "QG-SAST-01 packs stored: $stamp"
