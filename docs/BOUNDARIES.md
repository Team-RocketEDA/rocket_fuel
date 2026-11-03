# Rocket Fuel ↔ Rocket Engine ↔ Rocket IDE

Who owns what, and what each repo needs from the others. Based on the PRD repo's
`harness/README.md`, `tech-stack.md` and `plans/rocketeda-project-blueprint.md`.

## Ownership

| Piece | Repo | Notes |
|---|---|---|
| opencode (pinned build), its config, agent profiles, permissions | **Fuel** | `harness/opencode.json` |
| System prompt / agent instructions | **Fuel** | `harness/prompts/rocket-agent.md` (PRD harness §11) |
| opencode plugin: protected paths, iteration lock, session ids, audit log | **Fuel** | `plugin/` |
| Meta Model API provider setup (Muse Spark 1.3) and BYOK provider list | **Fuel** | config only; keys never in files |
| Evals / recorded sessions / replay fixtures | **Fuel** | `evals/` |
| Stub of the Engine's MCP tools, for development only | **Fuel** | `mcp-stub/`, deleted once Engine's bridge works |
| Project tooling engine, runner, evaluator, evidence, IP registry, PDK catalog | **Engine** | Python (blueprint B1–B8) |
| **MCP bridge** (`rocket` server with the tools below) | **Engine** | Blueprint B9 puts it in the tooling repo: it's a thin binding to engine ops |
| Iteration counter (source of truth) | **Engine** | Runner counts; Fuel's plugin only locks the session when told |
| Electron main: spawns opencode + engine, keychain, passes `MODEL_API_KEY` | **IDE** | Fuel provides the exact launch command and env (below) |
| Chat UI (assistant-ui), approvals dialog, iteration banner, check table | **IDE** | Talks to opencode's HTTP API + event stream |

## Contract 1: MCP tool surface (Engine provides, Fuel consumes)

The prompt and permission rules reference these names. opencode exposes them as
`rocket_<tool>`, so the MCP server **must be named `rocket`**.

Implemented in the stub today: `get_constraints`, `get_status`, `list_job_kinds`,
`get_job_status`, `run_job`, `get_check_results`, `get_logs`, `propose_revision`, `apply_revision`,
`propose_constraint_change`, `ip_search`, `ip_get`, `ip_register`. Their signatures and replies in
`mcp-stub/src/rocket_stub/server.py` are the reference for the Engine's server.

Still to agree (PRD harness §7.2): `ip_instantiate`, `generate_views`, `check_view_sync`,
`check_connection`, `export_project`, `pdk_list`, `pdk_get_cells`, `cancel_job`, `parse_report`,
`list_artifacts`.

Reply shapes Fuel relies on:
- `run_job` → `{run_id, iteration, iterations_left, checks: {id: {status, measured, target, margin, required, producer}}, failing_required, log_excerpt}`
- limit reached → `{"error": "iteration_limit_reached", failing, changes_tried}` (the plugin matches this string)
- duplicate change → `{"error": "duplicate_revision", ...}` (from `run_job` and `propose_revision`)
- `run_job` returns `changes_since_last_run` and `get_status.changes_tried[].changes`: the actual diff lines,
  computed from the files. The prompt tells the agent to report these, because in a live run it described a
  change it had intended but not made
- `ip_register` never accepts a status or evidence; blocks start `UNVERIFIED`, and `ip/manifest.yaml` is
  denied to the agent's edit tools
- statuses are exactly `PASS | FAIL | NOT_RUN | UNSUPPORTED`
- no tool may set a status; logs come back compact (≤ ~4k tokens, first error first)

## Contract 2: launching the harness (Fuel defines, IDE implements)

1. Install Fuel config into the chip project: `.opencode/opencode.json`, `.opencode/prompts/`, `.opencode/plugin/rocketeda.ts` (see `scripts/install-into-project.sh`).
2. Start the pinned opencode (`opencode-ai@1.19.5`) with cwd = project: `opencode serve --hostname 127.0.0.1 --port <random>`.
3. Env:
   - `OPENCODE_SERVER_PASSWORD`: random per launch (without it the server warns it is unsecured)
   - `MODEL_API_KEY`: from the OS keychain, never written to disk
   - `ROCKET_FUEL_HOME`, `ROCKET_PDK_ROOTS` (`:`-separated, read-only for the agent)
   - `XDG_DATA_HOME`/`XDG_CONFIG_HOME`/`XDG_STATE_HOME`/`XDG_CACHE_HOME` under the app's own data folder, so it never shares state with a user's own opencode install (1.x refuses to start on a v2 database)
   - `PWD` = the project path: opencode reads its directory from `PWD`, not the process cwd (`child_process.spawn({cwd})` alone is not enough)
   - `ROCKET_MODEL` (optional) overrides the default `meta/muse-spark-1.3` when installing the config
4. The UI uses opencode's session, prompt, event-stream and permission-reply endpoints. `scripts/dev.sh <project> serve --port 4097` reproduces this locally.

For UI work before the agent is ready: `evals/replay_server.py <recording>` serves a recorded session on
`GET /event` in opencode's own event format (first event `rocket.replay` → show a REPLAY banner).
Approval requests arrive as `permission.asked` (`properties.id`, `permission`, `patterns`) and are answered
with `POST /permission/<id>/reply {"reply": "once" | "always" | "reject"}`.

Things learned by running it (see `evals/`):
- **The project must be the root of its own git repo.** Otherwise opencode matches `design/**` against the path from `/` and every design edit is denied.
- **opencode npm-installs `@opencode-ai/plugin` into `.opencode/` on first open of a project.** That needs network; the offline installer must pre-seed it.
- MCP results reach plugins in a different field from built-in tool output; Fuel's plugin searches the whole result.

## Engine status (2026-11-03)

Rocket Engine's MCP server (`rocket_engine.adapters.mcp.server`, branch `GREEN-the-tests`) is connectable; Fuel attaches
it with `ROCKET_ENGINE_HOME` (see README). An operation such as `run_spice` now executes when called and returns the
verdict, and the engine writes its evidence then. `run_job(request_id)` fetches that run, or executes a deferred one.
What Fuel and the IDE rely on:
- `--project`/`--project-dir` binding: project_id and expected_revision filled in, sources confined to the project
- run_spice targets and measurement formulas from `constraints.yaml` (caller min/max/expr refused)
- `get_job_status`/`get_check_results`/`get_logs`/`list_job_kinds` wired, measurements kept on PASS, argument schemas
- evidence per run in `results/engine-runs/<run_id>.json` (verdict, source commit, log); `--call` for the IDE's own Run checks

Missing from `GREEN-the-tests`, only on the conflicted `fuel-mcp-fixes` (PR #3): the waveform datasets
(`<run_id>-ac.raw`) that the IDE plots.

Fuel counts each executed run once per `run_id`, on any `engine_run_*` call, against `agent.iteration_limit`; NOT_RUN and
UNSUPPORTED verdicts cost nothing. At the limit only a fetch of an already counted run is allowed. The agent's engine tools are an allowlist (`scripts/install-into-project.sh`): runs and reads,
with `generate_views` on ask. The engine's editor verbs, document CRUD, `rewind` and `write_settings` stay hidden because
they would bypass edit approvals, and so does any operation the engine adds later until someone reviews it.

Still open on the engine side: one engine shared by the IDE and MCP (each MCP process has its own engine), which store
is the source of truth for project files (engine CRUD documents or the project's git tree), and the workflow tools
Fuel's stub still provides (constraints, status card, revisions, IP).

## Open questions to settle with the team

1. **Session id.** Harness doc: the plugin attaches the opencode session id to job calls. Tooling doc (`tooling-operations.yaml`): `session_id` is server-owned. Proposal: the plugin sends `rocket_session`; the Engine treats it as a hint for the repair budget only and derives real identity from the broker credential.
2. **Iteration limit source.** Proposal: `constraints.yaml → agent.iteration_limit`, enforced by the runner.
3. **opencode version.** The research assumed 1.x; 2.0.28 is out (curl channel) but its published plugin API has no tool-call hooks. Fuel pins `opencode-ai@1.19.5` (npm stable), tested: config, agents, `rocket` MCP and plugin all load. Revisit v2 after the hackathon.
4. **Hosted gateway** (PRD harness §5.8): who owns it? Not obviously Fuel, Engine or IDE.
