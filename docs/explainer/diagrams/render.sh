#!/usr/bin/env bash
# Renders every .mmd here to an .svg with mermaid-cli, then strips the web font that mermaid-cli
# embeds (about 300 KB per diagram) because the explainer uses system fonts and the repo
# refuses files over 1 MB. Run from any directory; needs node (npx).
set -euo pipefail
cd "$(dirname "$0")"
for f in *.mmd; do
  n="${f%.mmd}"
  npx -y @mermaid-js/mermaid-cli -i "$f" -o "$n.svg" -b transparent -I "d-$n" -q
  python3 - "$n.svg" <<'PY'
import re, sys
path = sys.argv[1]
svg = open(path).read()
svg = re.sub(r"/\*.*?\*/", "", svg, flags=re.S)                       # font license comments
svg = re.sub(r"@font-face\s*\{[^}]*\}", "", svg, flags=re.S)           # embedded woff2 fonts
svg = svg.replace('"Recursive Variable"', "system-ui, sans-serif")
open(path, "w").write(svg)
PY
done
ls -la *.svg
