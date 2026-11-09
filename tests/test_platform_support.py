"""Platform decisions only: no host, network, native model or device loading."""
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import tomllib
import unittest
from unittest.mock import Mock, patch

from packaging.requirements import Requirement
from hermes_gaze import cli, platform_support, voice


class PlatformSupport(unittest.TestCase):
    def platform(self, system, machine):
        stack = ExitStack()
        stack.enter_context(patch.object(platform_support.platform, "system", return_value=system))
        stack.enter_context(patch.object(platform_support.platform, "machine", return_value=machine))
        return stack

    def test_beta_classification_matches_apple_dependency_eligibility(self):
        dependencies = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())["project"]["dependencies"]
        apple_deps = [Requirement(dep) for dep in dependencies
                      if Requirement(dep).name in ("parakeet-mlx", "pyobjc-framework-CoreML")]
        for system, machine, sys_platform, beta in (
            ("Darwin", "arm64", "darwin", True),
            ("Darwin", "x86_64", "darwin", False),  # Intel or Rosetta Python
            ("Linux", "aarch64", "linux", False),
            ("Linux", "x86_64", "linux", False),
            ("Windows", "AMD64", "win32", False),
        ):
            with self.subTest(system=system, machine=machine), self.platform(system, machine):
                self.assertEqual(platform_support.apple_silicon_mac(), beta)
                self.assertEqual(bool(platform_support.platform_notice()), not beta)
                for dep in apple_deps:
                    self.assertEqual(dep.marker.evaluate({"sys_platform": sys_platform, "platform_machine": machine}), beta)
                if not beta:
                    with patch.object(voice, "prepare") as prepare:
                        self.assertIsNone(voice._get_coreml_runner())
                        self.assertIsNone(voice._get_parakeet_model())
                        prepare.assert_not_called()

    def test_setup_fences_unverified_platforms_without_disabling_whisper(self):
        for system in ("Darwin", "Linux", "Windows"):
            with self.subTest(system=system), self.platform(system, "x86_64"), \
                 patch.object(voice, "prepare_recognition") as prepare, \
                 patch.object(voice, "recognition_status", return_value="pending"), \
                 patch.object(cli, "_missing_modules", return_value=[]), \
                 patch.object(cli.Path, "is_file", return_value=True):
                result = cli._first_run_guide(SimpleNamespace(cdp=SimpleNamespace(is_connected=False)))
                self.assertIn(platform_support.platform_notice(), result)
                if system == "Windows":
                    prepare.assert_not_called()
                else:
                    prepare.assert_called_once()
                    self.assertIn("~148 MB", result)

    def test_linux_start_keeps_cursor_path_and_discloses_unverified_lane(self):
        session, server = Mock(), Mock()
        with self.platform("Linux", "x86_64"), \
             patch.object(cli, "get_shared_session", return_value=session), \
             patch.object(cli, "get_shared_server", return_value=server):
            result = cli._handle_slash_command("start")
            session.cdp.start.assert_called_once()
            self.assertIn(platform_support.platform_notice(), result)

    def test_unverified_camera_command_preserves_cursor_before_configuration(self):
        session = Mock()
        with self.platform("Linux", "x86_64"), \
             patch.object(cli, "get_shared_session", return_value=session):
            result = cli._handle_slash_command("setup eyes")
            self.assertIn("eye tracking is unavailable", result)
            session.configure.assert_not_called()
            session.start_webcam.assert_not_called()


if __name__ == "__main__":
    unittest.main()
