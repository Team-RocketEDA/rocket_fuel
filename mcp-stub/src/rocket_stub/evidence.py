"""Check status from the real engine's evidence, for when Rocket Engine is attached.

The engine records every finished run in results/engine-runs/<run_id>.json (verdict, measurements, source
commit). This reads the latest one per check the same way the IDE does (UIUX src/api.ts checkRows), so the
agent and the person see the same statuses.
"""

import json
import subprocess
from pathlib import Path

FOLDER = Path("results/engine-runs")


def _records(project: Path) -> list[dict]:
    records = []
    for path in (project / FOLDER).glob("*.json"):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        # Solvers also write scratch .json here; only engine records carry a run id and a verdict.
        if isinstance(record, dict) and record.get("run_id") and isinstance(record.get("verdict"), dict):
            records.append(record)
    return sorted(records, key=lambda r: r.get("finished_at") or "", reverse=True)


def revision(project: Path) -> str | None:
    found = subprocess.run(["git", "-C", str(project), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True)
    return found.stdout.strip() or None if found.returncode == 0 else None


def check_statuses(project: Path, constraints: dict) -> dict:
    """{check id: {status, run_id, ...}} from the latest engine run that speaks for each check."""
    records = _records(project)
    head = revision(project)
    statuses = {}
    for check in constraints.get("checks") or []:
        metric = check.get("metric")
        # A run with no measurements (an HDL testbench, an optical run) gives one verdict for the whole run.
        latest = next((r for r in records
                       if r["verdict"].get("status") == "NOT_RUN"
                       or not r["verdict"].get("measurements")
                       or any(m.get("name") == metric for m in r["verdict"]["measurements"])), None)
        if latest is None:
            statuses[check["id"]] = {"status": "NOT_RUN_YET"}
            continue
        verdict = latest["verdict"]
        entry = {
            "run_id": latest["run_id"],
            "operation": latest.get("operation"),
            "finished_at": latest.get("finished_at"),
            # From an older commit, or from uncommitted design changes: rerun before relying on it.
            "stale": (head is not None and not (latest.get("source_commit") or "").startswith(head))
                     or bool(latest.get("source_dirty")),
        }
        measurement = next((m for m in verdict.get("measurements") or [] if m.get("name") == metric), None)
        if verdict.get("status") in ("NOT_RUN", "UNSUPPORTED") or measurement is None:
            entry["status"] = verdict.get("status")
            if verdict.get("reason"):
                entry["reason"] = verdict["reason"]
        else:
            entry["status"] = "PASS" if measurement.get("status") == "pass" else "FAIL"
            for key in ("value", "unit", "margin"):
                if key in measurement:
                    entry[key] = measurement[key]
        statuses[check["id"]] = entry
    return statuses
