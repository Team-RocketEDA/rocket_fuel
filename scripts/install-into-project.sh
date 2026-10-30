#!/usr/bin/env bash
# Install Rocket Fuel's opencode config into a chip project's .opencode/ folder.
# The Electron launcher (Rocket IDE) does the same thing before starting opencode.
# Usage: scripts/install-into-project.sh <project-dir> [--engine <mcp command...>]
set -euo pipefail

FUEL_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="$(cd "${1:?usage: install-into-project.sh <project-dir>}" && pwd)"
DEST="$PROJECT/.opencode"

mkdir -p "$DEST"
rm -rf "$DEST/prompts"
cp -r "$FUEL_HOME/harness/prompts" "$DEST/prompts"
# ROCKET_MODEL overrides the default model (meta/muse-spark-1.3), e.g. a free opencode model
# while no Meta key is available: ROCKET_MODEL=opencode/glm-5.3-flash-free
MODEL="${ROCKET_MODEL:-meta/muse-spark-1.3}"
sed -e "s#{env:ROCKET_FUEL_HOME}#$FUEL_HOME#g" \
    -e "s#\"model\": \"meta/muse-spark-1.3\"#\"model\": \"$MODEL\"#" \
    "$FUEL_HOME/harness/opencode.json" > "$DEST/opencode.json"

# opencode 1.x auto-loads every file in .opencode/plugin/.
mkdir -p "$DEST/plugin"
echo "export { RocketPlugin } from \"$FUEL_HOME/plugin/src/index.ts\"" > "$DEST/plugin/rocketeda.ts"
grep -qxF ".opencode/" "$PROJECT/.gitignore" 2>/dev/null || echo ".opencode/" >> "$PROJECT/.gitignore"
grep -qxF ".rocket/" "$PROJECT/.gitignore" 2>/dev/null || echo ".rocket/" >> "$PROJECT/.gitignore"

echo "Rocket Fuel installed into $DEST"
