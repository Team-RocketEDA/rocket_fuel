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

# ROCKET_ENGINE_HOME=<rocket-engine checkout> attaches the real engine: its MCP server provides the
# simulation tools (engine_*), the stub keeps only the workflow tools, and targets come from constraints.yaml.
if [[ -n "${ROCKET_ENGINE_HOME:-}" ]]; then
  ENGINE_HOME="$(cd "$ROCKET_ENGINE_HOME" && pwd)"
  python3 -I - "$DEST/opencode.json" "$ENGINE_HOME" "$PROJECT" <<'PY'
import json, sys
path, engine, project = sys.argv[1:4]
config = json.load(open(path))
config["mcp"]["rocket"].setdefault("environment", {})["ROCKET_STUB_RUNNER"] = "off"
config["mcp"]["engine"] = {
    "type": "local",
    "command": ["uv", "run", "--quiet", "--project", engine, "python", "-m", "rocket_engine.adapters.mcp.server",
                "--project", project.rstrip("/").split("/")[-1], "--project-dir", project],
    "enabled": True,
}
config["permission"]["engine_*"] = "allow"
config["permission"]["engine_python_execute"] = "deny"  # no approval flow over MCP yet
# The engine's document CRUD would change design files without the approval and diff the edit tools give.
for tool in ("write_doc", "delete_doc", "apply_mutations", "create_project"):
    config["permission"][f"engine_{tool}"] = "deny"
json.dump(config, open(path, "w"), indent=2)
PY
  cat "$FUEL_HOME/harness/prompts/runner-engine.md" >> "$DEST/prompts/rocket-agent.md"
fi

# opencode 1.x auto-loads every file in .opencode/plugin/.
mkdir -p "$DEST/plugin"
echo "export { RocketPlugin } from \"$FUEL_HOME/plugin/src/index.ts\"" > "$DEST/plugin/rocketeda.ts"
grep -qxF ".opencode/" "$PROJECT/.gitignore" 2>/dev/null || echo ".opencode/" >> "$PROJECT/.gitignore"
grep -qxF ".rocket/" "$PROJECT/.gitignore" 2>/dev/null || echo ".rocket/" >> "$PROJECT/.gitignore"

echo "Rocket Fuel installed into $DEST"
