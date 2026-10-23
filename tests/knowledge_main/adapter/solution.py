"""This solution under the build() flags the companion suites pass (they switch lanes of the other runtime,
e.g. enable_request_planner=True). The flags are accepted and ignored: the tests then check behaviour only."""
import importlib.util
import sys
from pathlib import Path

SOLUTION = Path(__file__).resolve().parents[3] / "solution"
sys.path.insert(0, str(SOLUTION))
_spec = importlib.util.spec_from_file_location("solution_under_test", SOLUTION / "solution.py")
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)


def build(**flags):
    return _mod.build()
