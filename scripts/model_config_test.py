"""Tests for model_config.py, the one provider-neutral configuration.

Run: python3 -I scripts/model_config_test.py

No network and no real key: everything runs against temporary files.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import model_config  # noqa: E402

KEY = "sk-test-not-a-real-key-123456"

BASE = {
    "$schema": "https://opencode.ai/config.json",
    "agent": {
        "rocket-approval": {"mode": "primary", "prompt": "{file:./prompts/rocket-agent.md}"},
        "rocket-auto": {"mode": "primary", "prompt": "{file:./prompts/rocket-agent.md}"},
        "rocket-tutor": {"mode": "primary", "prompt": "{file:./prompts/rocket-tutor.md}"},
        "rocket-reviewer": {"mode": "primary", "prompt": "{file:./prompts/rocket-reviewer.md}",
                            "options": {"reasoningEffort": "high"}},
        "build": {"disable": True},
    },
    "permission": {"bash": "deny"},
}


class ModelConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.config_file = self.tmp / "model.json"
        self.env = {
            "ROCKET_CONFIG_HOME": str(self.tmp / "home"),
            "ROCKET_MODEL_CONFIG": str(self.config_file),
        }

    def resolve(self, **env):
        return model_config.resolve({**self.env, **env}, self.config_file)

    def generate(self, **env):
        return model_config.opencode_config(self.resolve(**env), BASE)

    # --- defaults and resolution -------------------------------------------------

    def test_meta_default_is_unchanged(self):
        effective = self.resolve()
        self.assertEqual(effective["model_ref"], "meta/muse-spark-1.3")
        self.assertEqual(effective["provider_type"], "openai-compatible")
        self.assertEqual(effective["base_url"], "https://api.meta.ai/v1")
        self.assertEqual(effective["provider_name"], "Meta Model API")
        self.assertEqual(effective["small_model"], "meta/muse-spark-1.3")
        self.assertEqual(effective["tutor_model"], "meta/muse-spark-1.3")
        self.assertEqual(effective["reviewer_model"], "meta/muse-wonder-1.0")

    def test_a_native_provider_needs_no_base_url(self):
        effective = self.resolve(ROCKET_MODEL="openai/gpt-5.1")
        self.assertEqual((effective["provider_type"], effective["base_url"]), ("native", None))
        self.assertEqual(effective["reviewer_model"], "openai/gpt-5.1")

    def test_an_unknown_provider_with_a_base_url_is_openai_compatible(self):
        effective = self.resolve(ROCKET_MODEL="house/house-model",
                                 ROCKET_BASE_URL="https://api.example.com/v1/",
                                 ROCKET_PROVIDER_TYPE="openai-compatible")
        self.assertEqual(effective["provider_type"], "openai-compatible")
        self.assertEqual(effective["base_url"], "https://api.example.com/v1")

    def test_an_openai_compatible_provider_without_a_base_url_is_refused(self):
        with self.assertRaises(model_config.ConfigError):
            self.resolve(ROCKET_MODEL="house/x", ROCKET_PROVIDER_TYPE="openai-compatible")

    def test_a_base_url_may_not_carry_credentials(self):
        with self.assertRaisesRegex(model_config.ConfigError, "credentials"):
            self.resolve(ROCKET_MODEL="house/x", ROCKET_PROVIDER_TYPE="openai-compatible",
                         ROCKET_BASE_URL="https://user:pass@example.com/v1")

    def test_model_ids_may_contain_slashes_but_providers_may_not(self):
        self.assertEqual(model_config.split_ref("openrouter/meta/llama-3.3"), ("openrouter", "meta/llama-3.3"))
        with self.assertRaises(model_config.ConfigError):
            model_config.split_ref("no-slash")
        with self.assertRaises(model_config.ConfigError):
            model_config.split_ref("bad provider/model")

    # --- generated OpenCode 1.19.5 configuration --------------------------------

    def test_the_generated_config_uses_singular_provider_and_enables_it(self):
        config = self.generate(ROCKET_MODEL="openai/gpt-5.1")
        self.assertIn("provider", config)
        self.assertNotIn("providers", config)
        self.assertEqual(config["model"], "openai/gpt-5.1")
        self.assertEqual(config["small_model"], "openai/gpt-5.1")
        self.assertEqual(config["enabled_providers"], ["openai"])
        # Native providers keep OpenCode's own integration; only the manually chosen model is declared.
        self.assertEqual(config["provider"]["openai"], {"models": {"gpt-5.1": {"name": "gpt-5.1"}}})

    def test_role_overrides_land_on_the_agents(self):
        config = self.generate(
            ROCKET_MODEL="anthropic/claude-sonnet-4-5",
            ROCKET_SMALL_MODEL="claude-haiku-4-5",
            ROCKET_TUTOR_MODEL="openai/gpt-5-mini",
            ROCKET_REVIEWER_MODEL="openai/gpt-5.1",
        )
        self.assertEqual(config["small_model"], "anthropic/claude-haiku-4-5")
        self.assertEqual(config["agent"]["rocket-approval"]["model"], "anthropic/claude-sonnet-4-5")
        self.assertEqual(config["agent"]["rocket-auto"]["model"], "anthropic/claude-sonnet-4-5")
        self.assertEqual(config["agent"]["rocket-tutor"]["model"], "openai/gpt-5-mini")
        self.assertEqual(config["agent"]["rocket-reviewer"]["model"], "openai/gpt-5.1")
        # A provider-specific reasoning option must not be handed to another provider.
        self.assertNotIn("options", config["agent"]["rocket-reviewer"])
        self.assertEqual(sorted(config["enabled_providers"]), ["anthropic", "openai"])
        self.assertNotIn("providers", config)

    def test_a_custom_endpoint_gets_the_openai_compatible_adapter_and_a_key_placeholder(self):
        config = self.generate(ROCKET_MODEL="house/house-model",
                               ROCKET_PROVIDER_TYPE="openai-compatible",
                               ROCKET_BASE_URL="https://api.example.com/v1",
                               ROCKET_PROVIDER_NAME="House API")
        block = config["provider"]["house"]
        self.assertEqual(block["name"], "House API")
        self.assertEqual(block["npm"], "@ai-sdk/openai-compatible")
        self.assertEqual(block["options"]["baseURL"], "https://api.example.com/v1")
        self.assertEqual(block["options"]["apiKey"], "{env:ROCKET_KEY_HOUSE}")
        self.assertIn("house-model", block["models"])
        # Nothing Meta is left in a non-Meta configuration.
        self.assertNotIn("meta", config["provider"])

    def test_meta_keeps_its_own_block_and_models(self):
        config = self.generate()
        self.assertEqual(config["provider"]["meta"]["options"]["apiKey"], "{env:MODEL_API_KEY}")
        self.assertEqual(config["provider"]["meta"]["options"]["baseURL"], "https://api.meta.ai/v1")
        self.assertIn("muse-wonder-1.0", config["provider"]["meta"]["models"])
        self.assertEqual(config["agent"]["rocket-reviewer"]["model"], "meta/muse-wonder-1.0")

    def test_a_saved_meta_base_url_still_wins_for_compatibility(self):
        config = self.generate(ROCKET_META_BASE_URL="http://127.0.0.1:8766/v1")
        self.assertEqual(config["provider"]["meta"]["options"]["baseURL"], "http://127.0.0.1:8766/v1")

    def test_the_generated_config_never_holds_a_key(self):
        model_config.save_credentials(self.tmp / "home" / "rocketide" / "credentials", "openai", KEY)
        config = self.generate(ROCKET_MODEL="openai/gpt-5.1")
        text = json.dumps(config)
        self.assertNotIn(KEY, text)
        for value in config["provider"].values():
            self.assertNotIn("api_key", value.get("options", {}))

    # --- saved configuration ----------------------------------------------------

    def test_a_saved_configuration_round_trips_and_the_file_has_no_secret(self):
        saved = model_config.write_config(self.config_file, {
            "provider_id": "house", "model_id": "house-model", "provider_type": "openai-compatible",
            "base_url": "https://api.example.com/v1", "provider_name": "House API",
            "tutor_model": "house-model-lite",
        })
        self.assertEqual(saved["model_ref"], "house/house-model")
        self.assertEqual(saved["provider_type"], "openai-compatible")
        on_disk = self.config_file.read_text()
        self.assertNotIn("api_key", on_disk)
        effective = self.resolve()
        self.assertEqual(effective["model_ref"], "house/house-model")
        self.assertEqual(effective["tutor_model"], "house/house-model-lite")
        self.assertEqual(effective["provider_name"], "House API")

    def test_an_exported_model_wins_over_the_saved_configuration(self):
        model_config.write_config(self.config_file, {"provider_id": "openai", "model_id": "gpt-5.1",
                                                     "provider_type": "native"})
        self.assertEqual(self.resolve()["model_ref"], "openai/gpt-5.1")
        self.assertEqual(self.resolve(ROCKET_MODEL="meta/muse-spark-1.3")["model_ref"], "meta/muse-spark-1.3")

    def test_provider_and_model_id_can_be_set_separately(self):
        effective = self.resolve(ROCKET_PROVIDER="deepseek", ROCKET_MODEL_ID="deepseek-chat")
        self.assertEqual(effective["model_ref"], "deepseek/deepseek-chat")

    def test_a_configuration_file_may_never_carry_a_key(self):
        for data in ({"provider_id": "openai", "model_id": "x", "api_key": KEY},
                     {"provider_id": "openai", "model_id": "x", "providers": {"openai": {"apiKey": KEY}}}):
            self.config_file.write_text(json.dumps(data))
            with self.assertRaisesRegex(model_config.ConfigError, "never be stored"):
                self.resolve()
        with self.assertRaisesRegex(model_config.ConfigError, "never be stored"):
            model_config.write_config(self.config_file, {"provider_id": "openai", "model_id": "x", "api_key": KEY})

    # --- credentials ------------------------------------------------------------

    def credentials(self):
        return model_config.credentials_path(self.env)

    def test_the_original_MODEL_API_KEY_file_reads_as_the_meta_key(self):
        path = self.credentials()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"MODEL_API_KEY={KEY}\n")
        self.assertEqual(model_config.provider_key("meta", self.env), KEY)
        self.assertEqual(model_config.key_status("meta", self.env)["source"], "saved")

    def test_keys_are_separate_per_provider_and_env_can_win_for_the_launcher(self):
        model_config.save_credentials(self.credentials(), "meta", KEY)
        model_config.save_credentials(self.credentials(), "openai", "sk-openai-test-123456")
        self.assertEqual(model_config.provider_key("meta", self.env), KEY)
        self.assertEqual(model_config.provider_key("openai", self.env), "sk-openai-test-123456")
        env = {**self.env, "OPENAI_API_KEY": "sk-from-environment"}
        self.assertEqual(model_config.provider_key("openai", env, prefer_env=True), "sk-from-environment")
        self.assertEqual(model_config.provider_key("openai", env), "sk-openai-test-123456")

    def test_a_custom_endpoint_key_can_come_from_its_own_environment_name(self):
        env = {**self.env, "ROCKET_KEY_HOUSE": "sk-house-test-123456"}
        self.assertEqual(model_config.provider_key("house", env), "sk-house-test-123456")
        self.assertEqual(model_config.key_status("house", env)["source"], "env")
        # MODEL_API_KEY is still accepted, so existing .env files keep working.
        self.assertEqual(model_config.provider_key("house", {**self.env, "MODEL_API_KEY": KEY}), KEY)

    def test_status_never_contains_the_key(self):
        model_config.save_credentials(self.credentials(), "meta", KEY)
        self.assertNotIn(KEY, json.dumps(model_config.key_status("meta", self.env)))

    def test_shell_exports_never_print_the_key_unless_asked(self):
        model_config.save_credentials(self.credentials(), "openai", "sk-openai-test-123456")
        env = {**self.env, "ROCKET_MODEL": "openai/gpt-5.1"}
        text = model_config.shell_exports(model_config.resolve(env, self.config_file), env)
        self.assertNotIn("sk-openai-test-123456", text)
        self.assertIn("ROCKET_MODEL=openai/gpt-5.1", text)
        with_key = model_config.shell_exports(model_config.resolve(env, self.config_file), env, with_key=True)
        self.assertIn("OPENAI_API_KEY=sk-openai-test-123456", with_key)
        self.assertNotIn("MODEL_API_KEY", with_key)

    def test_a_custom_compatible_provider_exports_its_own_key_variable(self):
        model_config.save_credentials(self.credentials(), "house", "sk-house-test-123456")
        env = {**self.env, "ROCKET_MODEL": "house/house-model", "ROCKET_PROVIDER_TYPE": "openai-compatible",
               "ROCKET_BASE_URL": "https://api.example.com/v1"}
        text = model_config.shell_exports(model_config.resolve(env, self.config_file), env, with_key=True)
        self.assertIn("ROCKET_KEY_HOUSE=sk-house-test-123456", text)
        self.assertNotIn("MODEL_API_KEY=sk-house-test-123456", text)

    def test_every_role_provider_gets_its_key_without_overwriting_another(self):
        model_config.save_credentials(self.credentials(), "meta", KEY)
        model_config.save_credentials(self.credentials(), "anthropic", "sk-anthropic-test-123456")
        env = {**self.env, "ROCKET_MODEL": "meta/muse-spark-1.3",
               "ROCKET_REVIEWER_MODEL": "anthropic/claude-sonnet-4-5"}
        text = model_config.shell_exports(model_config.resolve(env, self.config_file), env, with_key=True)
        self.assertIn(f"MODEL_API_KEY={KEY}", text)
        self.assertIn("ANTHROPIC_API_KEY=sk-anthropic-test-123456", text)


if __name__ == "__main__":
    unittest.main()
