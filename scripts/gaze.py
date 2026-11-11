"""Repository-root entry point; loads the plugin package without registration hooks."""
import importlib
import importlib.machinery
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.machinery.ModuleSpec("look", None, is_package=True)
spec.submodule_search_locations = [str(ROOT)]
sys.modules[spec.name] = importlib.util.module_from_spec(spec)
COMMANDS = {"record": "gaze_record", "eval": "gaze_eval", "tune": "gaze_tuning", "data": "gaze_dataset",
            "research": "gaze_research", "research-safety": "gaze_research_safety"}
if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
    raise SystemExit("Usage: .venv/bin/python scripts/gaze.py {record,eval,tune,data,research,research-safety} --help")
module = COMMANDS[sys.argv.pop(1)]
importlib.import_module(f"look.benchmark.{module}").main()
