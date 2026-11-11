"""Offline checks for captured consent and disposable inference credentials."""
import json
import os
from pathlib import Path
import sys
import builtins
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from look.runtime.native_input import consent
from look.benchmark.probe_profile import prepare_profile, profile_config
from look.benchmark import probe_companion_ui, probe_sessions


class ProbeBoundaries(unittest.TestCase):
    def loader(self):
        return SimpleNamespace(safe_load=json.loads, safe_dump=json.dumps)

    def test_stock_hermes_loader_needs_no_pyyaml(self):
        try:
            import hermes_yaml
        except ImportError:
            self.skipTest("Stock Hermes is not installed in this interpreter")
        real_import = builtins.__import__

        def without_pyyaml(name, *args, **kwargs):
            if name == "yaml" or name.startswith("yaml."):
                raise ImportError("PyYAML is intentionally unavailable")
            return real_import(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "config.yaml").write_text(
                "plugins:\n  entries:\n    look:\n      allow_gateway_injection: true\n")
            with patch("builtins.__import__", side_effect=without_pyyaml):
                self.assertTrue(consent(home, "look"))
            (home / "config.yaml").write_text("plugins: [")
            self.assertFalse(consent(home, "look"))


    def test_captured_consent_reread_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / "config.yaml"
            with patch.dict(sys.modules, {"hermes_yaml": self.loader()}), patch.dict(
                    os.environ, {"HERMES_HOME": str(home / "other-profile")}):
                def write(grant=True, **extra):
                    path.write_text(json.dumps({"plugins": {"entries": {"look": {
                        "allow_gateway_injection": grant}}, **extra}}))
                write()
                self.assertTrue(consent(home, "look"))
                self.assertFalse(consent(home, "other-plugin"))
                for grant in (False, "true", 1, None):
                    write(grant)
                    self.assertFalse(consent(home, "look"))
                write(isolation="subprocess")
                self.assertFalse(consent(home, "look"))
                for malformed in ("[", "[]", '{"plugins": []}', '{"plugins": {"entries": []}}'):
                    path.write_text(malformed)
                    self.assertFalse(consent(home, "look"))
                write()
                self.assertTrue(consent(home, "look"))
                path.unlink()
                self.assertFalse(consent(home, "look"))
            with patch.dict(sys.modules, {"hermes_yaml": None}):
                self.assertFalse(consent(home, "look"))

    def test_profile_uses_only_test_key_and_selected_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "account", root / "probe"
            source.mkdir()
            original = {"model": {"default": "test-model", "provider": "openrouter",
                                  "base_url": "https://openrouter.ai/api/v1", "api_key": "account-secret",
                                  "key_cmd": "do-not-run", "extra_headers": {"Authorization": "secret"}},
                        "providers": {"private": {"api_key": "secret"}}, "mcp_servers": {"secret": {}},
                        "fallback_model": "account-model"}
            (source / "config.yaml").write_text(json.dumps(original))
            for name in (".env", "auth.json"):
                (source / name).write_text("account-secret")
            modules = {"hermes_yaml": self.loader(),
                       "hermes_constants": SimpleNamespace(get_hermes_home=lambda: source,
                                                            __file__=str(root / "hermes_constants.py")),
                       "hermes_cli": ModuleType("hermes_cli"),
                       "hermes_cli.auth": SimpleNamespace(PROVIDER_REGISTRY={"openrouter": SimpleNamespace(
                           auth_type="api_key", api_key_env_vars=("OPENROUTER_API_KEY",))})}
            with patch.dict(sys.modules, modules), patch.dict(os.environ, {
                    "LOOK_PROBE_API_KEY": "test-only-key", "OPENROUTER_API_KEY": "account-secret",
                    "ANTHROPIC_API_KEY": "account-secret", "PYTHONPATH": "untrusted", "HERMES_HOME": str(source)}, clear=True):
                config, env = prepare_profile(target, plugin_id="look", settings={"cdp_url": "http://127.0.0.1:9222"})
            self.assertEqual(config["model"], {"default": "test-model", "provider": "openrouter",
                             "base_url": "https://openrouter.ai/api/v1", "key_env": "LOOK_PROBE_API_KEY"})
            self.assertNotIn("account-secret", json.dumps((config, env)))
            self.assertNotIn("test-only-key", (target / "config.yaml").read_text())
            self.assertEqual(env["OPENROUTER_API_KEY"], "test-only-key")
            self.assertEqual(env["LOOK_PROBE_API_KEY"], "test-only-key")
            self.assertNotIn("ANTHROPIC_API_KEY", env)
            self.assertEqual(env["HOME"], str(target))
            self.assertEqual(set(p.name for p in target.iterdir()), {"config.yaml"})
            self.assertEqual((target / "config.yaml").stat().st_mode & 0o777, 0o600)
            self.assertEqual(config["mcp_servers"], {})
            self.assertIsNone(config["fallback_model"])

    def test_harnesses_refuse_missing_key_before_launch(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "account-secret"}, clear=True), patch("subprocess.Popen") as launch:
            for harness in (probe_sessions, probe_companion_ui):
                with self.subTest(harness=harness.__name__), self.assertRaisesRegex(ValueError, "LOOK_PROBE_API_KEY"):
                    harness.run(SimpleNamespace(plugin_root=None))
            launch.assert_not_called()

    def test_secret_bearing_endpoint_rejected(self):
        for url in ("https://user:secret@example.com/v1", "https://example.com?key=secret", "https://example.com#secret"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                profile_config({"model": {"default": "model", "base_url": url}}, plugin_id="look", settings={})


if __name__ == "__main__":
    unittest.main()
