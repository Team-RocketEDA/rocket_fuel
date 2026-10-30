#!/usr/bin/env bash
# Run the pinned opencode on a chip project with Rocket Fuel installed.
# Usage: scripts/dev.sh <project-dir> [opencode args...]   e.g. scripts/dev.sh "$(scripts/new-demo.sh)"
#        scripts/dev.sh <project-dir> serve --port 4097   (headless, what the IDE launcher does)
# Set ROCKET_MODEL to use another model, e.g. ROCKET_MODEL=opencode/glm-5.3-flash-free (free, no key).
set -euo pipefail

FUEL_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${1:?usage: dev.sh <project-dir> [opencode args...]}"
shift
PROJECT="$(cd "$PROJECT" && pwd)"

if [[ "$(git -C "$PROJECT" rev-parse --show-toplevel 2>/dev/null)" != "$PROJECT" ]]; then
  echo "$PROJECT must be the root of its own git repo, or edit permissions won't match." >&2
  echo "For the demo: scripts/dev.sh \"\$(scripts/new-demo.sh)\"" >&2
  exit 1
fi

# .env first (the model choice is baked in at install time); a ROCKET_MODEL set on the command line wins.
CLI_MODEL="${ROCKET_MODEL:-}"
if [[ -f "$FUEL_HOME/.env" ]]; then set -a; source "$FUEL_HOME/.env"; set +a; fi
[[ -n "$CLI_MODEL" ]] && export ROCKET_MODEL="$CLI_MODEL"

"$FUEL_HOME/scripts/install-into-project.sh" "$PROJECT" >/dev/null

# Own data/config dirs so the pinned 1.x build never shares a database with a global opencode install.
STATE="$FUEL_HOME/.opencode-home"
export XDG_DATA_HOME="$STATE/data" XDG_CONFIG_HOME="$STATE/config" XDG_STATE_HOME="$STATE/state" XDG_CACHE_HOME="$STATE/cache"
export ROCKET_FUEL_HOME="$FUEL_HOME"

# opencode takes its project directory from PWD.
cd "$PROJECT"
export PWD="$PROJECT"
exec "$FUEL_HOME/node_modules/.bin/opencode" "$@"
