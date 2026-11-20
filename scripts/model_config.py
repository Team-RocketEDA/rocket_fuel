#!/usr/bin/env python3
"""One provider-neutral model configuration for RocketIDE and Rocket Fuel.

The canonical settings live in one JSON file (default
``${XDG_CONFIG_HOME:-~/.config}/rocketide/model.json``).  Environment variables
such as ``ROCKET_MODEL`` still work and win over the file, which keeps existing
``.env`` installations working.  Nothing here ever writes an API key: keys live
in the separate credentials file owned by the IDE/``modelKey.ts``.

Conceptual settings::

    {"provider_id": "openai", "model_id": "gpt-5.1",
     "provider_type": "native", "base_url": null}

    {"provider_id": "custom", "model_id": "my-model",
     "provider_type": "openai-compatible",
     "base_url": "https://api.example.com/v1"}

Commands
--------
    model_config.py path
    model_config.py show [--json]
    model_config.py shell [--with-key]
    model_config.py generate --base harness/opencode.json [--out path]
    model_config.py export-key --provider <id>
    model_config.py set --provider <id> --model <id> --type native|openai-compatible
                        [--base-url URL] [--name NAME]

Only the Python standard library is used.  ``show`` and ``generate`` never
print or embed credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path

DEFAULT_PROVIDER = "meta"
DEFAULT_MODEL = "muse-spark-1.3"
DEFAULT_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_PROVIDER_NAME = "Meta Model API"
DEFAULT_MODEL_REF = f"{DEFAULT_PROVIDER}/{DEFAULT_MODEL}"

PROVIDER_TYPES = ("native", "openai-compatible")

# Providers OpenCode 1.19.5 knows natively through models.dev.  This is a
# convenience list for the UI and for inferring a type; it is not an allowlist.
NATIVE_PROVIDERS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google Gemini",
    "google-vertex": "Google Vertex AI",
    "deepseek": "DeepSeek",
    "mistral": "Mistral",
    "groq": "Groq",
    "openrouter": "OpenRouter",
    "together": "Together AI",
    "fireworks": "Fireworks AI",
    "xai": "xAI",
    "amazon-bedrock": "Amazon Bedrock",
    "azure": "Azure OpenAI",
    "ollama": "Ollama",
    "lmstudio": "LM Studio",
    "github-copilot": "GitHub Copilot",
    "opencode": "OpenCode Zen",
}

# Where each provider expects its key.  A stored key is injected under these
# names when the agent starts.  Meta keeps MODEL_API_KEY for compatibility; a
# custom endpoint gets its own name (see custom_key_env) so a role on another
# provider can never overwrite it.
PROVIDER_KEY_ENVS = {
    "meta": ("MODEL_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "google": ("GOOGLE_GENERATIVE_AI_API_KEY", "GEMINI_API_KEY"),
    "google-vertex": ("GOOGLE_VERTEX_API_KEY", "GOOGLE_API_KEY"),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "mistral": ("MISTRAL_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "together": ("TOGETHER_API_KEY",),
    "fireworks": ("FIREWORKS_API_KEY",),
    "xai": ("XAI_API_KEY",),
    "amazon-bedrock": ("AWS_ACCESS_KEY_ID",),
    "azure": ("AZURE_API_KEY",),
    "github-copilot": ("GITHUB_TOKEN",),
}

# Local servers that need no key.
KEYLESS_PROVIDERS = {"ollama", "lmstudio", "llamacpp", "vllm"}


def custom_key_env(provider: str) -> str:
    """A private environment name for one custom endpoint's key."""
    return "ROCKET_KEY_" + re.sub(r"[^A-Za-z0-9]", "_", provider).upper()


def provider_env_names(provider: str, provider_type: str = "native") -> tuple[str, ...]:
    if provider == DEFAULT_PROVIDER:
        return ("MODEL_API_KEY",)
    if provider_type == "native" and provider in PROVIDER_KEY_ENVS:
        return PROVIDER_KEY_ENVS[provider]
    return (custom_key_env(provider),)


META_MODELS = {
    "muse-spark-1.3": {
        "name": "Muse Spark 1.3",
        "attachment": True,
        "modalities": {"input": ["text", "image", "pdf"], "output": ["text"]},
        "limit": {"context": 1048576, "output": 32768},
    },
    "muse-spark-1.3-contributor": {
        "name": "Muse Spark 1.3 Contributor (cheap; Meta may train on prompts, dev/demo data only)",
        "attachment": True,
        "modalities": {"input": ["text", "image", "pdf"], "output": ["text"]},
        "limit": {"context": 1048576, "output": 32768},
    },
    "muse-wonder-1.0": {
        "name": "Muse Wonder 1.0",
        "attachment": True,
        "modalities": {"input": ["text", "image", "pdf"], "output": ["text"]},
        "limit": {"context": 1048576, "output": 32768},
    },
}

VERSION = 1
PROVIDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MODEL_RE = re.compile(r"^[^\s/][^\s]*$")


class ConfigError(ValueError):
    pass


def config_home(env: dict[str, str]) -> str:
    if env.get("ROCKET_CONFIG_HOME"):
        return env["ROCKET_CONFIG_HOME"]
    return env.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")


def config_path(env: dict[str, str]) -> Path:
    return Path(env.get("ROCKET_MODEL_CONFIG") or os.path.join(config_home(env), "rocketide", "model.json"))


def credentials_path(env: dict[str, str]) -> Path:
    return Path(env.get("ROCKET_CREDENTIALS_FILE") or os.path.join(config_home(env), "rocketide", "credentials"))


def default_call_log(env: dict[str, str]) -> str:
    return env.get("ROCKET_MODEL_CALL_LOG") or env.get("ROCKET_META_CALL_LOG") or os.path.join(config_home(env), "rocketide", "model-calls.jsonl")


def split_ref(ref: str) -> tuple[str, str]:
    """Split ``provider/model``.  Model IDs may themselves contain slashes."""
    if not isinstance(ref, str) or "/" not in ref:
        raise ConfigError(f"Model must be written as provider/model, not {ref!r}.")
    provider, model = ref.split("/", 1)
    if not PROVIDER_RE.match(provider):
        raise ConfigError(f"Invalid provider ID {provider!r}.")
    if not MODEL_RE.match(model):
        raise ConfigError(f"Invalid model ID {model!r}.")
    return provider, model


def model_ref(provider: str, model: str) -> str:
    if not PROVIDER_RE.match(provider or ""):
        raise ConfigError(f"Invalid provider ID {provider!r}. Use letters, digits, '.', '_' or '-'.")
    if not MODEL_RE.match(model or ""):
        raise ConfigError("Enter a model ID (no spaces).")
    return f"{provider}/{model}"


def canonical_type(provider: str, value: str | None, base_url: str | None) -> str:
    if value:
        if value not in PROVIDER_TYPES:
            raise ConfigError(f"provider_type must be one of: {', '.join(PROVIDER_TYPES)}.")
        return value
    if provider in NATIVE_PROVIDERS:
        return "native"
    if provider == DEFAULT_PROVIDER:
        return "openai-compatible"
    return "openai-compatible" if base_url else "native"


def clean_base_url(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().rstrip("/")
    if not re.match(r"^https?://[^\s]+$", value):
        raise ConfigError("The API base URL must start with http:// or https://.")
    if "@" in value.split("://", 1)[1].split("/", 1)[0]:
        raise ConfigError("Put credentials in the API key field, not in the base URL.")
    return value


def _find_key(value, path: str = "") -> str | None:
    """Any api_key/api-key anywhere in the document, at any depth."""
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in ("api_key", "api-key", "apikey"):
                return f"{path}.{key}".lstrip(".")
            found = _find_key(item, f"{path}.{key}".lstrip("."))
            if found:
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found = _find_key(item, f"{path}[{index}]")
            if found:
                return found
    return None


def read_config(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a JSON object.")
    found = _find_key(data)
    if found:
        raise ConfigError(f"API keys must never be stored in the model configuration file ({found}).")
    return data


def _env(env: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = env.get(name)
        if value:
            return value
    return None


def resolve(env: dict[str, str] | None = None, config_file: Path | None = None) -> dict:
    """Effective settings: environment > saved config > Meta defaults.

    Callers that load ``.env`` are responsible for not exporting model variables
    from it when a saved config exists; ``run.sh`` and ``dev.sh`` do that.  An
    explicitly exported value always wins, which is what the IDE uses when it
    starts the agent.
    """
    env = dict(os.environ if env is None else env)
    path = config_file or config_path(env)
    saved = read_config(path)

    saved_ref = saved.get("model_ref")
    if not saved_ref and saved.get("provider_id") and saved.get("model_id"):
        saved_ref = model_ref(str(saved["provider_id"]), str(saved["model_id"]))
    saved_ref = saved_ref or DEFAULT_MODEL_REF

    explicit_ref = _env(env, "ROCKET_MODEL")
    provider_env = _env(env, "ROCKET_PROVIDER")
    model_env = _env(env, "ROCKET_MODEL_ID")

    if explicit_ref:
        ref = explicit_ref
    elif provider_env or model_env:
        saved_provider, saved_model = split_ref(saved_ref)
        ref = model_ref(provider_env or saved_provider, model_env or (saved_model if provider_env else DEFAULT_MODEL))
    else:
        ref = saved_ref
    provider, model = split_ref(ref)

    base_url = clean_base_url(_env(env, "ROCKET_BASE_URL", "ROCKET_META_BASE_URL") or saved.get("base_url"))
    provider_type = canonical_type(provider, _env(env, "ROCKET_PROVIDER_TYPE") or saved.get("provider_type"), base_url)
    provider_name = _env(env, "ROCKET_PROVIDER_NAME") or saved.get("provider_name") or NATIVE_PROVIDERS.get(provider) or (
        DEFAULT_PROVIDER_NAME if provider == DEFAULT_PROVIDER else provider
    )
    if provider == DEFAULT_PROVIDER and not base_url:
        base_url = DEFAULT_BASE_URL
    if provider_type == "openai-compatible" and not base_url:
        raise ConfigError(f"Provider {provider!r} is OpenAI-compatible, so a base URL is required.")

    def role(name: str, saved_key: str) -> str:
        return _env(env, name) or saved.get(saved_key) or ""

    small = role("ROCKET_SMALL_MODEL", "small_model") or ref
    tutor = role("ROCKET_TUTOR_MODEL", "tutor_model") or ref
    reviewer = role("ROCKET_REVIEWER_MODEL", "reviewer_model") or (
        "meta/muse-wonder-1.0" if provider == DEFAULT_PROVIDER else ref
    )
    roles = {"small": small, "tutor": tutor, "reviewer": reviewer}
    for key, value in roles.items():
        if value:
            roles[key] = model_ref(*_role_ref_parts(value, provider))
    # Keep a full ref for comparison, but OpenCode wants provider/model.
    for key, value in roles.items():
        split_ref(value)

    models = saved.get("models") if isinstance(saved.get("models"), dict) else {}
    providers = saved.get("providers") if isinstance(saved.get("providers"), dict) else {}
    return {
        "version": VERSION,
        "config_file": str(path),
        "provider_id": provider,
        "model_id": model,
        "model_ref": f"{provider}/{model}",
        "provider_type": provider_type,
        "base_url": base_url if provider_type == "openai-compatible" else None,
        "provider_name": provider_name,
        "api_key_env": saved.get("api_key_env") or (PROVIDER_KEY_ENVS.get(provider, ("MODEL_API_KEY",))[0]),
        "small_model": roles["small"],
        "tutor_model": roles["tutor"],
        "reviewer_model": roles["reviewer"],
        "models": models,
        "providers": providers,
        "call_log": default_call_log(env),
    }


def _role_ref_parts(value: str, default_provider: str) -> tuple[str, str]:
    """A role override may be a full ref or just a model ID for the main provider."""
    if "/" in value:
        return split_ref(value)
    return default_provider, value


def _model_definition(model_id: str, saved_models: dict, provider: str) -> dict:
    definition = saved_models.get(model_id) if isinstance(saved_models.get(model_id), dict) else {}
    if provider == DEFAULT_PROVIDER and model_id in META_MODELS:
        return dict(META_MODELS[model_id], **definition)
    result = {"name": definition.get("name") or model_id}
    for key in ("attachment", "modalities", "limit", "reasoning", "tool_call"):
        if key in definition:
            result[key] = definition[key]
    return result


def opencode_config(effective: dict, base: dict) -> dict:
    """Build a pinned-OpenCode-1.19.5 config (singular ``provider`` key)."""
    config = json.loads(json.dumps(base))  # deep copy
    provider = effective["provider_id"]
    refs = [effective["model_ref"], effective["small_model"], effective["tutor_model"], effective["reviewer_model"]]
    providers = []
    for ref in refs:
        p, _ = split_ref(ref)
        if p not in providers:
            providers.append(p)

    saved_models = effective.get("models") or {}
    definitions: dict[str, dict] = {}
    for ref in refs:
        p, m = split_ref(ref)
        definitions.setdefault(p, {})[m] = _model_definition(m, saved_models, p)
    saved_providers = effective.get("providers") if isinstance(effective.get("providers"), dict) else {}

    blocks: dict[str, dict] = {}
    for p in providers:
        if p == DEFAULT_PROVIDER:
            blocks[p] = {
                "name": DEFAULT_PROVIDER_NAME,
                "npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": effective["base_url"] or DEFAULT_BASE_URL, "apiKey": "{env:MODEL_API_KEY}"},
                "models": {**META_MODELS, **definitions.get(p, {})},
            }
            continue
        extra = saved_providers.get(p) if isinstance(saved_providers.get(p), dict) else {}
        p_type = extra.get("provider_type") or (effective["provider_type"] if p == provider else "native")
        if p_type == "openai-compatible":
            base_url = extra.get("base_url") or (effective["base_url"] if p == provider else None)
            if not base_url:
                raise ConfigError(f"Provider {p!r} needs a base URL in the model configuration.")
            key_env = provider_env_names(p, "openai-compatible")[0]
            blocks[p] = {
                "name": extra.get("provider_name") or (effective["provider_name"] if p == provider else p),
                "npm": extra.get("npm") or "@ai-sdk/openai-compatible",
                # Always a placeholder: the key lives in the credentials file and is injected into the
                # OpenCode process, never written into a project's config. A non-Meta endpoint has its own
                # variable, so two endpoints (or a role on another provider) can't share one key.
                "options": {"baseURL": clean_base_url(base_url), "apiKey": f"{{env:{key_env}}}"},
                "models": {**definitions.get(p, {}), **(extra.get("models") if isinstance(extra.get("models"), dict) else {})},
            }
        else:
            # Native providers keep their models.dev metadata; only add the
            # manually entered IDs so an unknown model can still be selected.
            blocks[p] = {"models": definitions.get(p, {})}

    config["provider"] = blocks
    config["model"] = effective["model_ref"]
    config["small_model"] = effective["small_model"]
    config["enabled_providers"] = providers

    agents = config.get("agent") or {}
    main_roles = ("rocket-approval", "rocket-auto")
    for name in main_roles:
        if name in agents and not agents[name].get("disable"):
            agents[name]["model"] = effective["model_ref"]
    if "rocket-tutor" in agents and not agents["rocket-tutor"].get("disable"):
        agents["rocket-tutor"]["model"] = effective["tutor_model"]
    if "rocket-reviewer" in agents and not agents["rocket-reviewer"].get("disable"):
        agents["rocket-reviewer"]["model"] = effective["reviewer_model"]
        # reasoningEffort is provider-specific; a generic provider may reject it.
        agents["rocket-reviewer"].pop("options", None)
    config["agent"] = agents

    # Resolve the MCP command's Fuel path now, as the installer used to do with sed.
    fuel_home = os.environ.get("ROCKET_FUEL_HOME")
    command = config.get("mcp", {}).get("rocket", {}).get("command")
    if fuel_home and isinstance(command, list):
        command[:] = [str(item).replace("{env:ROCKET_FUEL_HOME}", fuel_home) for item in command]
    return config


def _read_credentials(path: Path) -> dict[str, str]:
    """JSON credentials, or the legacy ``MODEL_API_KEY=...`` file."""
    try:
        text = path.read_text()
    except OSError:
        return {}
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except ValueError:
            return {}
        keys = data.get("keys") if isinstance(data.get("keys"), dict) else {}
        return {str(k): str(v) for k, v in keys.items() if isinstance(v, str) and v}
    match = re.search(r"^MODEL_API_KEY=(.*)$", text, re.M)
    return {"meta": match.group(1).strip()} if match and match.group(1).strip() else {}


def save_credentials(path: Path, provider: str, key: str) -> None:
    """Store one provider's key in the private credentials file (0600, folder 0700).

    The IDE's TypeScript side owns the browser-facing management; this exists so
    scripts and tests use exactly the same file format.
    """
    keys = _read_credentials(path)
    keys[provider] = key
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps({"version": 1, "keys": keys}, indent=2) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _env_names(provider: str) -> tuple[str, ...]:
    """Where a key for this provider may be supplied in the environment."""
    if provider == DEFAULT_PROVIDER:
        return ("MODEL_API_KEY",)
    if provider in PROVIDER_KEY_ENVS:
        return PROVIDER_KEY_ENVS[provider]
    # A custom endpoint: its own name, and the original Meta name for compatibility.
    return (custom_key_env(provider), "MODEL_API_KEY")


def provider_key(provider: str, env: dict[str, str] | None = None, prefer_env: bool = False) -> str:
    env = dict(os.environ if env is None else env)
    keys = _read_credentials(credentials_path(env))
    names = _env_names(provider)
    if prefer_env:
        for name in names:
            if env.get(name):
                return env[name]
    if keys.get(provider):
        return keys[provider]
    if provider == DEFAULT_PROVIDER and keys.get("meta"):
        return keys["meta"]
    for name in names:
        if env.get(name):
            return env[name]
    return ""


def key_status(provider: str, env: dict[str, str] | None = None) -> dict:
    env = dict(os.environ if env is None else env)
    if _read_credentials(credentials_path(env)).get(provider):
        return {"configured": True, "source": "saved", "provider": provider}
    for name in _env_names(provider):
        if env.get(name):
            return {"configured": True, "source": "env", "provider": provider}
    return {"configured": False, "source": None, "provider": provider}


def shell_exports(effective: dict, env: dict[str, str], with_key: bool = False) -> str:
    values = {
        "ROCKET_MODEL": effective["model_ref"],
        "ROCKET_PROVIDER": effective["provider_id"],
        "ROCKET_MODEL_ID": effective["model_id"],
        "ROCKET_PROVIDER_TYPE": effective["provider_type"],
        "ROCKET_PROVIDER_NAME": effective["provider_name"],
        "ROCKET_BASE_URL": effective.get("base_url") or "",
        "ROCKET_SMALL_MODEL": effective["small_model"],
        "ROCKET_TUTOR_MODEL": effective["tutor_model"],
        "ROCKET_REVIEWER_MODEL": effective["reviewer_model"],
        "ROCKET_MODEL_CONFIG": effective["config_file"],
        "ROCKET_MODEL_CALL_LOG": effective["call_log"],
    }
    lines = [f"export {name}={shlex.quote(str(value))}" for name, value in values.items()]
    if with_key:
        # Every role may use a different provider, so inject each provider's own key. Keyless local servers
        # simply have none.
        refs = [effective["model_ref"], effective["small_model"], effective["tutor_model"], effective["reviewer_model"]]
        seen: set[str] = set()
        extra_providers = effective.get("providers") if isinstance(effective.get("providers"), dict) else {}
        for ref in refs:
            provider, _ = split_ref(ref)
            if provider in seen:
                continue
            seen.add(provider)
            if provider in KEYLESS_PROVIDERS:
                continue
            key = provider_key(provider, env)
            if not key:
                continue
            if provider == effective["provider_id"]:
                provider_type = effective["provider_type"]
            else:
                extra = extra_providers.get(provider) if isinstance(extra_providers.get(provider), dict) else {}
                provider_type = extra.get("provider_type") or ("native" if provider in NATIVE_PROVIDERS else "openai-compatible")
            for name in provider_env_names(provider, provider_type):
                lines.append(f"export {name}={shlex.quote(key)}")
    return "\n".join(lines) + "\n"


def write_config(path: Path, settings: dict) -> dict:
    found = _find_key(settings)
    if found:
        raise ConfigError(f"API keys must never be stored in the model configuration file ({found}).")
    provider = str(settings.get("provider_id") or "").strip()
    model = str(settings.get("model_id") or "").strip()
    base_url = clean_base_url(settings.get("base_url"))
    provider_type = canonical_type(provider, settings.get("provider_type"), base_url)
    if provider_type == "openai-compatible" and not base_url and provider != DEFAULT_PROVIDER:
        raise ConfigError("A base URL is required for an OpenAI-compatible provider.")
    if provider == DEFAULT_PROVIDER and not base_url:
        base_url = DEFAULT_BASE_URL

    saved = {
        "version": VERSION,
        "provider_id": provider,
        "model_id": model,
        "model_ref": model_ref(provider, model),
        "provider_type": provider_type,
        "base_url": base_url if provider_type == "openai-compatible" else None,
        "provider_name": str(settings.get("provider_name") or NATIVE_PROVIDERS.get(provider) or provider),
    }
    for key in ("small_model", "tutor_model", "reviewer_model"):
        value = settings.get(key)
        if value:
            saved[key] = value
        else:
            saved.pop(key, None)
    if isinstance(settings.get("models"), dict):
        saved["models"] = settings["models"]
    if settings.get("api_key_env"):
        saved["api_key_env"] = str(settings["api_key_env"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(saved, indent=2) + "\n")
    os.chmod(temporary, 0o644)
    os.replace(temporary, path)
    return saved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("path")
    show = sub.add_parser("show")
    show.add_argument("--json", action="store_true")
    shell = sub.add_parser("shell")
    shell.add_argument("--with-key", action="store_true")
    generate = sub.add_parser("generate")
    generate.add_argument("--base", default=str(Path(__file__).resolve().parents[1] / "harness" / "opencode.json"))
    generate.add_argument("--out", help="write here instead of stdout")
    export_key = sub.add_parser("export-key")
    export_key.add_argument("--provider", default=DEFAULT_PROVIDER)
    setter = sub.add_parser("set")
    setter.add_argument("--provider", required=True)
    setter.add_argument("--model", required=True)
    setter.add_argument("--type", choices=PROVIDER_TYPES)
    setter.add_argument("--base-url")
    setter.add_argument("--name")
    setter.add_argument("--small-model")
    setter.add_argument("--tutor-model")
    setter.add_argument("--reviewer-model")
    args = parser.parse_args(argv)

    try:
        if args.command == "path":
            print(config_path(dict(os.environ)))
        elif args.command == "show":
            effective = resolve()
            if args.json:
                print(json.dumps(effective, indent=2))
            else:
                print(f"provider  {effective['provider_name']} ({effective['provider_id']}, {effective['provider_type']})")
                if effective.get("base_url"):
                    print(f"base URL  {effective['base_url']}")
                print(f"model     {effective['model_ref']}")
                print(f"small     {effective['small_model']}")
                print(f"tutor     {effective['tutor_model']}")
                print(f"reviewer  {effective['reviewer_model']}")
                print(f"config    {effective['config_file']}")
        elif args.command == "shell":
            print(shell_exports(resolve(), dict(os.environ), args.with_key), end="")
        elif args.command == "generate":
            effective = resolve()
            base = json.loads(Path(args.base).read_text())
            text = json.dumps(opencode_config(effective, base), indent=2) + "\n"
            if args.out:
                Path(args.out).parent.mkdir(parents=True, exist_ok=True)
                Path(args.out).write_text(text)
            else:
                print(text, end="")
        elif args.command == "export-key":
            key = provider_key(args.provider, dict(os.environ))
            if not key:
                print(f"No API key is configured for {args.provider}.", file=sys.stderr)
                return 1
            print(key)
        elif args.command == "set":
            saved = write_config(config_path(dict(os.environ)), {
                "provider_id": args.provider, "model_id": args.model, "provider_type": args.type,
                "base_url": args.base_url, "provider_name": args.name,
                "small_model": args.small_model, "tutor_model": args.tutor_model,
                "reviewer_model": args.reviewer_model,
            })
            print(json.dumps(saved, indent=2))
    except ConfigError as exc:
        print(f"model config: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
