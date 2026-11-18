#!/usr/bin/env python3
"""Print new model-call records as they are appended, provider-neutrally.

Rocket Fuel's plugin writes one record per completed model message. The relay,
when one is enabled, writes request/response records. This tail prints the useful
facts for either shape and never prints a key, a prompt or a message body.

Usage: python3 -I model-log-tail.py <log.jsonl>
"""

import json
import os
import sys
import time
from datetime import datetime


def line(record: dict) -> str | None:
    event = record.get("event")
    provider = record.get("provider") or "-"
    model = record.get("model") or "-"
    if event == "request":
        return f"[Model API] {provider}/{model}  -> {record.get('method', 'POST')} {record.get('path', '')}"
    if event not in ("response", "call"):
        return None
    status = record.get("status", "?")
    seconds = record.get("seconds")
    if seconds is None and record.get("duration_ms") is not None:
        seconds = record["duration_ms"] / 1000
    tokens_in = record.get("tokens_in", record.get("input_tokens"))
    tokens_out = record.get("tokens_out", record.get("output_tokens"))
    tokens = f"  tokens in {tokens_in} / out {tokens_out}" if tokens_in is not None or tokens_out is not None else ""
    took = f"  {seconds:.2f} s" if isinstance(seconds, (int, float)) else ""
    return f"[Model API] {provider}/{model}  <- {status}{tokens}{took}"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.splitlines()[0], file=sys.stderr)
        return 2
    path = sys.argv[1]
    while not os.path.exists(path):
        time.sleep(0.5)
    with open(path, "r", encoding="utf-8", errors="replace") as log:
        log.seek(0, os.SEEK_END)
        while True:
            where = log.tell()
            text = log.readline()
            if not text:
                time.sleep(0.5)
                log.seek(where)
                continue
            try:
                record = json.loads(text)
            except ValueError:
                continue
            printed = line(record)
            if printed:
                stamp = datetime.now().strftime("%H:%M:%S")
                print(f"{printed}  {stamp}", flush=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        pass
