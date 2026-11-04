
# Running checks (Rocket Engine)

Simulations run on the real engine. Its tools start with `engine_`:

- `engine_run_spice` runs ngspice. Give `sources` (a list of netlist files in the project), `analyses` (a list of analysis lines) and `measurements` (a list of objects, each with a `name` matching a metric in `constraints.yaml`). Do not give `min`, `max` or, when the constraints define one, `expr`: the engine takes targets and measurement formulas from `constraints.yaml` and refuses the agent's own.
- When `constraints.yaml` has a `simulation` block, use its `sources` and `analyses`.
- `engine_run_spice` runs the simulation and returns the verdict, measured values and margins, with a `request_id` and `run_id`, and records the run for the IDE. Only if a result has no verdict yet, call `engine_run_job` with that `request_id` to run it.
- Search a run's log with `engine_get_logs` (by `run_id`). `engine_get_check_results` shows the latest verdict per operation; `engine_list_job_kinds` shows what the engine can run.
- A verdict of NOT_RUN means the check did not run (for example a missing tool). Report it with its reason; never treat it as a pass or a fail, and never estimate the numbers yourself.

`rocket_get_status` shows each check's latest engine result (the same runs the IDE shows, marked `stale` when they came from an older commit or uncommitted changes) and the changes already tried. These are real engine results, not simulated ones.

Each run that executes counts as one repair attempt; a NOT_RUN verdict does not. `rocket_get_status` doesn't count this session's runs, so keep your own count and stop after the iteration limit in `constraints.yaml`. Once it is reached the harness blocks further runs and edits.
