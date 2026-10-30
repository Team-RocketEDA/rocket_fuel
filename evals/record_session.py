"""Record a live agent session from opencode's server event stream, for replay in the IDE.

Starts the pinned opencode server on a fresh demo project (or --project), sends one prompt,
and writes every event from GET /event with its time offset to a JSONL file until the session
goes idle. With --approve, approval requests are answered "once" so the recording includes them.

Usage:
  python3 -I evals/record_session.py --out evals/recordings/opamp-free.jsonl \
      [--prompt "Bring this op-amp to spec."] [--agent rocket-approval] [--approve] [--project DIR]
Set ROCKET_MODEL / MODEL_API_KEY as for scripts/dev.sh.
"""

import argparse
import base64
import json
import os
import secrets
import socket
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

FUEL_HOME = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, base: str, password: str):
        self.base = base
        self.auth = "Basic " + base64.b64encode(f"opencode:{password}".encode()).decode()

    def request(self, method: str, path: str, body: dict | None = None, timeout: float = 30):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Authorization": self.auth, "Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=timeout)

    def json(self, method: str, path: str, body: dict | None = None):
        with self.request(method, path, body) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None


def wait_ready(server: Server, proc: subprocess.Popen, timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("opencode server exited during startup")
        try:
            server.json("GET", "/session")
            return
        except OSError:
            time.sleep(0.5)
    raise TimeoutError("opencode server did not start")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--prompt", default="Bring this op-amp to spec.")
    parser.add_argument("--agent", default="rocket-approval")
    parser.add_argument("--project")
    parser.add_argument("--approve", action="store_true", help='answer every approval request "once"')
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()

    project = args.project or subprocess.run([FUEL_HOME / "scripts" / "new-demo.sh"], check=True,
                                             capture_output=True, text=True).stdout.strip()
    port, password = free_port(), secrets.token_urlsafe(24)
    env = {**os.environ, "OPENCODE_SERVER_PASSWORD": password}
    proc = subprocess.Popen([FUEL_HOME / "scripts" / "dev.sh", project, "serve", "--port", str(port)],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    server = Server(f"http://127.0.0.1:{port}", password)
    events: list[dict] = []
    idle = threading.Event()
    session_id: list[str] = []

    try:
        wait_ready(server, proc)
        config = server.json("GET", "/config")
        start = time.monotonic()

        def listen():
            with server.request("GET", "/event", timeout=args.timeout) as stream:
                for line in stream:
                    if not line.startswith(b"data:"):
                        continue
                    event = json.loads(line[5:])
                    events.append({"t_ms": round((time.monotonic() - start) * 1000), "event": event})
                    props = event.get("properties", {})
                    if session_id and props.get("sessionID") != session_id[0]:
                        continue
                    if event["type"] == "permission.asked" and args.approve:
                        server.json("POST", f"/permission/{props['id']}/reply", {"reply": "once"})
                    if event["type"] == "session.idle" and session_id:
                        idle.set()
                        return

        threading.Thread(target=listen, daemon=True).start()
        time.sleep(0.5)
        session = server.json("POST", "/session", {"title": "recorded session"})
        session_id.append(session["id"])
        server.json("POST", f"/session/{session['id']}/prompt_async",
                    {"agent": args.agent, "parts": [{"type": "text", "text": args.prompt}]})
        finished = idle.wait(args.timeout)
    finally:
        os.killpg(proc.pid, 15)

    header = {
        "recording": "rocket-fuel/v1",
        "note": "REPLAY of a recorded session. Show a REPLAY banner whenever these events are displayed.",
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "opencode": "1.19.5",
        "model": config.get("model"),
        "agent": args.agent,
        "prompt": args.prompt,
        "session_id": session_id[0] if session_id else None,
        "complete": finished,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Recordings get committed; keep local paths out of them.
    replacements = [(str(Path(project).resolve()), "/project"), (str(FUEL_HOME), "/rocket_fuel"), (str(Path.home()), "/home/user")]
    with out.open("w") as f:
        f.write(json.dumps(header) + "\n")
        for item in events:
            line = json.dumps(item)
            for local, public in replacements:
                line = line.replace(local, public)
            f.write(line + "\n")
    print(f"{'complete' if finished else 'TIMED OUT'}: {len(events)} events -> {out}")
    return 0 if finished else 1


if __name__ == "__main__":
    raise SystemExit(main())
