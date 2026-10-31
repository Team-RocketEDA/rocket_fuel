
# Running checks (Rocket Engine)

Simulations run on the real engine. Its tools start with `engine_`:

- `engine_run_spice` runs ngspice. Give `sources` (netlist files in the project), `analyses` and `measurements` (each a `name` matching a metric in `constraints.yaml`). Do not give `min`, `max` or, when the constraints define one, `expr`: the engine takes targets and measurement formulas from `constraints.yaml` and refuses the agent's own.
- When `constraints.yaml` has a `simulation` block, use its `sources` and `analyses`.
- Runs are two steps. `engine_run_spice` only admits the job and returns an acknowledgement with a `request_id`; then call `engine_run_job` with that `request_id` to run it. Its result has the verdict, measured values and margins, and the `run_id` of the run.
- Search a run's log with `engine_get_logs` (by `run_id`). `engine_get_check_results` shows the latest verdict per operation; `engine_list_job_kinds` shows what the engine can run.
- A verdict of NOT_RUN means the check did not run (for example a missing tool). Report it with its reason; never treat it as a pass or a fail, and never estimate the numbers yourself.

Each `engine_run_job` counts as one repair attempt. `rocket_get_status` does not count engine runs yet, so keep your own count and stop after the iteration limit in `constraints.yaml`; the harness blocks further runs and edits once it is reached.
