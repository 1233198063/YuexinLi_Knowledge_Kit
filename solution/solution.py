"""
Knowledge system for the "what's true now" hackathon.

    ingest(snapshot)          keep every snapshot as its own view of the website (history, not just latest)
    answer(question, as_of)   pick the snapshot view for the date, then answer from it
    conflicts()               places where the website contradicts itself

See NOTES.md for the rules on what counts as "current".

Note: the harness loads this file without registering it in sys.modules, which breaks @dataclass here.
Keep dataclasses in the kb_* modules (normal imports) and only plain classes in this file.
"""
import sys
from datetime import date
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    from contract import Answer, Conflict, Snapshot, Source  # the harness puts harness/ on sys.path
except ImportError:  # running outside the harness: find harness/contract.py in a parent folder
    sys.path.insert(0, str(next(d / "harness" for d in HERE.parents if (d / "harness" / "contract.py").exists())))
    from contract import Answer, Conflict, Snapshot, Source  # noqa: E402

from kb_conflicts import find_conflicts  # noqa: E402
from kb_pages import SnapView, index_doc, make_doc  # noqa: E402
from kb_rate_qa import answer_rate_question  # noqa: E402
from kb_search import build_definitions, build_idf, search  # noqa: E402


class KnowledgeBase:
    def __init__(self):
        self.snaps = []   # list[SnapView], oldest first
        self.docs = {}    # (url key, version hash) -> PageDoc
        self.idf = {}     # snapshot_id -> {term: idf} over that snapshot's chunks
        self.defs = {}    # snapshot_id -> {"charter area": "Iowa: Any county; ..."} terms the site defines

    # ------------------------------------------------------------ ingest
    def ingest(self, snapshot: Snapshot) -> None:
        view = SnapView(snapshot.snapshot_id, snapshot.taken_on)
        for p in snapshot.pages:
            d = make_doc(p.url, p.title, p.markdown)
            old = view.pages.get(d.key)
            if old is not None and len(old.text) >= len(d.text):
                continue  # same page under another query string / #fragment: keep the fuller copy
            stored = self.docs.setdefault((d.key, d.version), d)
            if stored is d:
                index_doc(d)  # new version: cut into paragraphs + parse its rate tables
            if not stored.first_seen:
                stored.first_seen = snapshot.snapshot_id
            if snapshot.snapshot_id not in stored.snapshots:
                stored.snapshots.append(snapshot.snapshot_id)
            view.pages[d.key] = stored
        # A page this download didn't fetch is still on the site: keep its newest earlier version
        # (user decision, 2026-10-20, matching the harness example where a page from the first download still answers).
        earlier = [s for s in self.snaps if s.taken_on < view.taken_on]
        if earlier:
            prev = max(earlier, key=lambda s: s.taken_on)
            for key, doc in prev.pages.items():
                if key not in view.pages:
                    view.pages[key] = doc
                    view.carried.add(key)
        self.snaps.append(view)
        self.snaps.sort(key=lambda s: s.taken_on)
        self.idf[view.snapshot_id] = build_idf(view)
        self.defs[view.snapshot_id] = build_definitions(view)

    def view(self, as_of: Optional[str] = None):
        """Latest snapshot taken on or before `as_of` (the oldest one if as_of predates them all)."""
        if not as_of:
            return self.snaps[-1]
        day = str(as_of)[:10]
        eligible = [s for s in self.snaps if s.taken_on <= day]
        return eligible[-1] if eligible else self.snaps[0]

    def history(self, key: str):
        """Every snapshot's version of one page, oldest first."""
        return [(s.snapshot_id, s.pages[key]) for s in self.snaps if key in s.pages]

    # ------------------------------------------------------------ answer
    def answer(self, question: str, as_of: Optional[str] = None) -> Answer:
        view = self.view(as_of)
        asked = date.fromisoformat(str(as_of)[:10]) if as_of else None
        rate = answer_rate_question(view, question)   # step 2c: rate questions are answered from RateRows
        if rate is not None:
            text = rate.text
            if rate.confident:
                text += self.coverage_note(asked, rate.effective)
            return Answer(
                text=text, confident=rate.confident, conflict_note=rate.note,
                sources=[Source(url=u, snapshot_id=view.snapshot_id, quote=q) for u, q in rate.sources],
            )
        # step 3: everything else is answered with the sentence that holds the fact
        today = asked or date.fromisoformat(view.taken_on)    # "is it still open?" is judged on this day
        before_first = asked if asked and asked < date.fromisoformat(self.snaps[0].taken_on) else None
        hit = search(view, question, self.idf[view.snapshot_id], today, self.defs[view.snapshot_id], before_first)
        if hit is None:
            return Answer(text="I don't know.", confident=False)
        sources = [Source(url=hit.doc.url, snapshot_id=view.snapshot_id, quote=hit.quote)] if hit.doc else []
        published = hit.doc.published if hit.doc else None
        text = hit.text + (self.coverage_note(asked, published=published) if hit.confident else "")
        return Answer(text=text, sources=sources, confident=hit.confident)

    def coverage_note(self, asked: Optional[date], effective: Optional[list] = None,
                      published: Optional[date] = None) -> str:
        """A date before the first download: answer from the earliest copy, then say plainly what that
        copy can and cannot tell about the day asked (user decision, 2026-10-19)."""
        first = date.fromisoformat(self.snaps[0].taken_on)
        if asked is None or asked >= first:
            return ""
        day = lambda d: f"{d:%B} {d.day}, {d.year}"
        note = (f"\nNote: you asked about {day(asked)}, but the earliest copy of the website I have is from "
                f"{day(first)}; the answer above comes from that copy.")
        dated = [d for d in (effective or []) if d]
        if published:
            note += (f" It is taken from a page published on {day(published)}, before the date you asked about, "
                     f"so it reflects what Dupaco said at that time.")
        elif dated and len(dated) == len(effective) and max(dated) <= asked:
            note += f" These rates took effect by {day(max(dated))}, before the date you asked about, so they applied then too."
        elif dated and min(dated) > asked:
            note += (f" These rates took effect on {day(min(dated))}, after the date you asked about, and I have no copy "
                     f"of the earlier rates, so I don't know what applied on {day(asked)}.")
        else:
            note += f" I can't confirm what the website said on {day(asked)}."
        return note

    # ------------------------------------------------------------ conflicts (step 7)
    def conflicts(self) -> list[Conflict]:
        """Rate facts printed with different numbers (across pages or downloads) and repeated statements
        whose numbers changed; each with the value the answer rules pick and why (kb_conflicts.py)."""
        return [Conflict(topic=c.topic, values=c.values, resolution=c.resolution, reason=c.reason,
                         sources=[Source(url=u, snapshot_id=s) for u, s in c.sources])
                for c in find_conflicts(self.snaps)]


def build() -> KnowledgeBase:
    return KnowledgeBase()
