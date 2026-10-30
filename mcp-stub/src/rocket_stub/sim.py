"""Fake op-amp "simulator" and runner state for the stub.

Nothing here is real EDA. It exists so the agent loop (fail -> diagnose -> edit
-> rerun -> iteration limit) can be exercised before Rocket Engine is ready.
Every result is stamped producer="stub" and must never be shown as green.
"""

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


def design_hash(project: Path) -> str:
    h = hashlib.sha256()
    for path in sorted((project / "design").rglob("*")):
        if path.is_file():
            h.update(path.relative_to(project).as_posix().encode())
            h.update(path.read_bytes())
    return h.hexdigest()[:12]


def simulate(params: dict[str, float]) -> dict[str, float]:
    """Toy model: longer second-stage L raises gain and costs phase margin."""
    l2 = params.get("L2", 0.5)
    cc = params.get("CC", 1.0)
    return {
        "dc_gain_db": round(40.0 + 20.0 * l2, 2),
        "phase_margin_deg": round(70.0 - 10.0 * l2 + 5.0 * (cc - 1.0), 2),
        "ugbw_mhz": round(25.0 / cc, 2),
    }


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

    @classmethod
    def load(cls, project: Path) -> "RunnerState":
        path = project / STATE
        return cls(**json.loads(path.read_text())) if path.exists() else cls()

    def save(self, project: Path) -> None:
        path = project / STATE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, indent=2))
