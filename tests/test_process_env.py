"""Real children receive runtime essentials, never ambient credentials or injection."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from look.process_env import minimal_env


class ProcessEnvironmentTests(unittest.TestCase):
    def test_real_child_receives_only_explicit_runtime_values(self):
        with tempfile.TemporaryDirectory() as directory:
            required = {"PATH": os.environ.get("PATH", os.defpath), "HOME": directory,
                        "TMPDIR": directory, "LANG": "C", "LC_ALL": "C", "LC_CTYPE": "C",
                        "LANGUAGE": "en", "LC_TIME": "C"}
            desktop = {"DISPLAY": ":99", "WAYLAND_DISPLAY": "wayland-0", "XAUTHORITY": directory + "/auth",
                       "XDG_RUNTIME_DIR": directory, "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + directory + "/bus"}
            forbidden = dict.fromkeys((
                "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY",
                "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH",
                "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT",
                "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy",
                "NEMO_SPEECH_MODEL", "LC_SECRET", "UNRECOGNIZED_FUTURE_SECRET",
            ), "must-not-reach-child")
            with patch.dict(os.environ, required | desktop | forbidden, clear=True):
                for platform, use_desktop in (("linux", False), ("linux", True), ("darwin", True)):
                    with self.subTest(platform=platform, desktop=use_desktop), patch("sys.platform", platform):
                        child = subprocess.run(
                            [sys.executable, "-c", "import json, os; print(json.dumps(dict(os.environ)))"],
                            env=minimal_env(desktop=use_desktop), capture_output=True, text=True,
                            check=True, timeout=10,
                        )
                        received = json.loads(child.stdout)
                        self.assertTrue(forbidden.keys().isdisjoint(received))
                        self.assertEqual({key: received.get(key) for key in required}, required)
                        expected_desktop = desktop if platform == "linux" and use_desktop else {}
                        self.assertEqual({key: received[key] for key in desktop if key in received}, expected_desktop)


if __name__ == "__main__":
    unittest.main()
