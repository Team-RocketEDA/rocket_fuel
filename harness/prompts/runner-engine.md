
# Running checks (Rocket Engine)

Simulations run on the real engine. Its tools start with `engine_`:

- `engine_run_spice` runs ngspice. Give `sources` (netlist files in the project), `analyses` and `measurements` (each a `name` matching a metric in `constraints.yaml`). Do not give `min`, `max` or, when the constraints define one, `expr`: the engine takes targets and measurement formulas from `constraints.yaml` and refuses the agent's own.
- When `constraints.yaml` has a `simulation` block, use its `sources` and `analyses`.
- `engine_run_spice` runs the simulation and returns the verdict, measured values and margins, with a `request_id` and `run_id`. Then call `engine_run_job` once with that `request_id`: this records the run's evidence for the IDE and costs no attempt. If a result has no verdict yet, the same call runs the job and returns it.
- Search a run's log with `engine_get_logs` (by `run_id`). `engine_get_check_results` shows the latest verdict per operation; `engine_list_job_kinds` shows what the engine can run.
- A verdict of NOT_RUN means the check did not run (for example a missing tool). Report it with its reason; never treat it as a pass or a fail, and never estimate the numbers yourself.

Each run that executes counts as one repair attempt; a NOT_RUN verdict does not. `rocket_get_status` does not count engine runs yet, so keep your own count and stop after the iteration limit in `constraints.yaml`. Once it is reached the harness blocks further runs and edits, but you can still record the last run with `engine_run_job`.
