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
# Only Meta models run: ROCKET_MODEL picks one of them (default meta/muse-spark-1.3), and the config only
# enables the Meta Model API provider. ROCKET_META_BASE_URL sends the calls through a relay instead of
# straight to https://api.meta.ai/v1, e.g. RocketIDE's call log (scripts/meta-relay.py).
MODEL="${ROCKET_MODEL:-meta/muse-spark-1.3}"
if [[ "$MODEL" != meta/* ]]; then
  echo "ROCKET_MODEL=$MODEL is not a Meta model. Use meta/muse-spark-1.3 (or another meta/... model)." >&2
  exit 2
fi
BASE_URL="${ROCKET_META_BASE_URL:-https://api.meta.ai/v1}"
sed -e "s#{env:ROCKET_FUEL_HOME}#$FUEL_HOME#g" \
    -e "s#\"model\": \"meta/muse-spark-1.3\"#\"model\": \"$MODEL\"#" \
    -e "s#\"small_model\": \"meta/muse-spark-1.3\"#\"small_model\": \"$MODEL\"#" \
    -e "s#\"baseURL\": \"https://api.meta.ai/v1\"#\"baseURL\": \"$BASE_URL\"#" \
    "$FUEL_HOME/harness/opencode.json" > "$DEST/opencode.json"

# ROCKET_ENGINE_HOME=<rocket-engine checkout> attaches the real engine: its MCP server provides the
# simulation tools (engine_*), the stub keeps only the workflow tools, and targets come from constraints.yaml.
# ROCKET_ENGINE_URL=<running engine> attaches the engine RocketIDE already runs (its scripts/engine-host.py)
# instead of starting one, so the agent and the IDE share one engine and see each other's runs.
if [[ -n "${ROCKET_ENGINE_HOME:-}" || -n "${ROCKET_ENGINE_URL:-}" ]]; then
  ENGINE_HOME="$( [[ -n "${ROCKET_ENGINE_HOME:-}" ]] && cd "$ROCKET_ENGINE_HOME" && pwd || true)"
  python3 -I - "$DEST/opencode.json" "$ENGINE_HOME" "$PROJECT" "${ROCKET_ENGINE_URL:-}" <<'PY'
import json, sys, urllib.parse
path, engine, project, url = sys.argv[1:5]
name = project.rstrip("/").split("/")[-1]
config = json.load(open(path))
config["mcp"]["rocket"].setdefault("environment", {})["ROCKET_STUB_RUNNER"] = "off"
if url:
    config["mcp"]["engine"] = {
        "type": "remote",
        "url": f"{url.rstrip('/')}/projects/{urllib.parse.quote(name)}/mcp",
        "enabled": True,
        "oauth": False,
        # A run answers when the simulation ends; opencode's default is 5 s.
        "timeout": 600000,
    }
else:
    config["mcp"]["engine"] = {
        "type": "local",
        "command": ["uv", "run", "--quiet", "--project", engine, "python", "-m", "rocket_engine.adapters.mcp.server",
                    "--project", name, "--project-dir", project],
        "enabled": True,
    }
# An allowlist, so an operation the engine adds later stays hidden until someone reviews it. Everything else
# (python_execute, document CRUD, editor verbs, rewind, settings) would change the project without the approval
# and diff the edit tools give. Later rules win, so the deny comes first.
permission = config["permission"]
permission["engine_*"] = "deny"
for pattern in ("engine_run_*", "engine_get_*", "engine_list_*", "engine_cancel_job",
                "engine_api_help", "engine_api_info", "engine_api_search", "engine_check_capability",
                "engine_components_of", "engine_connection_graph", "engine_describe_testbench", "engine_entities_with",
                "engine_erc_check", "engine_instances_on_sheet", "engine_net_occurrences", "engine_plan_checks",
                "engine_read_doc", "engine_read_entity_revision", "engine_read_settings", "engine_resolve_pin"):
    permission[pattern] = "allow"
permission["engine_generate_views"] = "ask"
# Reading the engine's manuals one call at a time is where a session's minutes went. The prompt says what's needed.
for pattern in ("engine_api_help", "engine_api_info", "engine_api_search", "engine_read_doc", "engine_list_docs"):
    permission[pattern] = "deny"
json.dump(config, open(path, "w"), indent=2)
PY
  for prompt in rocket-agent rocket-tutor rocket-reviewer; do
    cat "$FUEL_HOME/harness/prompts/runner-engine.md" >> "$DEST/prompts/$prompt.md"
  done
fi

# opencode 1.x auto-loads every file in .opencode/plugin/.
mkdir -p "$DEST/plugin"
echo "export { RocketPlugin } from \"$FUEL_HOME/plugin/src/index.ts\"" > "$DEST/plugin/rocketeda.ts"
grep -qxF ".opencode/" "$PROJECT/.gitignore" 2>/dev/null || echo ".opencode/" >> "$PROJECT/.gitignore"
grep -qxF ".rocket/" "$PROJECT/.gitignore" 2>/dev/null || echo ".rocket/" >> "$PROJECT/.gitignore"

echo "Rocket Fuel installed into $DEST"
