"""Replay a recorded session as opencode's event stream, so UI work doesn't need a live agent.

Serves GET /event (Server-Sent Events) with the recorded events at their original timing,
GET /replay with the recording header, and accepts POST /permission/<id>/reply as a no-op.
The first event is {"type": "rocket.replay", ...}: the UI must show a REPLAY banner.

Usage: python3 -I evals/replay_server.py evals/recordings/opamp-approval-free.jsonl [--port 4199] [--speed 2]
       [--pause-at permission.asked]   (hold at the first approval request, for UI work)
"""

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def load(path: Path) -> tuple[dict, list[dict]]:
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return lines[0], lines[1:]


class Replay(BaseHTTPRequestHandler):
    header: dict = {}
    events: list[dict] = []
    speed: float = 1.0
    pause_at: str | None = None

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")

    def _json(self, body, status=200):
        data = json.dumps(body).encode()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/replay"):
            return self._json(self.header)
        if not self.path.startswith("/event"):
            return self._json({"error": "replay server only serves /event and /replay"}, 404)

        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self._send({"type": "rocket.replay", "properties": self.header})
            start = time.monotonic()
            for item in self.events:
                delay = item["t_ms"] / 1000 / self.speed - (time.monotonic() - start)
                if delay > 0:
                    time.sleep(delay)
                self._send(item["event"])
                if self.pause_at and item["event"]["type"] == self.pause_at:
                    # Hold here (e.g. on an approval card) until the client disconnects.
                    while True:
                        time.sleep(15)
                        self.wfile.write(b": paused\n\n")
                        self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        if "/permission/" in self.path:
            return self._json(True)
        return self._json({"error": "read-only replay"}, 405)

    def _send(self, event: dict):
        self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
        self.wfile.flush()

    def log_message(self, *args):
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("recording", type=Path)
    parser.add_argument("--port", type=int, default=4199)
    parser.add_argument("--speed", type=float, default=1.0, help="2 = twice as fast")
    parser.add_argument("--pause-at", help="stop at the first event of this type and hold, e.g. permission.asked")
    args = parser.parse_args()

    Replay.header, Replay.events = load(args.recording)
    Replay.speed = args.speed
    Replay.pause_at = args.pause_at
    print(f"REPLAY of {args.recording.name} ({len(Replay.events)} events) on http://127.0.0.1:{args.port}/event")
    ThreadingHTTPServer(("127.0.0.1", args.port), Replay).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
