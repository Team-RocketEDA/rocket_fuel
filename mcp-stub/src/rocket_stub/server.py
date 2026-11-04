"""Stub MCP server exposing a subset of the harness tool surface.

Tool names match harness/README.md section 7.2 in the PRD repo so the agent
prompt and permission rules don't change when Rocket Engine's real MCP bridge
replaces this. opencode prefixes them with the server name: rocket_run_job etc.
"""

import difflib
import os
import subprocess
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from rocket_stub import evidence, ip
from rocket_stub.sim import (
    NETLIST,
    RunnerState,
    changed_lines,
    design_files,
    design_hash,
    evaluate,
    fake_log,
    load_constraints,
    read_params,
    simulate,
)

mcp = MCPServer("rocket")
PROJECT = Path(os.environ.get("ROCKET_PROJECT_DIR", os.getcwd())).resolve()
STUB_NOTE = "STUB RESULT from rocket_fuel/mcp-stub. Not a real simulation; never display as verified."
LOGS = Path(".rocket/stub-logs")
EDITABLE = ("design/", "tests/", "workflows/", "ip/")


def iteration_limit() -> int:
    constraints = load_constraints(PROJECT)
    agent = constraints.get("agent", {})
    return int(agent.get("iteration_limit", os.environ.get("ROCKET_STUB_ITERATION_LIMIT", 3)))


@mcp.tool()
def get_constraints() -> dict:
    """Return the user's constraints and required checks. Read-only; you may not change them."""
    return load_constraints(PROJECT)


def engine_attached() -> bool:
    """Rocket Engine runs the checks (ROCKET_STUB_RUNNER=off): nothing here is simulated."""
    return os.environ.get("ROCKET_STUB_RUNNER", "on") == "off"


@mcp.tool()
def get_status() -> dict:
    """Compact state card: check statuses, repair iteration count and limit, changes already tried."""
    state = RunnerState.load(PROJECT)
    limit = iteration_limit()
    if engine_attached():
        return {
            "source": "Rocket Engine evidence in results/engine-runs, the same runs the IDE shows",
            "revision": evidence.revision(PROJECT),
            "checks": evidence.check_statuses(PROJECT, load_constraints(PROJECT)),
            "iteration_limit": limit,
            "repairs": "Each engine run you execute counts as one; the harness blocks runs and edits at the limit.",
            "changes_tried": state.ledger,
        }
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

    params = read_params(PROJECT)
    measured = simulate(params)
    state.run_count += 1
    run_id = f"stub-{state.run_count}"
    log_path = PROJECT / LOGS / f"{run_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(fake_log((PROJECT / NETLIST).read_text(), params, measured)) + "\n")
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
    # The ledger records what actually changed (from the files), not what the agent says it changed.
    files = design_files(PROJECT)
    changes = changed_lines(state.last_design, files) if state.last_design else []
    state.last_design = files
    state.ledger.append({"iteration": state.iteration, "design": current, "hypothesis": hypothesis, "changes": changes, "measured": measured})
    if failed:
        state.last_failed_hash = current
        state.failed_hashes.append(current)
    else:
        state.last_failed_hash = None
    state.runs[run_id] = {"kind": kind, "state": "completed", "design": current, "failing_required": failed, "session": rocket_session}
    state.save(PROJECT)

    return {
        "run_id": run_id,
        "iteration": state.iteration,
        "iterations_left": max(0, limit - state.iteration),
        "checks": results,
        "failing_required": failed,
        "changes_since_last_run": changes,
        "log_excerpt": [f"* stub ngspice: {k} = {v}" for k, v in measured.items()],
        "note": STUB_NOTE,
    }


@mcp.tool()
def get_check_results() -> dict:
    """Current check table from the runner. Read-only."""
    state = RunnerState.load(PROJECT)
    return {"checks": state.results, "current_design": design_hash(PROJECT), "note": STUB_NOTE}


@mcp.tool()
def get_job_status(run_id: str) -> dict:
    """State of a run: queued, running, completed, error or cancelled. Stub runs complete immediately."""
    run = RunnerState.load(PROJECT).runs.get(run_id)
    return {"run_id": run_id, **run} if run else {"error": "unknown_run", "message": f"no run {run_id!r}"}


@mcp.tool()
def get_logs(run_id: str, query: str = "", offset: int = 0, limit: int = 40) -> dict:
    """Search or page through a run's full log. With query, returns matching lines (case-insensitive) with line numbers."""
    path = PROJECT / LOGS / f"{run_id}.log"
    if not path.exists():
        return {"error": "unknown_run", "message": f"no log for {run_id!r}"}
    lines = path.read_text().splitlines()
    numbered = [(i + 1, line) for i, line in enumerate(lines)]
    if query:
        numbered = [(n, line) for n, line in numbered if query.lower() in line.lower()]
    limit = max(1, min(limit, 200))
    page = numbered[offset : offset + limit]
    return {
        "run_id": run_id,
        "total_lines": len(lines),
        "matched": len(numbered),
        "offset": offset,
        "lines": [f"{n}: {line}" for n, line in page],
        "more": offset + limit < len(numbered),
    }


@mcp.tool()
def propose_revision(file: str, old_text: str, new_text: str, hypothesis: str, checks: list[str]) -> dict:
    """Stage a targeted change for specific failing checks, with a one-sentence hypothesis.

    old_text must appear exactly once in file. Returns a revision id and diff; nothing changes until
    apply_revision. A change that recreates a design which already failed is rejected.
    """
    if not file.startswith(EDITABLE) or ".." in Path(file).parts:
        return {"error": "invalid_path", "message": f"revisions may only touch {', '.join(EDITABLE)}"}
    path = PROJECT / file
    if not path.is_file():
        return {"error": "invalid_path", "message": f"{file} does not exist"}
    if not hypothesis.strip() or not checks:
        return {"error": "invalid_arguments", "message": "give a hypothesis and the check ids this change targets"}
    before = path.read_text()
    if before.count(old_text) != 1:
        return {"error": "invalid_arguments", "message": f"old_text appears {before.count(old_text)} times in {file}; it must appear exactly once"}

    after = before.replace(old_text, new_text)
    state = RunnerState.load(PROJECT)
    proposed = design_hash(PROJECT, {file: after.encode()})
    if proposed in state.failed_hashes:
        earlier = next((e for e in state.ledger if e["design"] == proposed), None)
        return {"error": "duplicate_revision", "message": "This change recreates a design that already failed.", "earlier_result": earlier}

    state.revision_count += 1
    revision_id = f"rev-{state.revision_count}"
    state.staged[revision_id] = {"file": file, "before": before, "after": after, "hypothesis": hypothesis, "checks": checks}
    state.save(PROJECT)
    diff = difflib.unified_diff(before.splitlines(), after.splitlines(), f"a/{file}", f"b/{file}", lineterm="")
    return {"revision_id": revision_id, "file": file, "hypothesis": hypothesis, "checks": checks, "diff": "\n".join(diff)}


@mcp.tool()
def apply_revision(revision_id: str) -> dict:
    """Apply a staged revision and commit it. Fails if the file changed since it was proposed."""
    state = RunnerState.load(PROJECT)
    rev = state.staged.pop(revision_id, None)
    if rev is None:
        return {"error": "unknown_revision", "message": f"no staged revision {revision_id!r}"}
    path = PROJECT / rev["file"]
    if path.read_text() != rev["before"]:
        state.save(PROJECT)
        return {"error": "stale_revision", "message": f"{rev['file']} changed since {revision_id} was proposed; propose again"}
    path.write_text(rev["after"])
    state.save(PROJECT)
    return {"revision_id": revision_id, "file": rev["file"], "commit": _commit(f"{revision_id}: {rev['hypothesis']}", rev["file"])}


@mcp.tool()
def propose_constraint_change(check_id: str, new_value: float, reason: str) -> dict:
    """Ask the user to change a target. Nothing changes unless the user accepts it in the IDE."""
    checks = {c["id"]: c for c in load_constraints(PROJECT)["checks"]}
    if check_id not in checks:
        return {"error": "unknown_check", "message": f"no check {check_id!r}", "checks": sorted(checks)}
    state = RunnerState.load(PROJECT)
    proposal = {"check_id": check_id, "current": checks[check_id]["value"], "proposed": new_value, "reason": reason, "status": "pending_user"}
    state.constraint_proposals.append(proposal)
    state.save(PROJECT)
    return {**proposal, "message": "Proposed to the user. constraints.yaml is unchanged; do not continue as if it were accepted."}


@mcp.tool()
def ip_search(query: str, domain: str = "", pdk: str = "") -> list[dict]:
    """Search reusable IP blocks by function, domain and PDK. Returns id, version, summary and verification status."""
    return ip.search(ip.load(PROJECT), query, domain, pdk)


@mcp.tool()
def ip_get(block_id: str, version: str = "") -> dict:
    """Full record for one IP block: ports, parameters with bounds, views, PDKs and verification status."""
    matches = [b for b in ip.load(PROJECT) if b["id"] == block_id and (not version or b["version"] == version)]
    return matches[-1] if matches else {"error": "unknown_block", "message": f"no IP block {block_id!r}"}


@mcp.tool()
def ip_register(
    block_id: str,
    version: str,
    domain: str,
    summary: str,
    ports: list[dict],
    parameters: list[dict],
    pdks: list[str],
    views: dict[str, str],
    rocket_session: str = "",
) -> dict:
    """Register a reusable block in the project library (ip/manifest.yaml). It always starts UNVERIFIED.

    ports: [{name, kind: digital|analog|optical|supply|ground, direction: input|output|inout}]
    parameters: [{name, unit, min, max, default}]
    views: {"spice": "design/opamp.cir", ...} existing files under design/ or ip/
    """
    blocks = ip.load(PROJECT)
    block = {
        "id": block_id, "version": version, "domain": domain, "summary": summary,
        "ports": ports, "parameters": parameters, "pdks": pdks, "views": views,
        "status": "UNVERIFIED", "evidence": None,
        "origin": {"created_by": "agent", "session": rocket_session},
    }
    errors = ip.validate(PROJECT, block, blocks)
    if errors:
        return {"error": "invalid_block", "messages": errors}
    blocks.append(block)
    ip.save(PROJECT, blocks)
    commit = _commit(f"Register IP {block_id} {version}", str(ip.MANIFEST))
    return {"id": block_id, "version": version, "status": "UNVERIFIED", "commit": commit,
            "message": "Registered. Status stays UNVERIFIED until the runner records passing evidence."}


def _commit(message: str, *paths: str) -> str | None:
    """Stand-in for the project service, which owns every git write."""
    if not (PROJECT / ".git").exists():
        return None
    git = ["git", "-C", str(PROJECT), "-c", "user.name=rocketeda", "-c", "user.email=rocketeda@localhost"]
    subprocess.run([*git, "add", "--", *paths], check=True, capture_output=True)
    subprocess.run([*git, "commit", "-q", "-m", message, "--", *paths], check=True, capture_output=True)
    return subprocess.run([*git, "rev-parse", "--short", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


def _limit_reply(state: RunnerState, limit: int) -> dict:
    return {
        "error": "iteration_limit_reached",
        "message": "Repair iteration limit reached. Stop editing and running jobs; summarise the failures and ask the user.",
        "iteration_limit": limit,
        "failing": {cid: r for cid, r in state.results.items() if r["status"] != "PASS"},
        "changes_tried": state.ledger,
        "note": STUB_NOTE,
    }


# Simulation tools. With a real engine attached (ROCKET_STUB_RUNNER=off) they are withdrawn,
# so results only ever come from the engine; the workflow tools above stay.
RUNNER_TOOLS = ["list_job_kinds", "run_job", "get_job_status", "get_check_results", "get_logs"]


def main() -> None:
    if os.environ.get("ROCKET_STUB_RUNNER", "on") == "off":
        for name in RUNNER_TOOLS:
            mcp.remove_tool(name)
    mcp.run()
