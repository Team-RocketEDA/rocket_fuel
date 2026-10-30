"""Stub MCP server exposing a subset of the harness tool surface.

Tool names match harness/README.md section 7.2 in the PRD repo so the agent
prompt and permission rules don't change when Rocket Engine's real MCP bridge
replaces this. opencode prefixes them with the server name: rocket_run_job etc.
"""

import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from rocket_stub.sim import RunnerState, design_hash, evaluate, load_constraints, read_params, simulate

mcp = MCPServer("rocket")
PROJECT = Path(os.environ.get("ROCKET_PROJECT_DIR", os.getcwd())).resolve()
STUB_NOTE = "STUB RESULT from rocket_fuel/mcp-stub. Not a real simulation; never display as verified."


def iteration_limit() -> int:
    constraints = load_constraints(PROJECT)
    agent = constraints.get("agent", {})
    return int(agent.get("iteration_limit", os.environ.get("ROCKET_STUB_ITERATION_LIMIT", 3)))


@mcp.tool()
def get_constraints() -> dict:
    """Return the user's constraints and required checks. Read-only; you may not change them."""
    return load_constraints(PROJECT)


@mcp.tool()
def get_status() -> dict:
    """Compact state card: check statuses, repair iteration count and limit, changes already tried."""
    state = RunnerState.load(PROJECT)
    limit = iteration_limit()
    return {
        "iteration": state.iteration,
        "iteration_limit": limit,
        "iterations_left": max(0, limit - state.iteration),
        "limit_reached": state.limit_reached,
        "current_design": design_hash(PROJECT),
        "checks": {cid: r["status"] for cid, r in state.results.items()},
        "changes_tried": state.ledger,
        "note": STUB_NOTE,
    }


@mcp.tool()
def list_job_kinds() -> list[dict]:
    """Job kinds the runner supports and the checks each produces."""
    return [{"kind": "spice_sim", "produces": ["dc_gain", "phase_margin", "ugbw"], "note": STUB_NOTE}]


@mcp.tool()
def run_job(kind: str, hypothesis: str = "", rocket_session: str = "") -> dict:
    """Run a registered job (currently only kind="spice_sim") on the current design and evaluate checks.

    Pass a one-sentence hypothesis when rerunning after a change.
    """
    if kind != "spice_sim":
        return {"error": "unsupported_operation", "message": f"unknown job kind {kind!r}", "allowed": ["spice_sim"]}

    state = RunnerState.load(PROJECT)
    limit = iteration_limit()
    current = design_hash(PROJECT)

    if state.limit_reached:
        return _limit_reply(state, limit)
    if current in state.failed_hashes:
        return {
            "error": "duplicate_revision",
            "message": "This exact design already ran and failed. Try a different change.",
            "design": current,
        }

    is_repair = state.last_failed_hash is not None and current != state.last_failed_hash
    if is_repair:
        if state.iteration >= limit:
            state.limit_reached = True
            state.save(PROJECT)
            return _limit_reply(state, limit)
        state.iteration += 1

    measured = simulate(read_params(PROJECT))
    state.run_count += 1
    checks = load_constraints(PROJECT)["checks"]
    results = {}
    for check in checks:
        value = measured[check["metric"]]
        status = evaluate(check, value)
        results[check["id"]] = {
            "status": status,
            "measured": value,
            "target": f"{check['comparison']} {check['value']} {check['unit']}",
            "margin": round(value - check["value"], 2),
            "required": check.get("required", True),
            "design": current,
            "producer": "stub",
        }
    state.results = results

    failed = [cid for cid, r in results.items() if r["status"] != "PASS" and r["required"]]
    state.ledger.append({"iteration": state.iteration, "design": current, "hypothesis": hypothesis, "measured": measured})
    if failed:
        state.last_failed_hash = current
        state.failed_hashes.append(current)
    else:
        state.last_failed_hash = None
    state.save(PROJECT)

    return {
        "run_id": f"stub-{state.run_count}",
        "iteration": state.iteration,
        "iterations_left": max(0, limit - state.iteration),
        "checks": results,
        "failing_required": failed,
        "log_excerpt": [f"* stub ngspice: {k} = {v}" for k, v in measured.items()],
        "note": STUB_NOTE,
    }


@mcp.tool()
def get_check_results() -> dict:
    """Current check table from the runner. Read-only."""
    state = RunnerState.load(PROJECT)
    return {"checks": state.results, "current_design": design_hash(PROJECT), "note": STUB_NOTE}


@mcp.tool()
def ip_search(query: str, domain: str = "", pdk: str = "") -> list[dict]:
    """Search reusable IP blocks by function, domain, PDK and port types."""
    return []


def _limit_reply(state: RunnerState, limit: int) -> dict:
    return {
        "error": "iteration_limit_reached",
        "message": "Repair iteration limit reached. Stop editing and running jobs; summarise the failures and ask the user.",
        "iteration_limit": limit,
        "failing": {cid: r for cid, r in state.results.items() if r["status"] != "PASS"},
        "changes_tried": state.ledger,
        "note": STUB_NOTE,
    }


def main() -> None:
    mcp.run()
