# Rocket Fuel

Rocket Fuel is the agent harness: a pinned build of [opencode](https://opencode.ai) plus the
configuration, instructions, permission rules and plugin that turn it into a careful design agent.

Fuel does not contain an agent loop of its own. opencode provides the loop, model calls, file tools,
approvals, sessions and the live event stream. Fuel decides **what the agent may do, what it is told,
and when it must stop**.

## What Fuel guarantees

- **No fake results.** The agent cannot write check results or runner state, and has no tool that sets a status.
  It can only ask the runner to run a job and read what comes back.
- **Edits stay inside the design folders.** `design/`, `tests/`, `workflows/` and `ip/` are editable;
  `results/`, `exports/`, `.rocket/`, `.opencode/`, `.git/`, PDK installs and anything outside the project are not,
  including through symlinks or `../` tricks.
- **A hard stop.** When the runner reports the repair-iteration limit, the session is locked: no more edits or runs,
  and the agent has to summarise and hand back to the user.
- **No shell, no web.** Shell commands, web fetch/search and subagents are denied.
- **An audit trail.** Every tool call and every block is appended to `.rocket/audit.jsonl` in the project.
- **Keys stay out of files.** The model key comes from the `MODEL_API_KEY` environment variable only.

## How it fits together

```text
              opencode (pinned 1.19.5)
   ┌──────────────────────────────────────────────┐
   │  agent: rocket-approval / rocket-auto         │
   │  prompt: harness/prompts/rocket-agent.md      │
   │  permissions: harness/opencode.json           │
   │  plugin: plugin/src (paths, limit, audit)     │
   └──────────┬───────────────────────┬───────────┘
              │ model API             │ MCP (stdio)
              ▼                       ▼
     Muse Spark 1.3 (default)   `rocket` tool server
     or any configured model    (mcp-stub/ for now)
```

Fuel's config is installed into each project's `.opencode/` folder, and opencode is started with that project
as its working directory.

## Quick start

Requirements: `node`/`npm`, `bun`, `uv`, `git`.

```bash
npm install                                   # installs the pinned opencode into node_modules/
cp .env.example .env                          # add MODEL_API_KEY (gitignored)

scripts/dev.sh "$(scripts/new-demo.sh)"       # fresh demo project + opencode with Fuel installed
```

Then ask: *"Bring this op-amp to spec."* The demo starts out failing its gain target, so you can watch
the agent run the job, read the failure, edit the design, rerun, and stop at the limit if it can't fix it.

Choosing a model:

| Model | `ROCKET_MODEL` | Needs | Use for |
|---|---|---|---|
| Muse Spark 1.3 | (default) `meta/muse-spark-1.3` | Meta key | real designs; prompts are not used for training |
| Muse Spark 1.3 Contributor | `meta/muse-spark-1.3-contributor` | Meta key | development and rehearsals on demo data: ~12–20× cheaper, but Meta may train on prompts and outputs; 150 requests/min |
| opencode free models | e.g. `opencode/glm-5.3-flash-free` | nothing | trying the loop with no key at all (not Muse) |

```bash
ROCKET_MODEL=meta/muse-spark-1.3-contributor scripts/dev.sh "$(scripts/new-demo.sh)"
```

Headless, the way an app embeds it:

```bash
scripts/dev.sh <project> serve --port 4097
```

## Agent profiles

| Action | `rocket-approval` (default) | `rocket-auto` |
|---|---|---|
| Read and search the project | allow | allow |
| Edit `design/`, `tests/`, `workflows/`, `ip/` | ask | allow |
| Edit `constraints.yaml` | ask | ask |
| Edit `results/`, `exports/`, `.rocket/`, `.opencode/`, `.git/` | deny | deny |
| Shell, web, subagents, outside the project | deny | deny |
| Run jobs, read results | allow | allow |
| Apply revision, register/instantiate IP, generate views | ask | allow |
| Export, propose a constraint change | ask | ask |

Same instructions for both; only the permissions differ.

## Configuration

| Setting | Where | Default |
|---|---|---|
| Model | `ROCKET_MODEL` env, or `model` in `harness/opencode.json` | `meta/muse-spark-1.3` |
| Model API key | `MODEL_API_KEY` env | none |
| Read-only PDK locations | `ROCKET_PDK_ROOTS` env (`:`-separated) | none |
| Repair-iteration limit | `agent.iteration_limit` in the project's `constraints.yaml` (read by the runner) | 3 |
| Agent instructions | `harness/prompts/rocket-agent.md` | |
| Providers | `provider` in `harness/opencode.json` (any OpenAI-compatible or local model) | Meta Model API |

Requirements for a project:
- It must be the root of its own git repo; opencode matches permission paths like `design/**` from the git root.
- opencode must be started with `PWD` set to the project; it reads its directory from `PWD`, not the process cwd.
- Give opencode its own data folders (`XDG_*` env). `scripts/dev.sh` uses `.opencode-home/` so the pinned
  1.x build never touches a global opencode v2 install, whose database it cannot open.

## Repository layout

```text
harness/
  opencode.json              providers, `rocket` MCP server, permissions, both agents
  prompts/rocket-agent.md    the agent's instructions
plugin/                      opencode plugin (TypeScript, Bun)
  src/policy.ts                path checks, limit detection (pure, unit-tested)
  src/index.ts                 hooks: block protected edits, lock at limit, attach session id, audit
mcp-stub/                    stand-in `rocket` tool server (Python) with a toy op-amp model
evals/
  run_scenarios.py           scripted sessions through real opencode with a fake model
  scenarios/*.json           one file per scenario
examples/opamp-demo/         starting project: under-designed op-amp, gain ~50 dB vs ≥ 60 dB target
scripts/
  dev.sh                     run pinned opencode on a project with Fuel installed
  new-demo.sh                copy the demo into its own git repo
  install-into-project.sh    write Fuel's config into <project>/.opencode/
docs/BOUNDARIES.md           the tool contract and launch contract Fuel expects
```

## The tool server

The agent's chip-design tools come from an MCP server named `rocket` (opencode exposes them as `rocket_<tool>`).
Until the real one is available, `mcp-stub/` provides:

| Tool | Does |
|---|---|
| `get_constraints` | the project's targets and required checks |
| `get_status` | state card: check statuses, iteration count and limit, changes tried |
| `list_job_kinds` | supported job kinds |
| `run_job` | run a job, evaluate checks, count iterations, refuse repeats of a failed design, report the limit |
| `get_check_results` | current check table |
| `ip_search` | IP search (returns nothing yet) |

Stub results are stamped `producer: "stub"` and are not real simulations. The full tool list and reply shapes
Fuel expects are in [docs/BOUNDARIES.md](docs/BOUNDARIES.md).

## Testing

```bash
(cd plugin && bun install && bun test)       # path rules, symlinks, patch parsing, limit detection
(cd mcp-stub && uv sync && uv run pytest)    # fail → fix → pass, repeated designs, iteration limit
python3 -I evals/run_scenarios.py            # scripted sessions through the real pinned opencode
```

`evals/run_scenarios.py` needs no key or network. It starts a fake OpenAI-compatible model that replays the
tool calls in a scenario file, runs opencode with Fuel's config, plugin and the stub, then checks the project:

| Scenario | Proves |
|---|---|
| `fail_fix_rerun` | FAIL → edit design → rerun → PASS in one counted iteration; the session id reaches `run_job` |
| `fake_pass_blocked` | writing `results/`, `.rocket/` (via `design/../`) or outside the project is blocked; the check stays FAIL |
| `iteration_limit` | after the runner reports the limit, the next edit is blocked and audited |

To add one, drop a JSON file in `evals/scenarios/` (`{project}` in arguments becomes the project path).
These test the harness, not the model's judgement.

## Recorded sessions

Real sessions can be recorded from opencode's event stream and replayed, for building the chat UI
without a live agent and as a fallback if the model API is down during a demo.

```bash
# record: fresh demo, one prompt, every event until the session is idle (--approve answers approvals "once")
ROCKET_MODEL=opencode/glm-5.3-flash-free python3 -I evals/record_session.py --approve \
    --out evals/recordings/opamp-approval-free.jsonl

# replay at real speed (or --speed 5) as an SSE stream on http://127.0.0.1:4199/event
python3 -I evals/replay_server.py evals/recordings/opamp-approval-free.jsonl
```

A recording is JSONL: a header line (model, agent, prompt, `"recording": "rocket-fuel/v1"`) followed by
`{"t_ms": ..., "event": {...}}` lines in opencode's own event format. Local paths are rewritten to `/project`.
The replay stream starts with a `rocket.replay` event; anything displaying it must show a REPLAY banner.

`evals/recordings/opamp-approval-free.jsonl` is a real 87-second session (free GLM model, stub runner,
approval profile): it reads the constraints, runs the baseline, and asks four times before editing the design.

## Why opencode 1.19.5

opencode 2.x is out, but its published plugin API has no tool-call hooks, which the protections above rely on.
Fuel pins `opencode-ai@1.19.5` (npm stable) in `package.json`; a global opencode install is not used.
