# Rocket Fuel

The AI agent harness for **RocketEDA**: one of three repos.

| Repo | What |
|---|---|
| Rocket Engine | Python project tooling engine, runner, evidence, IP/PDK, and the `rocket` MCP server |
| Rocket IDE | React + Electron frontend; starts the engine and opencode, shows chat, approvals and checks |
| **Rocket Fuel** (this repo) | The agent: a pinned [opencode](https://opencode.ai) plus RocketEDA's config, prompt, permissions and plugin |

We don't write an agent loop. opencode provides the loop, model calls, file tools, approvals,
sessions and event stream. Fuel turns it into a chip-design agent that can't fake a PASS.
Design source: [`harness/README.md` in the PRD repo](https://github.com/Team-RocketEDA/PRD/blob/main/harness/README.md).
Who owns what across repos: [docs/BOUNDARIES.md](docs/BOUNDARIES.md).

**Model:** Meta Model API, Muse Spark 1.3, for the hackathon. Providers are config-only
(`harness/opencode.json`), so any other OpenAI-compatible or local model is one more entry.

## Layout

```text
harness/opencode.json        opencode config: Meta provider, rocket MCP server, permissions, two agents
harness/prompts/             system prompt for the RocketEDA agent
plugin/                      opencode plugin (TypeScript, Bun): protected paths, iteration lock,
                             session id on job calls, audit log → .rocket/audit.jsonl
mcp-stub/                    fake `rocket` MCP server (Python) with a toy op-amp, until Engine's bridge lands
examples/opamp-demo/         a deliberately failing op-amp project (gain ~50 dB, target ≥ 60 dB)
scripts/install-into-project.sh   installs Fuel config into a project's .opencode/ (what the IDE launcher does)
docs/BOUNDARIES.md           contracts with Engine and IDE, open questions
```

## Agent profiles

| | `rocket-approval` (default) | `rocket-auto` |
|---|---|---|
| Edit design/, tests/, workflows/, ip/ | ask | allow |
| Edit constraints.yaml | ask | ask |
| Edit results/, exports/, .rocket/, .opencode/, .git/ | deny | deny |
| Shell, web fetch/search, subagents, outside project | deny | deny |
| Rocket tools | allow; ask for apply/register/instantiate/views/export | allow; ask for export/constraint change |

## Getting started

Requirements: `node`/`npm`, `bun`, `uv`. opencode is pinned in `package.json` and installed locally.

```bash
npm install                                  # pinned opencode-ai 1.19.5 into node_modules
(cd plugin && bun install && bun test)       # plugin unit tests
(cd mcp-stub && uv sync && uv run pytest)    # stub runner: fail -> fix -> pass, duplicates, iteration limit

python3 -I evals/run_scenarios.py           # scripted sessions through real opencode (no key needed)

cp .env.example .env                         # put your Meta key in MODEL_API_KEY; .env is gitignored
scripts/dev.sh "$(scripts/new-demo.sh)"      # fresh demo repo + opencode TUI with Fuel installed
ROCKET_MODEL=opencode/glm-5.3-flash-free scripts/dev.sh "$(scripts/new-demo.sh)"   # free model, no Meta key
scripts/dev.sh <project> serve --port 4097   # headless, the way the IDE will run it
```

Then ask: *"Bring this op-amp to spec."* `scripts/new-demo.sh` recreates the demo from scratch each time.

- A project must be the root of its own git repo: opencode matches permission patterns like `design/**` from the git root.
- `scripts/dev.sh` uses a repo-local `.opencode-home/` so the pinned 1.x build doesn't clash with a global opencode install (v2 changed the database format).
- Stub results are stamped `producer: "stub"` and must never be shown as verified.

## Scripted sessions (`evals/`)

`evals/run_scenarios.py` runs the real pinned opencode with Fuel's config, plugin and the stub MCP, against a
fake model that replays the tool calls in `evals/scenarios/*.json`. It tests the harness, not the model:

| Scenario | Proves |
|---|---|
| `fail_fix_rerun` | FAIL → edit design → rerun → PASS (stub) in one counted iteration; session id reaches `run_job` |
| `fake_pass_blocked` | writing `results/`, `.rocket/` (via `design/../`) or outside the project is blocked; the check stays FAIL |
| `iteration_limit` | once the runner reports the limit, the plugin blocks further edits and audits it |

Add a scenario by dropping a JSON file in `evals/scenarios/`; `{project}` in arguments is replaced with the project path.
