#!/usr/bin/env python3
"""A visible log of every call the agent makes to the Meta Model API.

opencode sends its requests here instead of straight to https://api.meta.ai/v1 (install-into-project.sh writes
ROCKET_META_BASE_URL into the project's config). Each request is forwarded unchanged and streamed back, and one
line is printed when it is sent and one when the API answers, naming the model the request asked for and the
model the API's own response reports:

  [Meta Model API] 10:41:03  -> POST /v1/chat/completions  model=muse-spark-1.3  stream
  [Meta Model API] 10:41:05  <- 200  model=muse-spark-1.3  tokens in 4210 / out 312  2.14 s  id=req_...

The same facts go to a JSONL file (--log) as provenance for a run. Keys, prompts and replies are never printed
or written: only the path, the model names, the status, token counts, timing and the API's request id.

Usage: python3 -I scripts/meta-relay.py [--port 8766] [--upstream https://api.meta.ai] [--log meta-calls.jsonl]
"""

import argparse
import http.client
import json
import ssl
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
              "transfer-encoding", "upgrade", "host", "content-length", "accept-encoding"}
TAG = "[Meta Model API]"


class Usage:
    """Model name and token counts, from a JSON reply or from the data: lines of a streamed one."""

    def __init__(self):
        self.model = None
        self.tokens_in = None
        self.tokens_out = None
        self._pending = ""

    def take(self, payload):
        if not isinstance(payload, dict):
            return
        self.model = payload.get("model") or self.model
        usage = payload.get("usage") or {}
        if isinstance(usage, dict):
            self.tokens_in = usage.get("prompt_tokens", usage.get("input_tokens", self.tokens_in))
            self.tokens_out = usage.get("completion_tokens", usage.get("output_tokens", self.tokens_out))

    def feed_stream(self, text):
        self._pending += text
        *lines, self._pending = self._pending.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]"):
                try:
                    self.take(json.loads(line[5:]))
                except ValueError:
                    pass


def build_handler(upstream, log_path, color):
    target = urllib.parse.urlsplit(upstream)
    lock = threading.Lock()
    paint = (lambda code, text: f"\033[{code}m{text}\033[0m") if color else (lambda code, text: text)

    def emit(line, record):
        with lock:
            print(line, flush=True)
            if log_path:
                with open(log_path, "a", encoding="utf-8") as log:
                    log.write(json.dumps(record) + "\n")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass  # one line per call is printed below instead

        def _relay(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            try:
                asked = json.loads(body).get("model") if body else None
                streaming = bool(json.loads(body).get("stream")) if body else False
            except (ValueError, AttributeError):
                asked, streaming = None, False
            started = time.monotonic()
            now = datetime.now().strftime("%H:%M:%S")
            emit(f"{paint('38;5;209', TAG)} {now}  -> {self.command} {self.path}  model={asked or '-'}"
                 + ("  stream" if streaming else ""),
                 {"at": datetime.now(timezone.utc).isoformat(), "event": "request", "method": self.command,
                  "path": self.path, "model": asked, "stream": streaming})

            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
            headers["Accept-Encoding"] = "identity"
            conn_type = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
            kwargs = {"context": ssl.create_default_context()} if target.scheme == "https" else {}
            conn = conn_type(target.hostname, target.port, timeout=600, **kwargs)
            usage = Usage()
            status = 502
            request_id = None
            try:
                conn.request(self.command, self.path, body=body or None, headers=headers)
                reply = conn.getresponse()
                status = reply.status
                request_id = reply.getheader("x-request-id") or reply.getheader("request-id")
                self.send_response(reply.status, reply.reason)
                for key, value in reply.getheaders():
                    if key.lower() not in HOP_BY_HOP:
                        self.send_header(key, value)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                is_stream = "text/event-stream" in (reply.getheader("Content-Type") or "")
                whole = b""
                while True:
                    chunk = reply.read1(65536)
                    if not chunk:
                        break
                    if is_stream:
                        usage.feed_stream(chunk.decode("utf-8", "replace"))
                    elif len(whole) < 4_000_000:
                        whole += chunk
                    self.wfile.write(f"{len(chunk):X}\r\n".encode() + chunk + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                if not is_stream and whole:
                    try:
                        usage.take(json.loads(whole))
                    except ValueError:
                        pass
            except (OSError, http.client.HTTPException) as exc:
                if status == 502:
                    message = json.dumps({"error": {"message": f"relay could not reach {upstream}: {exc}"}}).encode()
                    self.send_response(502)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(message)))
                    self.end_headers()
                    self.wfile.write(message)
            finally:
                conn.close()
            seconds = time.monotonic() - started
            tokens = (f"  tokens in {usage.tokens_in} / out {usage.tokens_out}"
                      if usage.tokens_in is not None or usage.tokens_out is not None else "")
            mark = paint("32", str(status)) if status < 400 else paint("31", str(status))
            emit(f"{paint('38;5;209', TAG)} {datetime.now().strftime('%H:%M:%S')}  <- {mark}  "
                 f"model={usage.model or '-'}{tokens}  {seconds:.2f} s" + (f"  id={request_id}" if request_id else ""),
                 {"at": datetime.now(timezone.utc).isoformat(), "event": "response", "path": self.path,
                  "status": status, "model": usage.model, "tokens_in": usage.tokens_in,
                  "tokens_out": usage.tokens_out, "seconds": round(seconds, 3), "request_id": request_id})

        do_POST = do_GET = _relay

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--upstream", default="https://api.meta.ai")
    parser.add_argument("--log", help="append one JSON line per request and per response here")
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), build_handler(args.upstream, args.log, sys.stdout.isatty()))
    print(f"{TAG} relaying http://127.0.0.1:{args.port}/v1 -> {args.upstream}/v1 (keys and prompts are never logged)",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
