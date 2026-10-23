"""The runtime the copied suites under suites/*/ load as ROOT/'submission'/solution.py: this solution's build()."""
import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(_ROOT / "solution"), str(_ROOT / "harness")]
_spec = importlib.util.spec_from_file_location("_kit_solution", _ROOT / "solution" / "solution.py")
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)
build = _module.build
