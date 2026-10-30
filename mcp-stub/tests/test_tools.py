import shutil
import subprocess
from pathlib import Path

import pytest

from rocket_stub import server

DEMO = Path(__file__).resolve().parents[2] / "examples" / "opamp-demo"
OPAMP_PORTS = [
    {"name": "inp", "kind": "analog", "direction": "input"},
    {"name": "inn", "kind": "analog", "direction": "input"},
    {"name": "out", "kind": "analog", "direction": "output"},
    {"name": "vdd", "kind": "supply", "direction": "inout"},
    {"name": "vss", "kind": "ground", "direction": "inout"},
]
OPAMP_PARAMS = [{"name": "CC", "unit": "pF", "min": 0.5, "max": 10, "default": 2}]


@pytest.fixture
def project(tmp_path, monkeypatch):
    dest = tmp_path / "proj"
    shutil.copytree(DEMO, dest, ignore=shutil.ignore_patterns(".rocket", ".opencode"))
    subprocess.run(["git", "init", "-q", dest], check=True)
    subprocess.run(["git", "-C", dest, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    monkeypatch.setattr(server, "PROJECT", dest)
    return dest


def register(**overrides):
    args = dict(block_id="rocket.analog.opamp_2stage", version="0.1.0", domain="analog",
                summary="Two-stage Miller op-amp, SKY130 1.8 V", ports=OPAMP_PORTS, parameters=OPAMP_PARAMS,
                pdks=["sky130A"], views={"spice": "design/opamp.cir"})
    return server.ip_register(**{**args, **overrides})


def test_logs_page_and_search(project):
    run = server.run_job("spice_sim")
    page = server.get_logs(run["run_id"], limit=10)
    assert page["total_lines"] > 100 and len(page["lines"]) == 10 and page["more"]
    hit = server.get_logs(run["run_id"], query="dc_gain_db")
    assert hit["matched"] == 1 and "5.000000e+01" in hit["lines"][0]
    assert server.get_job_status(run["run_id"])["state"] == "completed"


def test_propose_then_apply_commits(project):
    rev = server.propose_revision("design/opamp.cir", ".param L2=0.5", ".param L2=1.0", "longer L2 raises gain", ["opamp.dc_gain"])
    assert "+.param L2=1.0" in rev["diff"]
    assert ".param L2=0.5" in (project / "design/opamp.cir").read_text()

    applied = server.apply_revision(rev["revision_id"])
    assert applied["commit"]
    assert ".param L2=1.0" in (project / "design/opamp.cir").read_text()


def test_proposing_a_design_that_already_failed_is_rejected(project):
    server.run_job("spice_sim")
    rev = server.apply_revision(server.propose_revision("design/opamp.cir", ".param L2=0.5", ".param L2=0.6", "try", ["opamp.dc_gain"])["revision_id"])
    assert rev["commit"]
    again = server.propose_revision("design/opamp.cir", ".param L2=0.6", ".param L2=0.5", "back to start", ["opamp.dc_gain"])
    assert again["error"] == "duplicate_revision"
    assert again["earlier_result"]["measured"]["dc_gain_db"] == 50.0


def test_ledger_records_actual_changes_not_claims(project):
    server.run_job("spice_sim")
    netlist = project / "design/opamp.cir"
    netlist.write_text(netlist.read_text().replace("W=4 L=0.5", "W=4 L=1.0"))
    run = server.run_job("spice_sim", hypothesis="raise first-stage L and CC to 1.5 pF")
    assert run["changes_since_last_run"] == [
        "design/opamp.cir: -XM1 n1 inn tail vss sky130_fd_pr__nfet_01v8 W=4 L=0.5",
        "design/opamp.cir: -XM2 n2 inp tail vss sky130_fd_pr__nfet_01v8 W=4 L=0.5",
        "design/opamp.cir: +XM1 n1 inn tail vss sky130_fd_pr__nfet_01v8 W=4 L=1.0",
        "design/opamp.cir: +XM2 n2 inp tail vss sky130_fd_pr__nfet_01v8 W=4 L=1.0",
    ]
    assert server.get_status()["changes_tried"][-1]["changes"] == run["changes_since_last_run"]


def test_stale_revision_is_refused(project):
    rev = server.propose_revision("design/opamp.cir", ".param CC=1.0", ".param CC=2.0", "more compensation", ["opamp.phase_margin"])
    netlist = project / "design/opamp.cir"
    netlist.write_text(netlist.read_text() + "* edited meanwhile\n")
    assert server.apply_revision(rev["revision_id"])["error"] == "stale_revision"


@pytest.mark.parametrize("file", ["results/x.yaml", "../outside.cir", "constraints.yaml"])
def test_revisions_only_touch_editable_folders(project, file):
    assert server.propose_revision(file, "a", "b", "h", ["opamp.dc_gain"])["error"] == "invalid_path"


def test_constraint_change_is_only_a_proposal(project):
    before = (project / "constraints.yaml").read_text()
    reply = server.propose_constraint_change("opamp.phase_margin", 55, "60 deg infeasible with gain >= 60 dB in this topology")
    assert reply["status"] == "pending_user"
    assert (project / "constraints.yaml").read_text() == before


def test_registered_block_is_unverified_and_findable(project):
    reply = register(rocket_session="ses_123")
    assert reply["status"] == "UNVERIFIED" and reply["commit"]
    assert server.ip_search("two-stage op-amp")[0]["id"] == "rocket.analog.opamp_2stage"
    assert server.ip_search("op-amp", domain="photonic") == []
    block = server.ip_get("rocket.analog.opamp_2stage")
    assert block["status"] == "UNVERIFIED" and block["evidence"] is None
    assert block["origin"]["session"] == "ses_123"


@pytest.mark.parametrize("overrides", [
    {"views": {"spice": "design/missing.cir"}},
    {"views": {"spice": "results/opamp.cir"}},
    {"ports": [{"name": "x", "kind": "magic", "direction": "input"}]},
    {"parameters": [{"name": "CC", "min": 1, "max": 2, "default": 5}]},
    {"block_id": "Not An Id"},
])
def test_invalid_blocks_are_rejected(project, overrides):
    assert register(**overrides)["error"] == "invalid_block"


def test_same_version_cannot_be_registered_twice(project):
    register()
    assert register()["error"] == "invalid_block"
    assert register(version="0.2.0")["status"] == "UNVERIFIED"
