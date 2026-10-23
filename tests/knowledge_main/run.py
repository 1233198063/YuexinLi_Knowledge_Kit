"""
Run the mechanism test suites written in the companion repository (knowledge-main) against this solution.

    python tests/knowledge_main/run.py [-v]

The suites were copied unchanged from that repository at the commit in SOURCE_COMMIT (latest version of each
test family; earlier versions of the same family are listed in MANIFEST.md). They build tiny synthetic
snapshots and call only build() / ingest() / answer() / conflicts(), so they test behaviour, not code.
A few tests reach into that runtime's internal modules (common.Context, facts, its wrappers); stubs/ lets the
files import, and such tests show up as errors marked "internal API" - they are not applicable here.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SOLUTION = ROOT / "solution"

SUITES = [   # (family, folder, test module, how the file finds the runtime under test)
    ("program status", "program_status", "test_program_status", "env"),
    ("program status: qualified", "program_status", "test_qualified_programs", "env"),
    ("program status: notices", "program_status", "test_program_notice_variants", "env"),
    ("source planner", "source_planner", "test_iteration2b_frozen", "argv"),
]
# Not run, with the reason: they test that runtime's own wrapper layers, not behaviour through the contract.
NOT_APPLICABLE = {
    "fee/test_fee_mechanism.py": "compares its fee-fallback lane with its Parent runtime (build_parent)",
    "percent_display/test_percent_display.py": "unit tests of its percent_display module",
    "narrative/test_mechanism.py": "unit tests of its narrative_adapter module",
}
INTERNAL = re.compile(r"NotImplementedError: internal API|ImportError|ModuleNotFoundError|AttributeError: .*"
                      r"('(_\w+|contexts|_at|_spine|_base)'|has no attribute)")


def run(folder, module, mode):
    env = dict(os.environ, PYTHONPATH=str(HERE / "stubs"), PYTHONIOENCODING="utf-8",
               FEE_CANDIDATE=str(SOLUTION), EXPERIMENT_CANDIDATE=str(SOLUTION), PROGRAM_CANDIDATE=str(SOLUTION))
    cwd = HERE / "suites" / folder
    if mode == "argv":
        cmd = [sys.executable, f"{module}.py", "--submission", str(HERE / "adapter"), "-v"]
    else:
        cmd = [sys.executable, "-m", "unittest", "-v", module]
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = p.stdout + p.stderr
    ran = int((re.search(r"Ran (\d+) tests?", out) or re.search(r"(0)", "0")).group(1))
    fails = int((re.search(r"failures=(\d+)", out) or re.search(r"(0)", "0")).group(1))
    errors = int((re.search(r"errors=(\d+)", out) or re.search(r"(0)", "0")).group(1))
    blocks = re.split(r"\n(?==+\n(?:ERROR|FAIL): )", out)
    internal = sum(1 for b in blocks if b.lstrip("=\n").startswith("ERROR: ") and INTERNAL.search(b))
    if ran == 0:            # the file itself didn't import: every test is not applicable
        internal = errors = len(re.findall(r"def test_", (cwd / f"{module}.py").read_text(encoding="utf-8")))
    failed_names = re.findall(r"^(?:FAIL|ERROR): (\w+)", out, re.M)
    return ran, fails, errors, internal, failed_names, out


def main():
    verbose = "-v" in sys.argv
    total = [0, 0, 0, 0]
    print(f"{'suite':28s}{'tests':>7s}{'pass':>7s}{'fail':>7s}{'error':>7s}{'n/a':>7s}")
    for family, folder, module, mode in SUITES:
        ran, fails, errors, internal, names, out = run(folder, module, mode)
        tests = max(ran, errors)
        passed = tests - fails - errors
        print(f"{family:28s}{tests:>7d}{passed:>7d}{fails:>7d}{errors - internal:>7d}{internal:>7d}")
        total = [total[0] + tests, total[1] + passed, total[2] + fails, total[3] + errors - internal]
        if verbose:
            for n in names:
                print("      ", n)
    print(f"{'total':28s}{total[0]:>7d}{total[1]:>7d}{total[2]:>7d}{total[3]:>7d}")
    for f, why in NOT_APPLICABLE.items():
        n = len(re.findall(r"def test_", (HERE / "suites" / f).read_text(encoding="utf-8")))
        print(f"not applicable: {f} ({n} tests): {why}")


if __name__ == "__main__":
    main()
