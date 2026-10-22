"""
Developer tool: look inside the knowledge base the way the system sees it.

    python solution/inspect_kb.py stats                     pages per kind, per snapshot
    python solution/inspect_kb.py kind calculator           list pages of one kind (latest snapshot)
    python solution/inspect_kb.py page contact              cleaned text + metadata of a page (url substring)
    python solution/inspect_kb.py history /rates            how one page changed across snapshots
    python solution/inspect_kb.py grep "30-Year Fixed"      where a phrase appears (latest; add --all for every snapshot)
    python solution/inspect_kb.py rates /rates              rate records parsed from a page (url substring)
    python solution/inspect_kb.py chunks contact            paragraph chunks of a page
    python solution/inspect_kb.py ask "30-year mortgage rate?" [2026-05-31]    answer + sources + conflict note
"""
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from run_eval import load_snapshots  # noqa: E402
from solution import build  # noqa: E402


def load():
    kb = build()
    for s in load_snapshots(ROOT / "snapshots"):
        kb.ingest(s)
    return kb


def find(kb, sub, view=None):
    view = view or kb.view()
    hits = [d for k, d in view.pages.items() if sub.lower() in d.url.lower()]
    hits.sort(key=lambda d: (len(d.url), d.url))
    return hits


def meta(d):
    pub = d.published.isoformat() if d.published else "-"
    return f"[{d.kind} auth={d.authority:.2f} published={pub} version={d.version} first_seen={d.first_seen[:13]}]"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd, args = sys.argv[1], sys.argv[2:]
    kb = load()

    if cmd == "stats":
        kinds = sorted({d.kind for s in kb.snaps for d in s.pages.values()})
        print(f"{'snapshot':28s}" + "".join(f"{k:>11s}" for k in kinds) + f"{'dated':>8s}")
        for s in kb.snaps:
            c = Counter(d.kind for d in s.pages.values())
            dated = sum(1 for d in s.pages.values() if d.published)
            print(f"{s.snapshot_id:28s}" + "".join(f"{c[k]:>11d}" for k in kinds) + f"{dated:>8d}")
        prev = None
        print("\npages whose CLEANED text changed vs previous snapshot:")
        for s in kb.snaps:
            if prev:
                changed = sum(1 for k, d in s.pages.items() if k in prev.pages and prev.pages[k].version != d.version)
                print(f"  {prev.snapshot_id[:13]} -> {s.snapshot_id[:13]}: {changed}")
            prev = s

    elif cmd == "kind":
        for d in sorted(kb.view().pages.values(), key=lambda d: d.url):
            if d.kind == args[0]:
                print(d.url, "|", d.published or "", "|", d.title[:60])

    elif cmd == "page":
        for d in find(kb, args[0])[:1]:
            print(d.url, meta(d))
            print("-" * 80)
            print(d.text[: int(args[1]) if len(args) > 1 else 3000])

    elif cmd == "history":
        d0 = find(kb, args[0])[:1]
        if not d0:
            print("no such page")
            return
        prev = None
        for sid, d in kb.history(d0[0].key):
            print(f"{sid}: version {d.version} {'(unchanged)' if prev == d.version else ''}")
            prev = d.version

    elif cmd == "grep":
        pat = re.compile(args[0], re.I)
        views = kb.snaps if "--all" in args else [kb.view()]
        for v in views:
            print(f"===== {v.snapshot_id}")
            rows = []
            for d in v.pages.values():
                for m in pat.finditer(d.text):
                    ctx = d.text[max(0, m.start() - 80): m.end() + 80].replace("\n", " ")
                    rows.append((-d.authority, d.url, meta(d), ctx))
                    break
            for _, url, md, ctx in sorted(rows)[:40]:
                print(f"{url}\n    {md}\n    ...{ctx}...")

    elif cmd == "rates":
        for d in find(kb, args[0])[:1]:
            print(d.url, meta(d))
            for r in d.rates:
                quals = ",".join(sorted(r.quals)) or "-"
                print(f"  T{r.table:<2} {r.family}/{r.name or '-'}/{quals}  eff={r.effective}  "
                      f"term={r.term_months} tier={r.tier_lo}-{r.tier_hi} years={r.years}  {r.rates}  | {r.display}")

    elif cmd == "chunks":
        for d in find(kb, args[0])[:1]:
            print(d.url, meta(d))
            for c in d.chunks:
                print(f"--- #{c.pos} [{c.heading}]\n{c.text[:400]}")

    elif cmd == "ask":
        a = kb.answer(args[0], as_of=args[1] if len(args) > 1 else None)
        print(a.text)
        print(f"\nconfident={a.confident}")
        for s in a.sources:
            print("source:", s.url)
        if a.conflict_note:
            print("conflict note:", a.conflict_note)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
