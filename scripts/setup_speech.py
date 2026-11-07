"""Fetch pinned Phonon assets without importing Hermes or opening an audio device."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "speech.py"), run_name="__main__")
