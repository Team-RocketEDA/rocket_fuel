
# Running checks (Rocket Engine)

Simulations run on the real engine. Its tools start with `engine_`:

- `engine_run_spice` runs ngspice. Give `sources` (netlist files in the project), `analyses` and `measurements` (`name` and `expr`). Do not give `min` or `max`: targets come from `constraints.yaml`, and the engine refuses them. A measurement name must match a metric in the constraints.
- It returns a queued acknowledgement with a `run_id`. Read the result with `engine_get_job_status` (verdict, measured values, margins) and search the log with `engine_get_logs`.
- `engine_get_check_results` shows the latest verdict per operation; `engine_list_job_kinds` shows what the engine can run.
- A verdict of NOT_RUN means the check did not run (for example a missing tool). Report it with its reason; never treat it as a pass or a fail, and never estimate the numbers yourself.

`rocket_get_status` does not count engine runs yet, so keep your own count of repair attempts and stop after the iteration limit in `constraints.yaml`.
