#!/usr/bin/env bash
# Run the pinned opencode on a chip project with Rocket Fuel installed.
# Usage: scripts/dev.sh <project-dir> [opencode args...]   e.g. scripts/dev.sh examples/opamp-demo
#        scripts/dev.sh examples/opamp-demo serve --port 4097   (headless, what the IDE launcher does)
set -euo pipefail

FUEL_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${1:?usage: dev.sh <project-dir> [opencode args...]}"
shift

"$FUEL_HOME/scripts/install-into-project.sh" "$PROJECT" >/dev/null

# Own data/config dirs so the pinned 1.x build never shares a database with a global opencode install.
STATE="$FUEL_HOME/.opencode-home"
export XDG_DATA_HOME="$STATE/data" XDG_CONFIG_HOME="$STATE/config" XDG_STATE_HOME="$STATE/state" XDG_CACHE_HOME="$STATE/cache"
export ROCKET_FUEL_HOME="$FUEL_HOME"
[[ -f "$FUEL_HOME/.env" ]] && set -a && source "$FUEL_HOME/.env" && set +a

cd "$PROJECT"
exec "$FUEL_HOME/node_modules/.bin/opencode" "$@"
