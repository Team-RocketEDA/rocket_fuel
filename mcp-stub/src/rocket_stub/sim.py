"""Fake op-amp "simulator" and runner state for the stub.

Nothing here is real EDA. It exists so the agent loop (fail -> diagnose -> edit
-> rerun -> iteration limit) can be exercised before Rocket Engine is ready.
Every result is stamped producer="stub" and must never be shown as green.
"""

import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML

NETLIST = Path("design/opamp.cir")
STATE = Path(".rocket/stub-state.json")
PARAM_RE = re.compile(r"^\s*\.param\s+(\w+)\s*=\s*([0-9.]+)", re.IGNORECASE | re.MULTILINE)


def read_params(project: Path) -> dict[str, float]:
    text = (project / NETLIST).read_text()
    return {name.upper(): float(value) for name, value in PARAM_RE.findall(text)}


def design_hash(project: Path, overlay: dict[str, bytes] | None = None) -> str:
    """Hash of design/; overlay maps project-relative paths to proposed contents."""
    files = {p.relative_to(project).as_posix(): p.read_bytes() for p in (project / "design").rglob("*") if p.is_file()}
    files.update(overlay or {})
    h = hashlib.sha256()
    for rel in sorted(files):
        if rel.startswith("design/"):
            h.update(rel.encode())
            h.update(files[rel])
    return h.hexdigest()[:12]


def design_files(project: Path) -> dict[str, str]:
    return {p.relative_to(project).as_posix(): p.read_text() for p in sorted((project / "design").rglob("*")) if p.is_file()}


def changed_lines(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """What actually changed between two design snapshots, as +/- lines per file."""
    out = []
    for rel in sorted(before.keys() | after.keys()):
        old, new = before.get(rel, "").splitlines(), after.get(rel, "").splitlines()
        lines = [l for l in difflib.unified_diff(old, new, lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]
        out += [f"{rel}: {l}" for l in lines]
    return out


def simulate(params: dict[str, float]) -> dict[str, float]:
    """Toy model: longer second-stage L raises gain and costs phase margin."""
    l2 = params.get("L2", 0.5)
    cc = params.get("CC", 1.0)
    return {
        "dc_gain_db": round(40.0 + 20.0 * l2, 2),
        "phase_margin_deg": round(70.0 - 10.0 * l2 + 5.0 * (cc - 1.0), 2),
        "ugbw_mhz": round(25.0 / cc, 2),
    }


def fake_log(netlist: str, params: dict[str, float], measured: dict[str, float]) -> list[str]:
    """A long ngspice-looking log, so log paging and search can be exercised."""
    lines = ["******", "** ngspice-44 (stub) : Circuit level simulation program", "******", "Circuit: opamp testbench"]
    lines += [f"netlist: {line}" for line in netlist.splitlines()]
    lines += ["Doing analysis at TEMP = 27.000000 and TNOM = 27.000000", "No. of Data Rows : 401"]
    lines += [f"Reference value :  {i * 2.5e5:.5e}" for i in range(1, 121)]
    lines += ["Warning: vdd: no DC value, transient time 0 value used"] if params.get("L2", 0.5) > 1.5 else []
    lines += [f"{name:<20} = {value:.6e}" for name, value in measured.items()]
    lines += ["ngspice-44 done"]
    return lines


def load_constraints(project: Path) -> dict:
    return YAML(typ="safe").load((project / "constraints.yaml").read_text())


def evaluate(check: dict, measured: float) -> str:
    target = check["value"]
    ok = {">=": measured >= target, "<=": measured <= target, "==": measured == target}[check["comparison"]]
    return "PASS" if ok else "FAIL"


@dataclass
class RunnerState:
    iteration: int = 0
    limit_reached: bool = False
    last_failed_hash: str | None = None
    failed_hashes: list[str] = field(default_factory=list)
    ledger: list[dict] = field(default_factory=list)
    results: dict = field(default_factory=dict)
    run_count: int = 0
    runs: dict = field(default_factory=dict)
    staged: dict = field(default_factory=dict)
    revision_count: int = 0
    constraint_proposals: list[dict] = field(default_factory=list)
    last_design: dict = field(default_factory=dict)

    @classmethod
    def load(cls, project: Path) -> "RunnerState":
        path = project / STATE
        return cls(**json.loads(path.read_text())) if path.exists() else cls()

    def save(self, project: Path) -> None:
        path = project / STATE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, indent=2))
