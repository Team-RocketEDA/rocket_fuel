"""Scripted harness sessions: real opencode + Fuel config/plugin + stub MCP, with a fake model.

The fake model is an OpenAI-compatible server that replays the tool calls listed in a
scenario file, so these runs test the harness (permissions, plugin, MCP wiring, iteration
limit) without a Meta key or network. They say nothing about how well Muse Spark behaves.

Usage: python3 -I evals/run_scenarios.py [scenario-name ...]
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FUEL_HOME = Path(__file__).resolve().parents[1]
SCENARIOS = FUEL_HOME / "evals" / "scenarios"
OPENCODE = FUEL_HOME / "node_modules" / ".bin" / "opencode"
TIMEOUT_S = 180


class FakeModel(BaseHTTPRequestHandler):
    """Answers chat completions with the next scripted step.

    The step index is the number of tool results already in the conversation, so each
    assistant turn advances the script by one. Requests without tools (titles, summaries)
    get a plain text reply.
    """

    steps: list[dict] = []
    project: str = ""
    requests: list[dict] = []

    def log_message(self, *args):
        pass

    def _read_body(self) -> bytes:
        if self.headers.get("Content-Length"):
            return self.rfile.read(int(self.headers["Content-Length"]))
        data = b""
        while (size := int(self.rfile.readline().strip() or b"0", 16)) > 0:
            data += self.rfile.read(size)
            self.rfile.readline()
        self.rfile.readline()
        return data

    def do_POST(self):
        body = json.loads(self._read_body())
        type(self).requests.append(body)
        if not body.get("tools"):
            step = {"text": "RocketEDA session"}
        else:
            done = sum(1 for m in body["messages"] if m.get("role") == "tool")
            step = self.steps[done] if done < len(self.steps) else {"text": "Script finished."}
        chunks = self._chunks(step, done if body.get("tools") else 0)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")

    def _chunks(self, step: dict, index: int) -> list[dict]:
        def chunk(delta, finish=None):
            return {"id": f"fake-{index}", "object": "chat.completion.chunk", "model": "scripted",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

        if "text" in step:
            return [chunk({"role": "assistant", "content": step["text"]}), chunk({}, "stop")]
        args = json.dumps(step["args"]).replace("{project}", self.project)
        call = {"index": 0, "id": f"call_{index}", "type": "function",
                "function": {"name": step["tool"], "arguments": args}}
        return [chunk({"role": "assistant", "tool_calls": [call]}), chunk({}, "tool_calls")]


def prepare_project(scenario: dict, port: int) -> Path:
    project = Path(tempfile.mkdtemp(prefix=f"rocket-eval-{scenario['name']}-"))
    shutil.rmtree(project)
    example = FUEL_HOME / "examples" / scenario.get("example", "opamp-demo")
    shutil.copytree(example, project, ignore=shutil.ignore_patterns(".opencode", ".rocket"))
    (project / "results").mkdir()

    if "iteration_limit" in scenario:
        constraints = project / "constraints.yaml"
        text = constraints.read_text().replace("iteration_limit: 3", f"iteration_limit: {scenario['iteration_limit']}")
        constraints.write_text(text)

    # Projects are git repos (the project service owns git). Without one, opencode matches edit
    # permission patterns against the path from / and design/** never matches.
    subprocess.run(["git", "init", "-q", project], check=True)
    # Only engine scenarios get the real engine, even if ROCKET_ENGINE_HOME is exported.
    env = dict(os.environ)
    if not scenario.get("engine"):
        env.pop("ROCKET_ENGINE_HOME", None)
    subprocess.run([FUEL_HOME / "scripts" / "install-into-project.sh", project], check=True, stdout=subprocess.DEVNULL, env=env)
    config_path = project / ".opencode" / "opencode.json"
    config = json.loads(config_path.read_text())
    config["provider"]["fake"] = {
        "npm": "@ai-sdk/openai-compatible",
        "options": {"baseURL": f"http://127.0.0.1:{port}/v1", "apiKey": "fake"},
        "models": {"scripted": {"name": "scripted", "limit": {"context": 100000, "output": 4096}}},
    }
    config["model"] = "fake/scripted"
    for agent in ("rocket-approval", "rocket-auto"):
        config["agent"][agent]["model"] = "fake/scripted"
    config_path.write_text(json.dumps(config, indent=2))
    return project


def run_opencode(project: Path, scenario: dict) -> subprocess.CompletedProcess:
    state = FUEL_HOME / ".opencode-home"
    env = {
        **os.environ,
        "XDG_DATA_HOME": str(state / "data"), "XDG_CONFIG_HOME": str(state / "config"),
        "XDG_STATE_HOME": str(state / "state"), "XDG_CACHE_HOME": str(state / "cache"),
        "ROCKET_FUEL_HOME": str(FUEL_HOME),
        # opencode takes its project directory from PWD, which cwd= alone doesn't update.
        "PWD": str(project),
    }
    env.pop("MODEL_API_KEY", None)
    cmd = [str(OPENCODE), "run", "--agent", scenario.get("agent", "rocket-auto"), "--model", "fake/scripted",
           "--title", scenario["name"], "--format", "json", scenario["prompt"]]
    # opencode run appends piped stdin to the prompt, so give it none.
    return subprocess.run(cmd, cwd=project, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT_S)


def tool_results(requests: list[dict]) -> list[str]:
    """What each scripted tool call returned, in order, from the model's last request."""
    with_tools = [r for r in requests if r.get("tools")]
    if not with_tools:
        return []
    return [json.dumps(m.get("content")) for m in with_tools[-1]["messages"] if m.get("role") == "tool"]


def check(project: Path, expect: dict, results: list[str] | None = None) -> list[str]:
    failures = []
    for item in expect.get("tool_results", []):
        step = item["step"]
        got = results[step] if results and step < len(results) else ""
        if "contains" in item and item["contains"] not in got:
            failures.append(f"tool step {step} result lacks {item['contains']!r}: {got[:160]}")
        if "lacks" in item and item["lacks"] in got:
            failures.append(f"tool step {step} result contains {item['lacks']!r}: {got[:160]}")
    for rel, needle in expect.get("file_contains", {}).items():
        text = (project / rel).read_text() if (project / rel).exists() else ""
        if needle not in text:
            failures.append(f"{rel} does not contain {needle!r}")
    for rel, needle in expect.get("file_lacks", {}).items():
        if (project / rel).exists() and needle in (project / rel).read_text():
            failures.append(f"{rel} contains {needle!r}")
    for rel in expect.get("file_absent", []):
        if (project / rel).exists():
            failures.append(f"{rel} exists but should not")

    state_file = project / ".rocket" / "stub-state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    for key, value in expect.get("state", {}).items():
        if state.get(key) != value:
            failures.append(f"runner state {key}={state.get(key)!r}, expected {value!r}")
    for check_id, status in expect.get("checks", {}).items():
        got = state.get("results", {}).get(check_id, {}).get("status")
        if got != status:
            failures.append(f"check {check_id} is {got!r}, expected {status!r}")

    audit_file = project / ".rocket" / "audit.jsonl"
    audit = [json.loads(line) for line in audit_file.read_text().splitlines()] if audit_file.exists() else []
    for needle in expect.get("audit_blocked", []):
        if not any(needle in str(entry.get("blocked", "")) for entry in audit):
            failures.append(f"no audit entry blocked with {needle!r}")
    if expect.get("session_attached") and not any(e.get("tool") == "rocket_run_job" and e.get("sessionID") for e in audit):
        failures.append("rocket_run_job calls were not audited with a session id")
    return failures


def run_scenario(path: Path) -> bool:
    scenario = json.loads(path.read_text())
    if scenario.get("engine") and not os.environ.get("ROCKET_ENGINE_HOME"):
        print(f"SKIP  {scenario['name']}  (set ROCKET_ENGINE_HOME to a rocket-engine checkout)")
        return True
    missing = [tool for tool in scenario.get("requires", []) if not shutil.which(tool)]
    if missing:
        print(f"SKIP  {scenario['name']}  (needs {', '.join(missing)} on PATH)")
        return True
    FakeModel.steps = scenario["steps"]
    FakeModel.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeModel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        project = prepare_project(scenario, server.server_address[1])
        FakeModel.project = str(project)
        result = run_opencode(project, scenario)
        failures = check(project, scenario["expect"], tool_results(FakeModel.requests))
        tool_turns = sum(1 for r in FakeModel.requests if r.get("tools"))
        if tool_turns < len(scenario["steps"]):
            failures.append(f"opencode stopped after {tool_turns} of {len(scenario['steps'])} scripted turns")
    finally:
        server.shutdown()

    print(f"{'PASS' if not failures else 'FAIL'}  {scenario['name']}  ({project})")
    for failure in failures:
        print(f"      - {failure}")
    if failures:
        print("      opencode stderr tail:", *result.stderr.strip().splitlines()[-8:], sep="\n        ")
    else:
        shutil.rmtree(project)
    return not failures


def main() -> int:
    if not OPENCODE.exists():
        print("Pinned opencode missing: run `npm install` in the repo root first.")
        return 2
    wanted = set(sys.argv[1:])
    paths = [p for p in sorted(SCENARIOS.glob("*.json")) if not wanted or p.stem in wanted]
    results = [run_scenario(p) for p in paths]
    print(f"\n{sum(results)}/{len(results)} scenarios passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
