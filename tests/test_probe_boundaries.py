"""Offline checks for captured consent and disposable inference credentials."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr
import builtins
import io
import json
import logging
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from look.runtime.native_input import consent
from look.benchmark.probe_profile import prepare_profile, profile_config
from look.benchmark import probe_companion_ui, probe_sessions


def grant(value=True):
    return {"plugins": {"entries": {"look": {"allow_gateway_injection": value}}}}


class ProbeBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from hermes_cli.config import read_config_doc
            from providers import bundled_profiles
        except ImportError:
            raise unittest.SkipTest("Stock Hermes is not installed in this interpreter")
        cls.read_doc = staticmethod(read_config_doc)
        cls.profiles = bundled_profiles()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.path = self.source / "config.yaml"
        self.target = self.root / "probe"
        self.env = patch.dict(os.environ, {"LOOK_PROBE_API_KEY": "test-only-key",
                                          "HERMES_HOME": str(self.source), "HERMES_CONFIG_BACKEND": "file"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def write(self, config):
        self.path.write_text(json.dumps(config))

    def prepare(self, provider="openrouter", **model):
        self.write({"model": {"default": "test-model", "provider": provider, **model}})
        return prepare_profile(self.target, plugin_id="look", settings={})

    def test_concurrent_captured_profiles_ignore_ambient_home(self):
        other = self.root / "other"
        other.mkdir()
        self.write(grant())
        (other / "config.yaml").write_text(json.dumps(grant(False)))
        with patch.dict(os.environ, {"HERMES_HOME": str(other)}), ThreadPoolExecutor(max_workers=8) as pool:
            homes = [self.source, other] * 32
            self.assertEqual(list(pool.map(lambda h: consent(h, "look"), homes)), [True, False] * 32)

    def test_strict_grants_shapes_and_live_revocation(self):
        self.write(grant())
        self.assertTrue(consent(self.source, "look"))
        self.assertFalse(consent(self.source, "another-plugin"))
        stamp = self.path.stat()
        # Same-size rewrite with the original mtime must not retain authority.
        self.path.write_text(self.path.read_text().replace("true", "null"))
        os.utime(self.path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.assertFalse(consent(self.source, "look"))
        for value in (False, "true", 1, None, [], {}):
            self.write(grant(value))
            self.assertFalse(consent(self.source, "look"))
        for config in ([], None, {"plugins": []}, {"plugins": "bad"},
                       {"plugins": {"entries": []}}, {"plugins": {"entries": {"look": []}}},
                       {"plugins": {"entries": {"look": None}}}):
            self.write(config)
            self.assertFalse(consent(self.source, "look"))
        for isolation in ("host", "subprocess", None, True):
            config = grant()
            config["plugins"]["isolation"] = isolation
            self.write(config)
            self.assertFalse(consent(self.source, "look"))
        self.write(grant())
        self.assertTrue(consent(self.source, "look"))
        self.path.unlink()
        self.assertFalse(consent(self.source, "look"))

    def test_malformed_and_duplicate_reads_are_quiet_and_do_not_write(self):
        stderr, logs = io.StringIO(), io.StringIO()
        handler = logging.StreamHandler(logs)
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        for text in ("plugins: [PRIVATE_SENTINEL", "private: PRIVATE_SENTINEL\nprivate: duplicate"):
            self.path.write_text(text)
            before = set(self.root.rglob("*"))
            with redirect_stderr(stderr):
                self.assertFalse(consent(self.source, "look"))
                with self.assertRaises(Exception):
                    prepare_profile(self.target, plugin_id="look", settings={})
            self.assertEqual(self.path.read_text(), text)
            self.assertEqual(set(self.root.rglob("*")), before)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(logs.getvalue(), "")

    def test_nonfile_and_unavailable_backends_refuse_without_reading(self):
        self.write(grant())
        with patch("hermes_cli.config.get_config_backend", return_value=SimpleNamespace(name="remote")), patch(
                "hermes_cli.config.read_config_doc") as read:
            self.assertFalse(consent(self.source, "look"))
            with self.assertRaises(ValueError):
                prepare_profile(self.target, plugin_id="look", settings={})
            read.assert_not_called()
        with patch.dict(os.environ, {"HERMES_CONFIG_BACKEND": "invalid-look-test"}):
            self.assertFalse(consent(self.source, "look"))
            with self.assertRaises(ValueError):
                prepare_profile(self.target, plugin_id="look", settings={})

    def test_profile_uses_only_test_key_and_roundtrips_strings(self):
        selected = {"default": "yes\\model 雪", "provider": "openrouter", "base_url": "https://example.com/v1"}
        original = {"model": {**selected, "api_key": "account-secret", "key_cmd": "do-not-run",
                              "extra_headers": {"Authorization": "secret"}},
                    "providers": {"private": {"api_key": "secret"}}, "mcp_servers": {"secret": {}},
                    "fallback_model": "account-model"}
        self.write(original)
        for name in (".env", "auth.json"):
            (self.source / name).write_text("account-secret")
        settings = {"literal": "yes", "unicode": "雪", "path": "C:\\test\\no"}
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "account-secret", "ANTHROPIC_API_KEY": "account-secret",
                                     "PYTHONPATH": "untrusted"}):
            config, env = prepare_profile(self.target, plugin_id="look", settings=settings)
        self.assertEqual(config["model"], {**selected, "key_env": "LOOK_PROBE_API_KEY"})
        self.assertEqual(self.read_doc(self.target / "config.yaml"), config)
        self.assertEqual(json.loads((self.target / "config.yaml").read_text()), config)
        self.assertEqual(config["plugins"]["entries"]["look"]["settings"], settings)
        self.assertNotIn("account-secret", json.dumps((config, env)))
        self.assertNotIn("test-only-key", (self.target / "config.yaml").read_text())
        self.assertEqual(env["OPENROUTER_API_KEY"], "test-only-key")
        self.assertEqual(env["LOOK_PROBE_API_KEY"], "test-only-key")
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertEqual(env["HOME"], str(self.target))
        self.assertEqual(env["HERMES_HOME"], str(self.target))
        self.assertEqual(set(p.name for p in self.target.iterdir()), {"config.yaml"})
        self.assertEqual((self.target / "config.yaml").stat().st_mode & 0o777, 0o600)
        self.assertEqual(config["mcp_servers"], {})
        self.assertIsNone(config["fallback_model"])
        self.assertEqual(set(config), {"model", "plugins", "mcp_servers", "fallback_model"})
        self.assertEqual(self.path.read_text(), json.dumps(original))

    def test_stock_provider_matrix(self):
        plugin = self.source / "plugins" / "model-providers" / "source-only-plugin"
        plugin.mkdir(parents=True)
        marker = self.source / "provider-executed"
        (plugin / "__init__.py").write_text(
            "from pathlib import Path\nfrom providers import register_provider\n"
            "from providers.base import ProviderProfile\n"
            f"Path({str(marker)!r}).touch()\n"
            "register_provider(ProviderProfile(name='source-only-plugin'))\n")
        alias_profile = next(p for p in self.profiles if p.aliases and (p.registry_auth_type or p.auth_type) == "api_key")
        for name, canonical, env_name in (("openai-api", "openai-api", "OPENAI_API_KEY"),
                                          ("openrouter", "openrouter", "OPENROUTER_API_KEY"),
                                          ("auto", "openrouter", "OPENROUTER_API_KEY"),
                                          (alias_profile.aliases[0], alias_profile.name, alias_profile.env_vars[0]),
                                          ("custom", "custom", "LOOK_PROBE_API_KEY")):
            with self.subTest(provider=name):
                config, env = self.prepare(name, **({"base_url": "https://example.com/v1"} if name == "custom" else {}))
                self.assertEqual(config["model"]["provider"], canonical)
                self.assertEqual(env[env_name], "test-only-key")
        rejected = [p.name for p in self.profiles if (p.registry_auth_type or p.auth_type) != "api_key"]
        for name in [*rejected, "unknown", "source-only-plugin", "openai"]:
            with self.subTest(provider=name), self.assertRaises(ValueError):
                self.prepare(name)
        self.assertFalse(marker.exists(), "Source-home provider code executed")
        with self.assertRaisesRegex(ValueError, "base_url"):
            self.prepare("custom")
        # Canonicalize an alias before applying custom's mandatory endpoint rule.
        from providers.base import ProviderProfile
        with patch("providers.bundled_profiles", return_value=[ProviderProfile(name="custom", aliases=("my-custom",))]):
            with self.assertRaisesRegex(ValueError, "base_url"):
                self.prepare("my-custom")

    def test_effective_auth_override_and_endpoint_env_exclusion(self):
        from providers.base import ProviderProfile
        for auth, override, allowed in (("api_key", "oauth_device_code", False),
                                         ("plugin-defined", "api_key", True),
                                         ("api_key", "", True), ("external_process", "", False),
                                         ("aws_sdk", "", False)):
            p = ProviderProfile(name="fixture", aliases=("fixture-alias",), auth_type=auth,
                                registry_auth_type=override, env_vars=("FIXTURE_API_KEY", "FIXTURE_URL", "FIXTURE_BASE_URL", "ENDPOINT"),
                                base_url_env_var="ENDPOINT")
            with self.subTest(auth=auth, override=override), patch("providers.bundled_profiles", return_value=[p]):
                if allowed:
                    config, env = self.prepare("fixture-alias")
                    self.assertEqual(config["model"]["provider"], "fixture")
                    self.assertEqual(env["FIXTURE_API_KEY"], "test-only-key")
                    for name in ("FIXTURE_URL", "FIXTURE_BASE_URL", "ENDPOINT"):
                        self.assertNotIn(name, env)
                else:
                    with self.assertRaises(ValueError):
                        self.prepare("fixture-alias")
        for p in self.profiles:
            if (p.registry_auth_type or p.auth_type) == "api_key" and p.name != "custom":
                _, env = self.prepare(p.name)
                for name in p.env_vars:
                    if name.endswith(("_URL", "_BASE_URL")) or name == p.base_url_env_var:
                        self.assertNotIn(name, env)


class ProbeEarlyRefusal(unittest.TestCase):
    def test_harnesses_refuse_missing_key_before_import_or_launch(self):
        real_import = builtins.__import__

        def no_hermes(name, *args, **kwargs):
            if name.startswith(("hermes", "providers")):
                self.fail("Imported Hermes before checking the dedicated credential")
            return real_import(name, *args, **kwargs)

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "account-secret"}, clear=True), patch(
                "subprocess.Popen") as launch, patch("builtins.__import__", side_effect=no_hermes):
            for harness in (probe_sessions, probe_companion_ui):
                with self.subTest(harness=harness.__name__), self.assertRaisesRegex(ValueError, "LOOK_PROBE_API_KEY"):
                    harness.run(SimpleNamespace(plugin_root=None))
            with self.assertRaisesRegex(ValueError, "LOOK_PROBE_API_KEY"):
                prepare_profile(Path("/unused"), plugin_id="look", settings={})
            launch.assert_not_called()

    def test_secret_bearing_endpoint_rejected(self):
        for url in ("https://user:secret@example.com/v1", "https://example.com?key=secret", "https://example.com#secret"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                profile_config({"model": {"default": "model", "base_url": url}}, plugin_id="look", settings={})


if __name__ == "__main__":
    unittest.main()
