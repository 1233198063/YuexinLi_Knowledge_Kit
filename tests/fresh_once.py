"""
Run a solution on the fresh blind set ONCE, and record only the aggregate.

    python tests/fresh_once.py --label B --submission solution

After the tournament line's one-shot heldback discipline: each solution version (the hash of its Python
source) may be scored on a blind set once. A START line is written to a ledger outside this repository before
the solution is imported; a second run of the same version on the same set is refused, whatever the outcome of
the first (pass, failure, interruption). Per-question outputs go to a temporary folder that is deleted; only
the harness aggregates are kept. The variants to run are fixed in docs/FRESH-PREREGISTRATION.md.

(Their v2a runner also hardens paths against an untrusted process on the same machine - symlinked ancestors,
swapped state roots. That threat doesn't apply to one person running four pre-registered variants, so this
keeps the discipline, not the hardening.)
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRESH = Path.home() / "Desktop" / "hackathon-fresh-eval"
LEDGER = FRESH / "LEDGER.jsonl"


def source_hash(folder: Path) -> str:
    """Sorted relative path + NUL + file SHA-256 + newline over every .py file (caches excluded)."""
    h = hashlib.sha256()
    for f in sorted(p for p in folder.rglob("*.py") if "__pycache__" not in p.parts):
        h.update(f.relative_to(folder).as_posix().encode() + b"\0" + hashlib.sha256(f.read_bytes()).hexdigest().encode() + b"\n")
    return h.hexdigest()


def ledger() -> list:
    if not LEDGER.exists():
        return []
    return [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]


def append(entry: dict) -> None:
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True, help="the pre-registered variant (A, B, C, D)")
    ap.add_argument("--submission", type=Path, required=True)
    args = ap.parse_args()
    bank, gold = FRESH / "fresh_final.jsonl", FRESH / "conflicts.json"
    if not bank.exists():
        sys.exit(f"no fresh set at {bank}")
    sub = args.submission.resolve()
    digest = source_hash(sub)
    bank_hash = hashlib.sha256(bank.read_bytes()).hexdigest()
    done = [e for e in ledger() if e.get("source") == digest and e.get("bank") == bank_hash]
    if done:
        sys.exit(f"refused: this version ({digest[:12]}) was already run on this set as {done[0]['label']}")
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    append({"event": "START", "label": args.label, "source": digest, "bank": bank_hash, "at": stamp})
    out = Path(tempfile.mkdtemp(prefix="fresh_once_"))
    try:
        cmd = [sys.executable, "harness/run_eval.py", "--submission", str(sub), "--eval", str(bank), "--out", str(out)]
        if gold.exists():
            cmd += ["--conflicts-gold", str(gold)]
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode != 0:
            append({"event": "FAIL", "label": args.label, "source": digest, "bank": bank_hash})
            sys.exit("harness failed:\n" + p.stdout[-600:] + p.stderr[-600:])
        r = json.loads((out / "report.json").read_text())
        result = {"event": "RESULT", "label": args.label, "source": digest, "bank": bank_hash,
                  "accuracy": r["qa_score"], "total": r["final_score"], "pillars": r.get("pillars"),
                  "consistency": r["consistency"]["score"], "speed": r["speed"]["score"],
                  "p95_s": r["speed"].get("p95_s"), "stale_traps": r["stale_trap_hits"], "errors": r["errors"],
                  "conflicts": {k: r["conflicts"].get(k) for k in ("f1", "precision", "recall", "resolution_accuracy")}
                  if r.get("conflicts") else None}
        append(result)
        print(json.dumps(result, indent=1))
    finally:
        shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    main()
