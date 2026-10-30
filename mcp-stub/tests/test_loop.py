import re
import shutil
from pathlib import Path

import pytest

from rocket_stub import server

DEMO = Path(__file__).resolve().parents[2] / "examples" / "opamp-demo"


@pytest.fixture
def project(tmp_path, monkeypatch):
    dest = tmp_path / "proj"
    shutil.copytree(DEMO, dest, ignore=shutil.ignore_patterns(".rocket", ".opencode"))
    monkeypatch.setattr(server, "PROJECT", dest)
    return dest


def set_param(project: Path, name: str, value: float) -> None:
    netlist = project / "design" / "opamp.cir"
    text = re.sub(rf"(\.param {name}=)[0-9.]+", rf"\g<1>{value}", netlist.read_text())
    netlist.write_text(text)


def test_fail_fix_rerun(project):
    first = server.run_job("spice_sim")
    assert first["checks"]["opamp.dc_gain"]["status"] == "FAIL"
    assert first["iteration"] == 0

    set_param(project, "L2", 1.0)
    second = server.run_job("spice_sim", hypothesis="longer L2 raises second-stage gain")
    assert second["checks"]["opamp.dc_gain"]["status"] == "PASS"
    assert second["iteration"] == 1
    assert all(r["producer"] == "stub" for r in second["checks"].values())


def test_rerunning_a_failed_design_is_refused(project):
    server.run_job("spice_sim")
    again = server.run_job("spice_sim")
    assert again["error"] == "duplicate_revision"


def test_iteration_limit_stops_the_loop(project):
    server.run_job("spice_sim")
    for l2 in (0.6, 0.7, 0.8):
        set_param(project, "L2", l2)
        assert "checks" in server.run_job("spice_sim")
    set_param(project, "L2", 0.9)
    stopped = server.run_job("spice_sim")
    assert stopped["error"] == "iteration_limit_reached"
    assert server.get_status()["limit_reached"] is True
