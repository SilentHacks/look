"""Test bootstrap for hermes-gaze.

The plugin directory is named ``hermes-gaze`` (hyphenated — Hermes loads it by
path, not by package name), so ``import hermes_gaze`` cannot resolve normally.
This registers a package *shell* without executing ``__init__.py`` (the same
shape Hermes's own ``register_synthetic_package`` produces), so submodule
imports like ``from hermes_gaze.resolver.bayesian_fusion import ...`` work in
tests exactly as they do inside Hermes. Runs for both unittest and pytest.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_PKG_NAME = "hermes_gaze"

if _PKG_NAME not in sys.modules:
    spec = importlib.machinery.ModuleSpec(_PKG_NAME, None, is_package=True)
    spec.submodule_search_locations = [str(_PLUGIN_ROOT)]
    sys.modules[_PKG_NAME] = importlib.util.module_from_spec(spec)
