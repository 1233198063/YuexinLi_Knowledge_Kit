"""
One command for every evaluation layer, scored by the unchanged organizer harness:

    python tests/scoreboard.py [--holdout] [--label NAME]

Layers (see METHODOLOGY.md for why each exists):
  checks    tests/run_checks.py         paraphrases, review cases, mutation tests (pass/fail counts)
  public    eval/public_eval.jsonl      the organizer's 40 (ceiling 0.969 without the LLM judge)
  selftest  harness/selftest            the organizer's contract test, with its conflict gold
  sim       tests/sim_eval.jsonl        our own stand-in for the hidden set (written by us: optimistic)
  dev       independent dev, 226 q      written by a separate test author; used for debugging
  holdout   independent holdout, 176 q  same author, never opened: --holdout prints aggregates only

Each layer prints the organizer pillars (accuracy, conflicts, consistency, speed) and the total.
The scores are written to results/scoreboard/<label>.json for the iteration ledger (ITERATIONS.md).
Per-question holdout output goes to a temporary folder that this script never reads.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEPENDENT = Path.home() / "Desktop" / "hackathon-independent-eval"
PY = sys.executable


def harness(eval_file, out, snapshots=None, gold=None):
    cmd = [PY, "harness/run_eval.py", "--submission", "solution", "--eval", str(eval_file), "--out", str(out)]
    if snapshots:
        cmd += ["--snapshots", str(snapshots)]
    if gold:
        cmd += ["--conflicts-gold", str(gold)]
    subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True)
    r = json.loads((Path(out) / "report.json").read_text())
    c = r.get("conflicts") or {}
    return {"accuracy": r["qa_score"], "consistency": r["consistency"]["score"], "speed": r["speed"]["score"],
            "conflict_f1": c.get("f1"), "conflict_winner": c.get("resolution_accuracy"),
            "stale_traps": r["stale_trap_hits"], "errors": r["errors"], "total": r["final_score"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", action="store_true", help="also score the blind holdout (aggregates only)")
    ap.add_argument("--label", default="current")
    args = ap.parse_args()
    board = {}
    checks = subprocess.run([PY, "tests/run_checks.py"], cwd=ROOT, capture_output=True, text=True)
    board["checks"] = {"output": [l for l in checks.stdout.splitlines() if not l.startswith("   FAIL")],
                       "failures": sum(l.startswith("   FAIL") for l in checks.stdout.splitlines())}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        board["public"] = harness(ROOT / "eval/public_eval.jsonl", tmp / "public")
        board["selftest"] = harness(ROOT / "harness/selftest/eval.jsonl", tmp / "selftest",
                                    ROOT / "harness/selftest/snapshots", ROOT / "harness/selftest/conflicts_gold.json")
        board["sim"] = harness(ROOT / "tests/sim_eval.jsonl", tmp / "sim")
        if INDEPENDENT.exists():
            board["dev"] = harness(INDEPENDENT / "dev_226.jsonl", ROOT / "results/indep_dev",
                                   gold=INDEPENDENT / "conflicts_dev.json")
            if args.holdout:
                board["holdout"] = harness(INDEPENDENT / "holdout_176.jsonl", tmp / "holdout",
                                           gold=INDEPENDENT / "conflicts_holdout.json")
    print(f"checks: {board['checks']['failures']} failure(s)  " + " | ".join(board["checks"]["output"]))
    cols = ["accuracy", "conflict_f1", "conflict_winner", "consistency", "speed", "stale_traps", "errors", "total"]
    print(f"{'layer':9s}" + "".join(f"{c:>16s}" for c in cols))
    for layer in ("public", "selftest", "sim", "dev", "holdout"):
        if layer in board:
            print(f"{layer:9s}" + "".join(f"{'-' if board[layer][c] is None else board[layer][c]:>16}" for c in cols))
    out = ROOT / "results/scoreboard"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.label}.json").write_text(json.dumps(board, indent=2))


if __name__ == "__main__":
    main()
