#!/usr/bin/env python3
"""Complete one minimal request with the configured provider/model.

The IDE's Settings uses this for native OpenCode providers: rather than inventing
an HTTP client per vendor, it starts the pinned OpenCode runtime on a throwaway
project and asks it to answer "pong" with the selected model. OpenAI-compatible
endpoints are tested directly with their Chat Completions API. The key is read
from the environment or credentials file and is never printed.

Output: one JSON object: {ok, category, message, status?}
Usage: python3 -I test_connection.py --provider openai --model gpt-5.1 --type native
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import model_config  # noqa: E402


def scrub(text: str, key: str) -> str:
    return text.replace(key, "***") if key else text


def error_message(body: str) -> str:
    try:
        data = json.loads(body)
        return str(data.get("error", {}).get("message") or data.get("message") or data.get("error") or "")
    except ValueError:
        return body.strip().replace("\n", " ")


def classify(status: int, message: str) -> tuple[str, str]:
    message = message or f"HTTP {status}"
    if status in (401, 403):
        return "auth", f"The provider refused this API key. {message}"
    if status == 404:
        return "model", f"The endpoint or model was not found. {message}"
    if status == 429:
        return "rate_limit", f"The provider is rate limiting requests. {message}"
    if status >= 500:
        return "unavailable", f"The provider is unavailable right now. {message}"
    if re.search(r"\bmodel\b.{0,40}(not found|unknown|does not exist)|unknown model|no such model", message, re.I):
        return "model", f"The provider does not know that model. {message}"
    if re.search(r"bad key|invalid.{0,20}key|unauthori[sz]ed|authentication", message, re.I):
        return "auth", f"The provider refused this API key. {message}"
    if re.search(r"permission|not authorized|insufficient", message, re.I):
        return "auth", f"The provider refused permission. {message}"
    if re.search(r"unsupported|protocol", message, re.I):
        return "protocol", f"The endpoint does not speak the expected protocol. {message}"
    # No HTTP status means OpenCode could not complete a turn; that is never a success.
    return ("unknown" if status == 0 or status >= 400 else "ok"), message


ANSI = re.compile(r"\x1b\[[0-9;]*m")


def clean_output(text: str) -> str:
    """The useful line from OpenCode's terminal output, without colour codes or a stack of blank lines."""
    lines = [line.strip() for line in ANSI.sub("", text).splitlines() if line.strip()]
    errors = [line for line in lines if "error" in line.lower()]
    return (errors[-1] if errors else (lines[-1] if lines else "The model did not answer."))[-300:]


def test_openai(provider: str, model: str, base_url: str, key: str) -> dict:
    if not base_url:
        return {"ok": False, "category": "endpoint", "message": "A base URL is required for an OpenAI-compatible provider."}
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly the word: pong"}],
        "max_tokens": 16,
        "stream": False,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", body, headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as reply:
            status, text = reply.status, reply.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        status, text = error.code, error.read().decode("utf-8", "replace")
        category, message = classify(status, error_message(text))
        return {"ok": False, "category": category, "message": scrub(message, key), "status": status}
    except (OSError, ValueError) as error:
        return {"ok": False, "category": "endpoint", "message": scrub(f"Could not reach {base_url}: {error}", key)}
    try:
        answer = json.loads(text).get("choices", [{}])[0].get("message", {}).get("content", "")
    except ValueError:
        return {"ok": False, "category": "protocol", "status": status,
                "message": "The endpoint answered, but not with an OpenAI-compatible chat completion."}
    if "pong" not in answer.lower():
        return {"ok": False, "category": "protocol", "status": status,
                "message": scrub(f"The model answered, but not to a chat completion request: {answer[:160]}", key)}
    return {"ok": True, "category": "ok", "status": status,
            "message": f"Connected: {provider}/{model} completed a minimal request."}


def find_opencode(fuel_home: Path) -> str | None:
    local = fuel_home / "node_modules" / ".bin" / "opencode"
    if local.exists():
        return str(local)
    return shutil.which("opencode")


def test_native(provider: str, model: str, base_url: str, key: str, fuel_home: Path) -> dict:
    binary = find_opencode(fuel_home)
    if not binary:
        return {"ok": False, "category": "unavailable",
                "message": "The pinned OpenCode runtime is not installed. Run `npm install` in rocket_fuel."}
    project = Path(tempfile.mkdtemp(prefix="rocket-connection-"))
    state = project / "state"
    try:
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        config: dict = {
            "$schema": "https://opencode.ai/config.json",
            "provider": {provider: {"models": {model: {"name": model}}}},
            "model": f"{provider}/{model}",
            "small_model": f"{provider}/{model}",
            "enabled_providers": [provider],
        }
        if base_url:
            config["provider"][provider]["npm"] = "@ai-sdk/openai-compatible"
            config["provider"][provider]["options"] = {"baseURL": base_url, "apiKey": "{env:MODEL_API_KEY}"}
        (project / "opencode.json").write_text(json.dumps(config, indent=2))
        env = {
            **os.environ,
            "XDG_DATA_HOME": str(state / "data"), "XDG_CONFIG_HOME": str(state / "config"),
            "XDG_STATE_HOME": str(state / "state"), "XDG_CACHE_HOME": str(state / "cache"),
            "ROCKET_MODEL_CALL_LOG": str(state / "model-calls.jsonl"),
            "ROCKET_FUEL_HOME": str(fuel_home),
            "PWD": str(project),
        }
        for name, value in list(env.items()):
            if value is None:
                env.pop(name)
        names = model_config.PROVIDER_KEY_ENVS.get(provider, ("MODEL_API_KEY",))
        if key:
            for name in names:
                env[name] = key
            env["MODEL_API_KEY"] = key
        result = subprocess.run(
            [binary, "run", "--model", f"{provider}/{model}", "--title", "connection test",
             "Reply with exactly the word: pong"],
            cwd=project, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=45,
        )
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        if "pong" in output.lower():
            return {"ok": True, "category": "ok", "message": f"Connected: {provider}/{model} completed a minimal request."}
        category, message = classify(0, clean_output((result.stderr or "") + "\n" + (result.stdout or "")))
        return {"ok": False, "category": category, "message": scrub(message, key)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "category": "unavailable", "message": "The provider did not answer within 45 seconds."}
    except Exception as error:  # noqa: BLE001 - the helper must always return JSON
        return {"ok": False, "category": "unknown", "message": scrub(f"Connection test failed: {error}", key)}
    finally:
        shutil.rmtree(project, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--type", default="native", choices=model_config.PROVIDER_TYPES)
    parser.add_argument("--base-url")
    parser.add_argument("--fuel-home", default=str(HERE.parent))
    args = parser.parse_args()
    key = model_config.provider_key(args.provider, dict(os.environ), prefer_env=True)
    if args.type == "openai-compatible":
        result = test_openai(args.provider, args.model, args.base_url or "", key)
    else:
        result = test_native(args.provider, args.model, args.base_url or "", key, Path(args.fuel_home))
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    # A failing test is still a successful helper run; the JSON says what happened.
    main()
    raise SystemExit(0)
