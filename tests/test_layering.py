"""Structural invariants for the hermes-gaze package (post-refactor layering contract).

1. No absolute self-imports inside the package: Hermes loads this plugin as
   ``hermes_plugins.hermes_gaze``, so ``import hermes_gaze`` inside a source file
   executes a SECOND copy of the package — the split-brain bug this refactor removed.
   Only ``from .x import y`` relative imports are allowed. (tests/ is exempt: its
   bootstrap registers a hermes_gaze package *shell* under that sys.modules name.)
2. resolver/ and tracker/ stay pure: no I/O or sibling-layer imports — all Chrome,
   HTTP, process, and voice plumbing lives in browser/, service.py, voice.py, server.py.
3. Removed pre-refactor symbols stay gone: get_shared_bridge, CDPBridge, voice_listener,
   HERMES_GAZE_INTERNAL, _ensure_package_importable.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Iterator, List, Tuple

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_SKIP_DIRS = {
    "tests", "benchmark", "docs", "skills", "__pycache__", ".git",
    # Virtualenvs hold foreign code (some non-UTF-8 test fixtures like joblib's);
    # PM creates .venv on `hermes pm install`.
    ".venv", "venv", "env", ".env", "ENV", ".hermes",
}
_PURE_DIRS = {"resolver", "tracker"}

_ABS_SELF_IMPORT = re.compile(r"^\s*(?:import|from)\s+hermes_gaze\b")
_IMPORT_STMT = re.compile(r"^\s*(?:from\s+([.\w]+)\s+)?import\s+(.+)")
_BANNED_MODULE = re.compile(
    r"^\.{0,2}(?:websockets|urllib|subprocess|socket|http\.server|server|service|browser)(?:\.|$)"
)
_REMOVED_SYMBOLS = re.compile(
    r"get_shared_bridge|CDPBridge|voice_listener|HERMES_GAZE_INTERNAL|_ensure_package_importable"
)


def _source_files() -> List[Path]:
    return sorted(
        p
        for p in PLUGIN_ROOT.rglob("*.py")
        if not (set(p.relative_to(PLUGIN_ROOT).parts) & _SKIP_DIRS)
    )


def _logical_lines(text: str) -> Iterator[Tuple[int, str]]:
    """Yield (lineno, code) with parenthesized import lists joined and comments stripped."""
    joined = re.sub(r"\(([^)]*)\)", lambda m: m.group(1).replace("\n", " "), text)
    for lineno, raw in enumerate(joined.splitlines(), start=1):
        yield lineno, raw.split("#", 1)[0]


def _imported_module_tokens(line: str) -> List[str]:
    """Module tokens an import statement pulls in ('from . import service' included)."""
    m = _IMPORT_STMT.match(line)
    if not m:
        return []
    base, names_blob = m.group(1), m.group(2)
    names = [
        part.split(" as ", 1)[0].strip()
        for part in names_blob.split(",")
        if part.split(" as ", 1)[0].strip()
    ]
    if base is None:
        return names  # 'import a, b' — every name is a module
    tokens = [base]
    if base.startswith("."):
        tokens.extend(names)  # 'from . import name' imports a sibling module by name
    return tokens


class TestLayering(unittest.TestCase):
    def test_no_absolute_self_imports(self) -> None:
        violations = []
        for path in _source_files():
            for lineno, line in _logical_lines(path.read_text(encoding="utf-8")):
                if _ABS_SELF_IMPORT.match(line):
                    violations.append(f"{path.relative_to(PLUGIN_ROOT)}:{lineno}: {line.strip()}")
        self.assertEqual(violations, [])

    def test_resolver_and_tracker_are_pure(self) -> None:
        violations = []
        for path in _source_files():
            if path.relative_to(PLUGIN_ROOT).parts[0] not in _PURE_DIRS:
                continue
            for lineno, line in _logical_lines(path.read_text(encoding="utf-8")):
                for token in _imported_module_tokens(line):
                    if _BANNED_MODULE.match(token):
                        violations.append(
                            f"{path.relative_to(PLUGIN_ROOT)}:{lineno}: {line.strip()}"
                        )
                        break
        self.assertEqual(violations, [])

    def test_removed_symbols_stay_gone(self) -> None:
        violations = []
        for path in _source_files():
            for match in _REMOVED_SYMBOLS.finditer(path.read_text(encoding="utf-8")):
                violations.append(
                    f"{path.relative_to(PLUGIN_ROOT)}: '{match.group(0)}'"
                )
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
