"""Fetch verified Phonon assets without importing Hermes or opening a device."""
import importlib
import importlib.machinery
import importlib.util
from pathlib import Path
import runpy
import sys

if __name__ == "__main__":
    spec = importlib.machinery.ModuleSpec("_gaze_speech_setup", None, is_package=True)
    spec.submodule_search_locations = [str(Path(__file__).resolve().parents[1])]
    sys.modules[spec.name] = importlib.util.module_from_spec(spec)
    runpy.run_module(f"{spec.name}.speech", run_name="__main__")
