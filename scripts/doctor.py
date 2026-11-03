#!/usr/bin/env python3
"""Is this machine ready to run Rocket Fuel (and the IDE demo)? Checks tools, the sibling checkouts and,
unless --no-model, whether the configured model actually answers. Prints a fix for each problem.

Usage: python3 -I scripts/doctor.py [--no-model] [--model provider/model]
Exit code 0 when everything required is OK.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

FUEL_HOME = Path(__file__).resolve().parents[1]
ROOT = FUEL_HOME.parent
PINNED_OPENCODE = "1.19.5"
LOG = FUEL_HOME / ".opencode-home" / "data" / "opencode" / "log" / "opencode.log"
# Provider keys opencode reads from the environment (names only; values are never printed).
PROVIDER_KEYS = {
    "MODEL_API_KEY": "meta (Muse)",
    "OPENROUTER_API_KEY": "openrouter",
    "GROQ_API_KEY": "groq",
    "GOOGLE_GENERATIVE_AI_API_KEY": "google",
    "ANTHROPIC_API_KEY": "anthropic",
    "OPENAI_API_KEY": "openai",
}

problems = 0


def report(level: str, item: str, detail: str = "", fix: str = "") -> None:
    global problems
    if level == "FAIL":
        problems += 1
    print(f"{level:<5} {item}" + (f" — {detail}" if detail else ""))
    if fix and level != "OK":
        print(f"      fix: {fix}")


def read_env() -> dict[str, str]:
    """.env as dev.sh sees it (KEY=value lines), with the real environment winning."""
    values: dict[str, str] = {}
    env_file = FUEL_HOME / ".env"
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            match = re.match(r"^\s*([A-Z_][A-Z0-9_]*)=(.*)$", line)
            if match:
                values[match.group(1)] = match.group(2).strip().strip("'\"")
    for key in ("ROCKET_MODEL", "ROCKET_ENGINE_HOME", *PROVIDER_KEYS):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def check_tools() -> None:
    package = FUEL_HOME / "node_modules" / "opencode-ai" / "package.json"
    if package.is_file() and json.loads(package.read_text()).get("version") == PINNED_OPENCODE:
        report("OK", f"opencode {PINNED_OPENCODE} (pinned)")
    else:
        report("FAIL", "pinned opencode", "missing or wrong version", "npm install   (in rocket_fuel)")
    for tool, fix, required in [
        ("git", "install git", True),
        ("node", "install Node.js 22+", True),
        ("uv", "curl -LsSf https://astral.sh/uv/install.sh | sh", True),
        ("bun", "curl -fsSL https://bun.sh/install | bash   (only for the plugin/client tests)", False),
        ("ngspice", "sudo apt install ngspice   (without it every simulation is NOT_RUN)", True),
    ]:
        if shutil.which(tool):
            report("OK", tool)
        else:
            report("FAIL" if required else "WARN", tool, "not on PATH", fix)


def check_checkouts(env: dict[str, str]) -> None:
    engine = Path(env.get("ROCKET_ENGINE_HOME") or ROOT / "rocket-engine")
    server = engine / "src" / "adapters" / "mcp" / "server.py"
    branch_fix = (f"cd {engine} && git fetch && git checkout GREEN-the-tests && uv sync   "
                  "(main once it is merged), or set ROCKET_ENGINE_HOME")
    if not engine.is_dir():
        report("FAIL", "rocket-engine", f"not found at {engine}",
               f"git clone https://github.com/Team-RocketEDA/rocket-engine.git {engine}   (or set ROCKET_ENGINE_HOME)")
    elif not server.is_file():
        report("FAIL", "rocket-engine", f"{engine} is on a branch without the MCP server", branch_fix)
    else:
        text = server.read_text()
        if "--project-dir" in text and "run_job" in text:
            report("OK", "rocket-engine", f"{engine} (project-bound server)")
            if "datasets" not in text:
                report("WARN", "rocket-engine waveforms", "runs keep no waveform datasets, so the IDE's Plots page stays empty",
                       "port dataset saving from rocket-engine PR #3 onto this branch")
        else:
            report("FAIL", "rocket-engine", f"{engine} lacks the project-bound MCP server", branch_fix)
        if not (engine / ".venv").is_dir():
            report("WARN", "rocket-engine environment", "no .venv yet", f"cd {engine} && uv sync")
    ui = ROOT / "UIUX"
    if (ui / "server" / "workspace.ts").is_file():
        if (ui / "node_modules").is_dir():
            report("OK", "UIUX", f"{ui} (real workspace)")
        else:
            report("WARN", "UIUX", "dependencies not installed", f"cd {ui} && npm install")
    elif ui.is_dir():
        report("WARN", "UIUX", "this checkout has no workspace server (sample-data UI)",
               "check out UIUX main")
    else:
        report("WARN", "UIUX", f"not found at {ui}", "only needed for the IDE; Fuel runs on its own in the terminal")


def classify(log_text: str) -> tuple[str, str]:
    """(problem, fix) from opencode's log for a failed model call."""
    errors = re.findall(r'error\.error="([^"]*)', log_text) + re.findall(r'"message":"([^"]{0,200})', log_text)
    joined = " | ".join(errors)
    if re.search(r"free usage|free_tier_limit", joined, re.I):
        return ("the free opencode quota is used up (it is shared by all opencode/*-free models on this machine)",
                "wait for the reset, or put a key in rocket_fuel/.env: e.g. OPENROUTER_API_KEY=… with "
                "ROCKET_MODEL=openrouter/google/gemma-4-31b-it:free (free sign-up), or MODEL_API_KEY for Muse")
    if re.search(r"401|403|unauthori[sz]ed|invalid.{0,20}key|api key", joined, re.I):
        return ("the provider rejected the key", "check the key in rocket_fuel/.env for this provider")
    if re.search(r"model.{0,30}not found|ProviderModelNotFound|unknown model|no such model", joined, re.I):
        return ("the model name is not known to the provider", "list models: scripts/dev.sh <project> models <provider>")
    if re.search(r"429|rate.?limit", joined, re.I):
        return ("rate limited", "wait a minute, or use a key with a higher limit")
    if joined:
        return (errors[-1][:160], "see .opencode-home/data/opencode/log/opencode.log")
    return ("no answer before the timeout", "check the network; see .opencode-home/data/opencode/log/opencode.log")


def check_model(model: str, timeout: float) -> None:
    project = Path(tempfile.mkdtemp(prefix="rocket-doctor-"))
    try:
        subprocess.run([FUEL_HOME / "scripts" / "new-demo.sh", project, "empty"], check=True, capture_output=True)
        offset = LOG.stat().st_size if LOG.is_file() else 0
        started = time.time()
        env = dict(os.environ, ROCKET_MODEL=model)
        out_file = project.parent / f"{project.name}.out"

        def new_log() -> str:
            if not LOG.is_file():
                return ""
            with LOG.open(errors="replace") as handle:
                handle.seek(offset)
                return handle.read()

        with out_file.open("w") as out:
            proc = subprocess.Popen([FUEL_HOME / "scripts" / "dev.sh", project, "run", "-m", model, "Reply with exactly the word: pong"],
                                    stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, env=env)
            # opencode retries a failing provider for a long time; stop as soon as the log says why.
            while proc.poll() is None and time.time() - started < timeout:
                if "error.error=" in new_log():
                    break
                time.sleep(1)
            if proc.poll() is None:
                proc.terminate()
                proc.wait(10)
        output = out_file.read_text(errors="replace")
        out_file.unlink(missing_ok=True)
        took = time.time() - started
        if re.search(r"\bpong\b", output, re.I):
            report("OK", f"model {model}", f"answered in {took:.0f}s")
            return
        problem, fix = classify(new_log())
        report("FAIL", f"model {model}", problem, fix)
    finally:
        shutil.rmtree(project, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-model", action="store_true", help="skip the live model check (no network, no quota)")
    parser.add_argument("--model", help="model to check instead of ROCKET_MODEL")
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()

    env = read_env()
    print("Rocket Fuel doctor\n")
    check_tools()
    check_checkouts(env)

    model = args.model or env.get("ROCKET_MODEL") or "meta/muse-spark-1.3"
    keys = [f"{name} ({PROVIDER_KEYS[name]})" for name in PROVIDER_KEYS if env.get(name)]
    if not (FUEL_HOME / ".env").is_file():
        report("WARN", ".env", "missing", "cp .env.example .env")
    report("OK", f"ROCKET_MODEL={model}", "keys set: " + (", ".join(keys) if keys else "none (only opencode/*-free models work)"))
    provider = model.split("/", 1)[0]
    needs = {"meta": "MODEL_API_KEY", "openrouter": "OPENROUTER_API_KEY", "groq": "GROQ_API_KEY",
             "google": "GOOGLE_GENERATIVE_AI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}.get(provider)
    if needs and not env.get(needs):
        report("FAIL", f"key for {provider}", f"{needs} is not set", f"add {needs}=… to rocket_fuel/.env")
    elif args.no_model:
        report("WARN", f"model {model}", "not checked (--no-model)")
    else:
        check_model(model, args.timeout)

    print("\nReady." if not problems else f"\n{problems} problem(s) to fix.")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
