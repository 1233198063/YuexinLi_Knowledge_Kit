"""
Score this solution on every agent-authored question bank, with the unchanged organizer harness.

    python tests/banks.py [--blind] [--only NAME]

The banks were written by independent test-author agents from the snapshots (none is an organizer hidden set):
  ours-*     our test author (C:/Users/<you>/Desktop/hackathon-independent-eval)
  km226      the 226-question regression bank of the companion repository (knowledge-main)
  legacy-*   its first author's bank (original corpus + self-authored synthetic scenarios)
  A-*, B-*, C-*   its round-2 and round-3 authors
Development banks print per-bank scores and keep per-question output under results/banks/ for debugging.
Blind banks (holdouts, confirmations) run only with --blind: they print aggregates, and their per-question output
goes to a temporary folder that nothing reads - so they keep measuring how well fixes generalise.
Items an author marked unresolved or quarantined are left out, as that author's rules require.
Synthetic items run on their own scenario's snapshots, with the scenario's conflict gold when it has one.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESK = Path.home() / "Desktop"
OURS = DESK / "hackathon-independent-eval"
KM = DESK / "knowledge-main"
TB = KM / "test-banks" / "local-authoring"
FIX = KM / "test-banks" / "local-synthetic-fixtures"
LEG = TB / "legacy509" / "organizer"

BANKS = [  # name, question files, blind?, conflict gold for the original corpus
    ("ours-dev", [OURS / "dev_226.jsonl"], False, OURS / "conflicts_dev.json"),
    ("km226", [KM / "eval/independent/combined_proxy_eval.jsonl"], False, KM / "eval/independent/stale_conflicts_proxy_gold.json"),
    ("legacy-dev", [LEG / "original_development.jsonl", LEG / "synthetic_development.jsonl"], False, None),
    ("A-dev", [TB / "round2-author-a/organizer/v2_development.jsonl"], False, None),
    ("B-dev", [TB / "round2-author-b-v2/development.jsonl"], False, None),
    ("C-dev", [TB / "round3-author-c-v2/candidate-facing/development_gold.jsonl"], False, None),
    ("ours-holdout", [OURS / "holdout_176.jsonl"], True, OURS / "conflicts_holdout.json"),
    ("legacy-holdout", [LEG / "original_holdout.jsonl", LEG / "synthetic_holdout.jsonl"], True, None),
    ("A-confirm", [TB / "round2-author-a/organizer/v2_confirmation.jsonl"], True, None),
    ("B-confirm", [TB / "round2-author-b-v2/confirmation.jsonl"], True, None),
    ("C-confirm", [TB / "round3-author-c-v2/private/confirmation.jsonl"], True, TB / "round3-author-c-v2/private/conflicts.json"),
]
EXCLUDED = {"unresolved", "quarantined", "quarantine", "disputed"}


def scenario_snapshots(name: str):
    for d in (FIX / "legacy509/synthetic" / name / "snapshots", FIX / "round2-author-a/evidence/synthetic" / name,
              TB / "round2-author-a/evidence/synthetic" / name):
        if d.is_dir():
            return d
    return None


def scenario_gold(name: str, tmp: Path):
    f = TB / "legacy509/synthetic" / name / "scenario.json"
    gold = json.loads(f.read_text(encoding="utf-8")).get("conflicts_gold") if f.exists() else None
    if not gold:
        return None
    out = tmp / f"{name}-gold.json"
    out.write_text(json.dumps(gold))
    return out


def harness(items, out: Path, snapshots=None, gold=None):
    out.mkdir(parents=True, exist_ok=True)
    qfile = out / "questions.jsonl"
    qfile.write_text("\n".join(json.dumps(i) for i in items), encoding="utf-8")
    cmd = [sys.executable, "harness/run_eval.py", "--submission", "solution", "--eval", str(qfile), "--out", str(out)]
    if snapshots:
        cmd += ["--snapshots", str(snapshots)]
    if gold and Path(gold).exists():
        cmd += ["--conflicts-gold", str(gold)]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(p.stdout[-800:] + p.stderr[-800:])
    return json.loads((out / "report.json").read_text())


def run_bank(name, files, blind, gold, base: Path):
    rows = [json.loads(l) for f in files if f.exists() for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r.get("ambiguity_status") not in EXCLUDED and r.get("leaderboard_eligible") is not False]
    runs = defaultdict(list)
    for r in rows:
        runs["original" if r.get("corpus", "original") == "original" else r.get("scenario") or "?"].append(r)
    results, skipped = [], 0
    for corpus, items in runs.items():
        if corpus == "original":
            rep = harness(items, base / name / "original", gold=gold)
        else:
            snaps = scenario_snapshots(corpus)
            if snaps is None:
                skipped += len(items)
                continue
            rep = harness(items, base / name / corpus, snaps, scenario_gold(corpus, base))
        results.append((corpus, sum(i.get("weight", 1.0) for i in items), len(items), rep))
    w = sum(x[1] for x in results) or 1
    acc = sum(x[1] * x[3]["qa_score"] for x in results) / w
    orig = next((x[3] for x in results if x[0] == "original"), None)
    syn = [x for x in results if x[0] != "original"]
    syn_w = sum(x[1] for x in syn)
    conflict = [x[3]["conflicts"] for x in results if x[3].get("conflicts")]
    return {
        "items": sum(x[2] for x in results), "skipped": skipped, "accuracy": round(acc, 4),
        "original_accuracy": orig["qa_score"] if orig else None,
        "synthetic_accuracy": round(sum(x[1] * x[3]["qa_score"] for x in syn) / syn_w, 4) if syn_w else None,
        "consistency": orig["consistency"]["score"] if orig else None,
        "stale_traps": sum(x[3]["stale_trap_hits"] for x in results), "errors": sum(x[3]["errors"] for x in results),
        "conflict_f1": round(sum(c["f1"] for c in conflict) / len(conflict), 4) if conflict else None,
        "original_total": orig["final_score"] if orig else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blind", action="store_true", help="also run holdout/confirmation banks (aggregates only)")
    ap.add_argument("--only", help="run one bank by name")
    args = ap.parse_args()
    cols = ["items", "accuracy", "original_accuracy", "synthetic_accuracy", "consistency", "conflict_f1",
            "stale_traps", "errors", "original_total"]
    print(f"{'bank':15s}" + "".join(f"{c[:14]:>15s}" for c in cols))
    board = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, files, blind, gold in BANKS:
            if (args.only and name != args.only) or (blind and not args.blind and args.only != name):
                continue
            base = Path(tmp) if blind else ROOT / "results/banks"
            board[name] = run_bank(name, files, blind, gold, base)
            print(f"{name:15s}" + "".join(f"{'-' if board[name][c] is None else board[name][c]:>15}" for c in cols)
                  + (f"   ({board[name]['skipped']} items without snapshots)" if board[name]["skipped"] else ""))
    out = ROOT / "results/scoreboard"
    out.mkdir(parents=True, exist_ok=True)
    (out / "banks.json").write_text(json.dumps(board, indent=2))


if __name__ == "__main__":
    main()
