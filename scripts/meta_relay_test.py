"""Tests for meta-relay.py against a stand-in for the Meta Model API. Run: python3 -I scripts/meta_relay_test.py"""

import contextlib
import importlib.util
import io
import json
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

spec = importlib.util.spec_from_file_location("meta_relay", Path(__file__).with_name("meta-relay.py"))
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)
KEY = "sk-test-not-a-real-key-123456"


class StandIn(BaseHTTPRequestHandler):
    """Answers like the Meta Model API: a JSON reply, or an SSE stream when the request asks for one."""

    protocol_version = "HTTP/1.1"
    seen = {}

    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        StandIn.seen = {"auth": self.headers.get("Authorization"), "path": self.path, "body": body}
        if body.get("stream"):
            events = [{"model": "muse-spark-1.3", "choices": [{"delta": {"content": "Hi"}}]},
                      {"model": "muse-spark-1.3", "choices": [], "usage": {"prompt_tokens": 42, "completion_tokens": 7}}]
            data = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
        else:
            data = json.dumps({"model": "muse-spark-1.3", "choices": [{"message": {"content": "pong"}}],
                               "usage": {"prompt_tokens": 5, "completion_tokens": 1}})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        self.send_header("x-request-id", "req_standin")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data.encode())


def serve(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]


class RelayTest(unittest.TestCase):
    def setUp(self):
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
        port = serve(self.upstream)
        self.log = Path(tempfile.mkdtemp()) / "calls.jsonl"
        self.printed = io.StringIO()
        handler = relay.build_handler(f"http://127.0.0.1:{port}", str(self.log), color=False)
        self.relay = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{serve(self.relay)}/v1/chat/completions"

    def tearDown(self):
        self.relay.shutdown()
        self.upstream.shutdown()

    def call(self, stream):
        body = json.dumps({"model": "muse-spark-1.3", "stream": stream, "messages": [{"role": "user", "content": "ping"}]})
        request = urllib.request.Request(self.url, body.encode(), {"Authorization": f"Bearer {KEY}",
                                                                    "Content-Type": "application/json"})
        with contextlib.redirect_stdout(self.printed):
            with urllib.request.urlopen(request, timeout=10) as reply:
                result = reply.status, reply.read().decode()
            # The relay logs the answer just after the last chunk reaches the client.
            for _ in range(50):
                if "<- " in self.printed.getvalue():
                    break
                time.sleep(0.05)
        return result

    def test_streamed_call_is_relayed_and_logged_with_the_reply_model(self):
        status, text = self.call(stream=True)
        self.assertEqual(status, 200)
        self.assertIn("data: [DONE]", text)
        self.assertEqual(StandIn.seen["auth"], f"Bearer {KEY}")
        self.assertEqual(StandIn.seen["path"], "/v1/chat/completions")
        out = self.printed.getvalue()
        self.assertIn("-> POST /v1/chat/completions  model=muse-spark-1.3  stream", out)
        self.assertIn("<- 200  model=muse-spark-1.3  tokens in 42 / out 7", out)
        self.assertIn("id=req_standin", out)

    def test_json_call_and_the_log_never_hold_the_key_or_the_prompt(self):
        status, text = self.call(stream=False)
        self.assertEqual((status, json.loads(text)["choices"][0]["message"]["content"]), (200, "pong"))
        records = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual([r["event"] for r in records], ["request", "response"])
        self.assertEqual(records[1]["model"], "muse-spark-1.3")
        self.assertEqual((records[1]["tokens_in"], records[1]["tokens_out"]), (5, 1))
        for text in (self.printed.getvalue(), self.log.read_text()):
            self.assertNotIn(KEY, text)
            self.assertNotIn("ping", text)


if __name__ == "__main__":
    unittest.main()
