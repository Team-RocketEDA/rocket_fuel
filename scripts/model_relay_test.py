"""Tests for model-relay.py, the optional transparent OpenAI-compatible relay.

Run: python3 -I scripts/model_relay_test.py

The relay is provider-neutral: these tests use a stand-in server answering for a
non-Meta provider, and check that requests and replies pass through unchanged
(including a streamed reply read incrementally), while the log holds only facts.
"""

import contextlib
import importlib.util
import io
import json
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

spec = importlib.util.spec_from_file_location("model_relay", Path(__file__).with_name("model-relay.py"))
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)
KEY = "sk-test-not-a-real-key-123456"
MODEL = "house-model"


class StandIn(BaseHTTPRequestHandler):
    """Answers like an arbitrary OpenAI-compatible endpoint."""

    protocol_version = "HTTP/1.1"
    seen = {}
    gate = threading.Event()
    mode = "json"

    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        StandIn.seen = {"auth": self.headers.get("Authorization"), "path": self.path, "body": body}
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            first = f"data: {json.dumps({'model': MODEL, 'choices': [{'delta': {'content': 'Hi'}}]})}\n\n".encode()
            self._chunk(first)
            # The test releases us only after it has read the first event. If the relay buffered the whole
            # response instead of streaming it, that read would block until this timeout.
            StandIn.gate.wait(6)
            last = ("data: " + json.dumps({"model": MODEL, "choices": [],
                                          "usage": {"prompt_tokens": 42, "completion_tokens": 7}}) + "\n\n"
                    "data: [DONE]\n\n").encode()
            self._chunk(last)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            return
        if StandIn.mode == "error":
            data = json.dumps({"error": {"message": "bad key"}}).encode()
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
        else:
            data = json.dumps({"model": MODEL,
                               "choices": [{"message": {"role": "assistant", "content": None,
                                                        "tool_calls": [{"id": "call_1", "type": "function",
                                                                        "function": {"name": "rocket_run_job",
                                                                                     "arguments": "{}"}}]}}],
                               "usage": {"prompt_tokens": 5, "completion_tokens": 1}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        self.send_header("x-request-id", "req_standin")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _chunk(self, data):
        self.wfile.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")
        self.wfile.flush()


def serve(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]


class RelayTest(unittest.TestCase):
    def setUp(self):
        StandIn.mode = "json"
        StandIn.gate.clear()
        StandIn.seen = {}
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
        self.upstream_port = serve(self.upstream)
        self.log = Path(tempfile.mkdtemp()) / "model-calls.jsonl"
        self.printed = io.StringIO()
        handler = relay.build_handler(f"http://127.0.0.1:{self.upstream_port}", str(self.log), color=False,
                                      provider="custom", tag="House API")
        self.relay = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{serve(self.relay)}/v1/chat/completions"

    def tearDown(self):
        StandIn.gate.set()
        for server in (self.relay, self.upstream):
            server.shutdown()
            server.server_close()

    def request(self, stream, body=None, timeout=10):
        body = body or {"model": MODEL, "stream": stream, "messages": [{"role": "user", "content": "ping"}]}
        request = urllib.request.Request(self.url, json.dumps(body).encode(),
                                         {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
        return request

    @staticmethod
    def wait_for_response(output, timeout=5.0):
        """The response line is written just after the client has the reply."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if "<- " in output.getvalue():
                return
            time.sleep(0.05)
        raise AssertionError(f"no response line was logged; saw: {output.getvalue()!r}")

    def test_a_streamed_reply_passes_through_incrementally_and_is_logged(self):
        with contextlib.redirect_stdout(self.printed):
            with urllib.request.urlopen(self.request(True), timeout=10) as reply:
                started = time.monotonic()
                first = reply.readline().decode()
                elapsed = time.monotonic() - started
                StandIn.gate.set()
                rest = reply.read().decode()
            # The response line is written just after the last chunk reaches the client.
            for _ in range(100):
                if "<- " in self.printed.getvalue():
                    break
                time.sleep(0.05)
        self.assertIn("data:", first)
        self.assertLess(elapsed, 3, "the first event should not wait for the whole reply")
        self.assertIn("data: [DONE]", rest)
        self.assertEqual(StandIn.seen["auth"], f"Bearer {KEY}")
        self.assertEqual(StandIn.seen["path"], "/v1/chat/completions")
        out = self.printed.getvalue()
        self.assertIn("[House API]", out)
        self.assertIn("-> POST /v1/chat/completions", out)
        self.assertIn("model=house-model", out)
        self.assertIn("tokens in 42 / out 7", out)
        for line in self.log.read_text().splitlines():
            record = json.loads(line)
            self.assertEqual(record["provider"], "custom")
            self.assertNotIn(KEY, line)
            self.assertNotIn("ping", line)

    def test_tool_calls_and_json_replies_pass_through_unchanged(self):
        with contextlib.redirect_stdout(self.printed):
            with urllib.request.urlopen(self.request(False), timeout=10) as reply:
                status, text = reply.status, reply.read().decode()
            self.wait_for_response(self.printed)
        self.assertEqual(status, 200)
        reply_body = json.loads(text)
        self.assertEqual(reply_body["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "rocket_run_job")
        records = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual([r["event"] for r in records], ["request", "response"])
        self.assertEqual(records[1]["model"], MODEL)
        self.assertEqual((records[1]["tokens_in"], records[1]["tokens_out"]), (5, 1))
        self.assertEqual(records[1]["provider"], "custom")
        self.assertNotIn(KEY, self.log.read_text())

    def test_an_upstream_error_keeps_its_status_and_body(self):
        StandIn.mode = "error"
        with contextlib.redirect_stdout(self.printed):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(self.request(False), timeout=10)
            body = caught.exception.read().decode()
            self.wait_for_response(self.printed)
        self.assertEqual(caught.exception.code, 401)
        self.assertEqual(json.loads(body)["error"]["message"], "bad key")
        records = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(records[-1]["event"], "response")
        self.assertEqual(records[-1]["status"], 401)
        self.assertNotIn(KEY, self.log.read_text())
        self.assertNotIn(KEY, self.printed.getvalue())

    def test_an_unreachable_upstream_is_a_502_and_never_a_silent_success(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        printed = io.StringIO()
        log = Path(tempfile.mkdtemp()) / "calls.jsonl"
        handler = relay.build_handler(f"http://127.0.0.1:{port}", str(log), color=False, provider="custom")
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        url = f"http://127.0.0.1:{serve(server)}/v1/chat/completions"
        request = urllib.request.Request(url, b'{"model":"x"}', {"Content-Type": "application/json"})
        with contextlib.redirect_stdout(printed):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=10)
            self.assertEqual(caught.exception.code, 502)
            self.assertIn("relay could not reach", caught.exception.read().decode())
            self.wait_for_response(printed)
        records = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(records[-1]["status"], 502)
        server.shutdown()
        server.server_close()

    def test_usage_reads_both_chat_completions_and_responses_api_shapes(self):
        usage = relay.Usage()
        usage.take({"model": "a", "usage": {"prompt_tokens": 3, "completion_tokens": 4}})
        self.assertEqual((usage.model, usage.tokens_in, usage.tokens_out), ("a", 3, 4))
        usage.feed_stream('data: {"type": "response.completed", "response": {"model": "b", '
                          '"usage": {"input_tokens": 9, "output_tokens": 2}}}\n\n')
        self.assertEqual((usage.model, usage.tokens_in, usage.tokens_out), ("b", 9, 2))


if __name__ == "__main__":
    unittest.main()
