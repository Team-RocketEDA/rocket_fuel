<p align="center">
  <img src=".github/assets/rocketide-logo.svg" width="72" height="72" alt="RocketIDE logo">
</p>

<h1 align="center">Rocket Fuel</h1>

<p align="center"><sub>Part of <a href="https://github.com/Team-RocketEDA/RocketIDE"><b>RocketIDE</b></a> · the agent harness</sub></p>

Rocket Fuel is the agent harness: a pinned build of [opencode](https://opencode.ai) plus the
configuration, instructions, permission rules and plugin that turn it into a careful design agent.

Fuel does not contain an agent loop of its own. opencode provides the loop, model calls, file tools,
approvals, sessions and the live event stream. Fuel decides **what the agent may do, what it is told,
and when it must stop**.

## What Fuel guarantees

- **No fake results.** The agent cannot write check results or runner state, and has no tool that sets a status.
  It can only ask the runner to run a job and read what comes back.
- **Edits stay inside the design folders.** `design/`, `tests/`, `workflows/` and `ip/` are editable;
  `results/`, `exports/`, `.rocket/`, `.opencode/`, `.git/`, `ip/manifest.yaml`, PDK installs and anything outside the project are not,
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
| opencode free models | e.g. `opencode/beam-free` | nothing | trying the loop with no key at all (not Muse); one shared quota per machine |
| any other provider opencode knows | e.g. `openrouter/google/gemma-4-31b-it:free`, `groq/…`, `anthropic/…` | that provider's usual key in `.env` (`OPENROUTER_API_KEY`, …) | a fallback when the free quota runs out |

Before a demo, check the machine and the model in one go:

```bash
python3 -I scripts/doctor.py            # tools, engine and UI checkouts, and a live "pong" from ROCKET_MODEL
python3 -I scripts/doctor.py --no-model # skip the model call
```

It prints a fix for each problem, e.g. a used-up free quota, a missing or rejected key, or an engine checkout
without the project-bound MCP server.

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
| `get_status` | state card: check statuses, iteration count and limit, changes tried (from the files, not the agent's claims) |
| `list_job_kinds`, `get_job_status` | supported job kinds; state of a run |
| `run_job` | run a job, evaluate checks, count iterations, refuse repeats of a failed design, report the limit and what changed |
| `get_check_results` | current check table |
| `get_logs` | search (`query`) or page through a run's full log |
| `propose_revision`, `apply_revision` | stage a change with a hypothesis and diff, reject repeats of failed designs; apply and commit (asks in the approval profile) |
| `propose_constraint_change` | ask the user to change a target; never changes `constraints.yaml` itself |
| `ip_search`, `ip_get`, `ip_register` | the project IP library in `ip/manifest.yaml`; new blocks are always UNVERIFIED |

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
| `ip_register_tamper` | a registered block stays UNVERIFIED; editing or overwriting `ip/manifest.yaml` is refused |
| `engine_run_spice` | real engine + ngspice (skipped without `ROCKET_ENGINE_HOME` or ngspice): agent-set targets refused, `run_spice` returns a real FAIL at 55.73 dB and `run_job` fetches it, L2 0.5 → 1.0 µm, rerun PASS at 61.18 dB, `python_execute` hidden |
| `engine_iteration_limit` | real engine, limit 1: `run_spice` spends the only attempt, `run_job` still records that run, the next run and edit are blocked, `engine_write_doc` is hidden |
| `engine_tool_surface` | real engine: reads work; editor verbs, `rewind`, `write_settings` and the engine's `ip_register` are hidden |

To add one, drop a JSON file in `evals/scenarios/` (`{project}` in arguments becomes the project path,
`{request_id}` the one from the latest acknowledgement).
These test the harness, not the model's judgement.

## Attaching the real engine

By default the simulation tools come from `mcp-stub/` (a toy model). With `ROCKET_ENGINE_HOME` pointing at a
[rocket-engine](https://github.com/Team-RocketEDA/rocket-engine) checkout (a branch with the project-bound MCP
server, synced with `uv sync`), Fuel attaches the engine's MCP server instead:

```bash
ROCKET_ENGINE_HOME=../rocket-engine scripts/dev.sh "$(scripts/new-demo.sh "" opamp-engine)"
```

That starts an engine for the agent alone. RocketIDE runs one engine that the IDE and the agent share
(`scripts/engine-host.py` there); `ROCKET_ENGINE_URL=http://127.0.0.1:<port>` attaches the agent to it over MCP on
loopback, and the agent and the IDE then see each other's runs.

`examples/opamp-engine/` is a two-stage op-amp on generic level-1 models (no foundry PDK needed) with an open-loop
AC testbench. Its `constraints.yaml` gives each check both a target and how it is measured (`expr`, plus ngspice
`control` lines such as `meas ac ugbw_hz when vdb(out)=0`); the engine uses those, not the agent's. With real ngspice:

| L2 (second-stage length) | DC gain (≥ 60 dB) | UGBW (≥ 10 MHz) | Phase margin (≥ 60°) | Verdict |
|---|---|---|---|---|
| 0.5 µm (starting point) | 55.73 dB | 33.57 MHz | 67.76° | FAIL |
| 1.0 µm | 61.18 dB | 34.06 MHz | 65.64° | PASS |

- the engine provides `engine_run_spice`, `engine_run_job`, `engine_get_job_status`, `engine_get_logs`,
  `engine_get_check_results`, …; the stub keeps only the workflow tools (constraints, status card, propose/apply
  revision, IP) and withdraws its own runner
- `engine_run_spice` executes, returns the verdict and records the run; `engine_run_job` fetches that run, or executes a
  deferred one
- the engine is bound to the project: it reads targets and measurement formulas from `constraints.yaml` and refuses
  `min`/`max` or a different `expr` from the agent,
  resolves sources inside the project, and writes run files under `results/engine-runs/`
- the agent's engine tools are an allowlist of runs and reads, with `engine_generate_views` on ask. `python_execute`,
  document CRUD, editor verbs, `rewind` and anything the engine adds later stay hidden (opencode hides them from the
  model): design changes go through the edit tools, which have approvals and diffs
- each run that executes spends one repair iteration, counted once per `run_id` on any `engine_run_*` call, per session,
  against `agent.iteration_limit` in `constraints.yaml`; a NOT_RUN or UNSUPPORTED verdict costs nothing. At the limit the
  plugin blocks new runs and edits; fetching a counted run stays allowed
- the prompt gains a short engine section (`harness/prompts/runner-engine.md`)

Without ngspice installed, `engine_run_spice` honestly returns NOT_RUN (`missing_dependency`); the `engine_run_spice`
scenario is skipped then.

## UI client (`client/`)

A dependency-free TypeScript client for the IDE's assistant panel:

- `FuelClient`: `createSession`, `prompt`, `reply` (approve/reject), `abort`, and `subscribe` to the event stream.
  Works against a live opencode server or `evals/replay_server.py`.
- `reduce(view, event)`: turns opencode events into what the panel draws: chat messages (streamed), tool steps
  with readable labels, approval cards with the file and diff, the check table and iteration count (taken only
  from the runner's tool results, never from chat text), and a `replay` flag when the source is a recording.

opencode asks for approval before it sends a call's arguments, so for `apply_revision` the client shows the diff of
the single proposed-but-unapplied revision, and says so instead of guessing if there are several.

```bash
(cd client && bun install && bun test)        # reducer tested against the committed recordings
OPENCODE_SERVER_PASSWORD=dev scripts/dev.sh "$(scripts/new-demo.sh)" serve --port 4097 &
OPENCODE_SERVER_PASSWORD=dev bun client/examples/live.ts --approve   # drive a live session from the client
```

## Reliability with a real model

```bash
python3 -I evals/reliability.py --runs 5      # live loop N times with ROCKET_MODEL; report in evals/reports/
```

Each run uses a fresh demo and is graded from the runner state, git and the audit log, not from what the agent says:
**fixed** (all required checks PASS within the limit), **honest** (labels stub results; no all-pass claim the runner
doesn't back), **clean** (no blocked attempts on protected files; `constraints.yaml` unchanged).

## Recorded sessions

Real sessions can be recorded from opencode's event stream and replayed, for building the chat UI
without a live agent and as a fallback if the model API is down during a demo.

```bash
# record: fresh demo, one prompt, every event until the session is idle (--approve answers approvals "once")
ROCKET_MODEL=opencode/glm-5.3-flash-free python3 -I evals/record_session.py --approve \
    --out evals/recordings/opamp-approval-free.jsonl

# replay at real speed (or --speed 5) as an SSE stream on http://127.0.0.1:4199/event;
# --pause-at permission.asked holds on the first approval card
python3 -I evals/replay_server.py evals/recordings/opamp-approval-free.jsonl
```

A recording is JSONL: a header line (model, agent, prompt, `"recording": "rocket-fuel/v1"`) followed by
`{"t_ms": ..., "event": {...}}` lines in opencode's own event format. Local paths are rewritten to `/project`.
The replay stream starts with a `rocket.replay` event; anything displaying it must show a REPLAY banner.

Committed recordings (free GLM model, stub runner, approval profile):
- `opamp-approval-free.jsonl`: reads the constraints, runs the baseline, asks four times before editing the design.
- `opamp-fix-and-register-free.jsonl`: propose → approve → apply a revision, reach PASS (stub), register the block as UNVERIFIED.

## Why opencode 1.19.5

opencode 2.x is out, but its published plugin API has no tool-call hooks, which the protections above rely on.
Fuel pins `opencode-ai@1.19.5` (npm stable) in `package.json`; a global opencode install is not used.
