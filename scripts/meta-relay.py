#!/usr/bin/env python3
"""Backward-compatible entry point for the old Meta relay.

The relay itself is provider-neutral now: see ``model-relay.py``. Existing
installations and scripts that call ``meta-relay.py`` keep working, with Meta as
the default provider and upstream.

Usage: python3 -I scripts/meta-relay.py [--port 8766] [--upstream https://api.meta.ai]
       [--log meta-calls.jsonl]
"""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("model_relay", Path(__file__).with_name("model-relay.py"))
_relay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_relay)

Usage = _relay.Usage
build_handler = _relay.build_handler


def main(argv=None):
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if "--provider" not in args:
        args += ["--provider", "meta"]
    if "--tag" not in args:
        args += ["--tag", "Meta Model API"]
    return _relay.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
