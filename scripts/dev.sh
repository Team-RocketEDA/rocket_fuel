#!/usr/bin/env bash
# Run the pinned opencode on a chip project with Rocket Fuel installed.
# Usage: scripts/dev.sh <project-dir> [opencode args...]   e.g. scripts/dev.sh "$(scripts/new-demo.sh)"
#        scripts/dev.sh <project-dir> serve --port 4097   (headless, what the IDE launcher does)
# ROCKET_MODEL picks any provider/model the pinned opencode understands (default meta/muse-spark-1.3).
# The saved provider configuration (scripts/model_config.py) wins over .env; an explicitly exported value
# wins over both. Keys are read from the credentials file or the provider's usual environment variable.
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

# Which model settings were exported by the caller. Anything already exported wins over .env and over the
# saved configuration, so a key or model passed by the IDE or a container is not blanked by .env.
# Only the choice of model is overridden by the saved configuration. Where that configuration and the call log
# live is a path setting, so a value from .env or the caller is kept.
MODEL_VARS=(ROCKET_MODEL ROCKET_PROVIDER ROCKET_MODEL_ID ROCKET_PROVIDER_TYPE ROCKET_PROVIDER_NAME
            ROCKET_BASE_URL ROCKET_SMALL_MODEL ROCKET_TUTOR_MODEL ROCKET_REVIEWER_MODEL)
PRESET=()
for name in "${MODEL_VARS[@]}"; do
  [[ -n "${!name+x}" ]] && PRESET+=("$name")
done

# .env first; anything already exported wins, so a key passed to a container or a launcher isn't blanked by
# an empty line in .env.
if [[ -f "$FUEL_HOME/.env" ]]; then
  EXPORTED="$(export -p)"
  set -a; source "$FUEL_HOME/.env"; set +a
  eval "$EXPORTED"
fi

# A saved configuration is authoritative over .env, so switching provider in the app takes effect without the
# stale ROCKET_MODEL line in .env winning. Values the caller exported before .env still win (see above).
if [[ -f "$(python3 -I "$FUEL_HOME/scripts/model_config.py" path)" ]]; then
  for name in "${MODEL_VARS[@]}"; do
    if [[ ! " ${PRESET[*]} " == *" $name "* ]]; then unset "$name"; fi
  done
fi
# Keep the activity log with the checkout, which is where RocketIDE's terminal and app look for it.
export ROCKET_MODEL_CALL_LOG="${ROCKET_MODEL_CALL_LOG:-$(cd "$FUEL_HOME/.." && pwd)/logs/model-calls.jsonl}"
eval "$(python3 -I "$FUEL_HOME/scripts/model_config.py" shell --with-key)"

"$FUEL_HOME/scripts/install-into-project.sh" "$PROJECT" >/dev/null

# Own data/config dirs so the pinned 1.x build never shares a database with a global opencode install.
STATE="$FUEL_HOME/.opencode-home"
export XDG_DATA_HOME="$STATE/data" XDG_CONFIG_HOME="$STATE/config" XDG_STATE_HOME="$STATE/state" XDG_CACHE_HOME="$STATE/cache"
export ROCKET_FUEL_HOME="$FUEL_HOME"

# Only what Fuel installs: not skills and prompts from whatever else is on this machine, which slow every call.
export OPENCODE_DISABLE_EXTERNAL_SKILLS=1 OPENCODE_DISABLE_CLAUDE_CODE=1

# opencode takes its project directory from PWD.
cd "$PROJECT"
export PWD="$PROJECT"
exec "$FUEL_HOME/node_modules/.bin/opencode" "$@"
