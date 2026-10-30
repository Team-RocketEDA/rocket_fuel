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

cp .env.example .env                         # put your Meta key in MODEL_API_KEY; .env is gitignored
scripts/dev.sh examples/opamp-demo           # opens the opencode TUI on the demo with Fuel installed
scripts/dev.sh examples/opamp-demo serve --port 4097   # headless, the way the IDE will run it
```

`scripts/dev.sh` uses a repo-local `.opencode-home/` so the pinned 1.x build doesn't clash
with a globally installed opencode (v2 changed the database format).

Then ask: *"Bring this op-amp to spec."* Reset the demo with
`git checkout examples/opamp-demo/design && rm -rf examples/opamp-demo/.rocket`.

Stub results are stamped `producer: "stub"` and must never be shown as verified.
