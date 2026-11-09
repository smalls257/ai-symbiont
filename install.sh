#!/bin/sh
# Install ai-symbiont without cloning the repository.
#
#   curl -fsSL https://raw.githubusercontent.com/smalls257/ai-symbiont-plugin/main/install.sh | sh -s -- \
#     [--nightly] [--ref <git ref>] [--harness <id>|auto|all|none]
#
# This script knows only `uv` and the package. Which harness plugins exist, and the commands that
# register them, live in `symbiont setup` (read from the harness registry), so a new harness
# needs no change here. Running it again upgrades the package (`uv tool install --force`).
set -eu

REPO_URL="https://github.com/smalls257/ai-symbiont-plugin"
UV_INSTALL_HINT="curl -LsSf https://astral.sh/uv/install.sh | sh"
ref="main"
extras=""
harness="auto"

usage() {
    echo "usage: install.sh [--nightly] [--ref <git ref>] [--harness <id>|auto|all|none]" >&2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --nightly) extras="[nightly]" ;;  # torch is large, so the trainer is opt-in
        --ref | --harness)
            if [ $# -lt 2 ]; then
                echo "install.sh: $1 needs a value" >&2
                usage
                exit 2
            fi
            if [ "$1" = "--ref" ]; then ref="$2"; else harness="$2"; fi
            shift
            ;;
        -h | --help) usage; exit 0 ;;
        *)
            echo "install.sh: unknown option $1" >&2
            usage
            exit 2
            ;;
    esac
    shift
done

if ! command -v uv >/dev/null 2>&1; then
    # Not piped on the user's behalf: running a second remote script is the user's call.
    echo "install.sh: uv is not installed. Install it with the official command, then run this again:" >&2
    echo "  $UV_INSTALL_HINT" >&2
    exit 1
fi

uv tool install --force "ai-symbiont${extras} @ git+${REPO_URL}@${ref}"
uv tool update-shell
"$(uv tool dir --bin)/symbiont" setup --harness "$harness"
