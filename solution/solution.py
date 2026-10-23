"""
Knowledge system for the "what's true now" hackathon.

    ingest(snapshot)          keep every snapshot as its own view of the website (history, not just latest)
    answer(question, as_of)   pick the snapshot view for the date, then answer from it
    conflicts()               places where the website contradicts itself

See NOTES.md for the rules on what counts as "current".

Note: the harness loads this file without registering it in sys.modules, which breaks @dataclass here.
Keep dataclasses in the kb_* modules (normal imports) and only plain classes in this file.
"""
import calendar
import re
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
from kb_pages import SnapView, index_doc, make_doc, observed_in  # noqa: E402
from kb_rate_qa import answer_rate_question, keep_asked_metrics, parse_question  # noqa: E402
from kb_search import answer_kind, build_definitions, build_idf, search  # noqa: E402


MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
DATE_IN_QUESTION = re.compile(
    r"\b(?:as of|in|on|during|by|back in|around|at the end of)\s+(?:the\s+)?(early|mid|late)?[-\s]?"
    r"(?:(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?:(\d{1,2})(?:st|nd|rd|th)?,?\s+)?(20\d\d)\b"
    r"|(\d{1,2})/(\d{1,2})/(20\d\d)\b|(20\d\d)-(\d\d)-(\d\d)\b)", re.I)
PART_OF_MONTH = {"early": 5, "mid": 15, "late": 25}


# "Has the 10-month jumbo rate changed?", "What was the previous 12-month certificate rate?"
CHANGE_QUESTION = re.compile(r"\b(chang\w*|previous(ly)?|prior|used to|before( that| it)?|went (up|down)|go(ne)? (up|down)|"
                             r"increas\w*|decreas\w*|rais\w*|lower(ed)?|drop\w*|old rate|last time)\b", re.I)


# stricter for text answers, where "how do I change my address?" is not about a change on the site
CHANGED_FACT = re.compile(r"\b(changed|previous(ly)?|used to|went (up|down)|gone (up|down)|increased|decreased|"
                          r"raised|lowered|dropped)\b", re.I)
KEY_VALUE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?|\b\d+(?:\.\d+)?%|\b\d[\d,]{2,}\b")


def date_in_question(question: str) -> Optional[str]:
    """'What was the 12-month certificate APY in May 2026?' -> '2026-05-31' (a month means its last day,
    as the site stood by then); 'as of May 12, 2026' -> '2026-05-12'; 'in mid-May 2026' -> '2026-05-15';
    'on the June 9, 2026 rate sheet' -> '2026-06-09'. Used only when no as_of is passed."""
    m = DATE_IN_QUESTION.search(question)
    if not m:
        return None
    part = (m.group(1) or "").lower()
    try:
        if m.group(2):
            y, mo = int(m.group(4)), MONTHS[m.group(2).lower()[:3]]
            d = int(m.group(3)) if m.group(3) else PART_OF_MONTH.get(part) or calendar.monthrange(y, mo)[1]
        elif m.group(5):
            mo, d, y = int(m.group(5)), int(m.group(6)), int(m.group(7))
        else:
            y, mo, d = int(m.group(8)), int(m.group(9)), int(m.group(10))
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def normalize_as_of(as_of) -> Optional[str]:
    """as_of as an ISO date: '2026-05-31', a date/datetime, '2026-05-31T00:00:00Z', '2026-05' (end of month),
    'May 2026', '05/31/2026'. Anything unreadable means no date (answer from the latest download), never a crash."""
    if not as_of:
        return None
    s = str(as_of).strip()
    try:
        return date.fromisoformat(s[:10]).isoformat()
    except ValueError:
        pass
    m = re.fullmatch(r"(20\d\d)-(\d{1,2})", s)
    if m and 1 <= int(m.group(2)) <= 12:
        y, mo = int(m.group(1)), int(m.group(2))
        return date(y, mo, calendar.monthrange(y, mo)[1]).isoformat()
    return date_in_question("as of " + s)


# A second question joined to the first: "What does a Holiday Club account earn, and WHEN does the money get paid
# out?", "Who administers the hardship fund AND HOW do I contact them?". Lists ("rate and APY", "for individuals
# and for businesses") are not split: the second part must start like a question of its own.
CLAUSE_BREAK = re.compile(r"(?:,\s*|\s+)and\s+(?=(?:what|when|how|who|whom|where|which|why|is|are|does|do|did|can|"
                          r"will|would)\b)|\?\s+(?=\S+(?:\s+\S+){3})|;\s+", re.I)
SUBJECT_NOUN = re.compile(r"(?:\b[\w$'’-]+\s+)?\b(?:accounts?|loans?|cards?|certificates?|mortgages?|branch(?:es)?|grants?|"
                          r"programs?|funds?|heloc|visa|privilege|savings|checking|scholarships?|insurance)\b", re.I)


def split_question(question: str) -> list:
    """['What does a Holiday Club account earn', 'when does the money get paid out (Holiday Club account)']:
    the second clause gets the first one's names and products, which it usually leaves out."""
    parts = [p.strip(" ?") for p in CLAUSE_BREAK.split(question) if p and p.strip(" ?")]
    if len(parts) < 2:
        return [question]
    first = parts[0]
    names = re.findall(r"(?<!^)(?<![.?!]\s)\b[A-Z][\w'’$-]+(?:\s+[A-Z][\w'’$-]+)*", first)
    subject = " ".join(dict.fromkeys(" ".join(names + [m.group(0) for m in SUBJECT_NOUN.finditer(first)]).split()))
    return [first + "?"] + [f"{p}? ({subject})" if subject else p + "?" for p in parts[1:]]


def question_kind(question: str) -> str:
    return "rate" if parse_question(question) else answer_kind(question)[0]


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
        try:
            return self._answer(question or "", as_of)
        except Exception:      # an unforeseen input must not crash the member's chat: decline instead
            return Answer(text="I don't know. Please contact Dupaco or visit https://www.dupaco.com/contact.",
                          confident=False)   # no numbers in a refusal

    def _answer(self, question: str, as_of: Optional[str] = None) -> Answer:
        as_of = normalize_as_of(as_of) or date_in_question(question)   # "... as of May 2026?" written in the text
        clauses = split_question(question)
        if len(clauses) > 1 and len({question_kind(c) for c in clauses}) > 1:
            # two questions asking for different kinds of answer (a rate and a date, a fee and a limit): each is
            # answered on its own, so neither part is dropped
            return self.combine([self._answer_one(c, as_of) for c in clauses])
        return self._answer_one(question, as_of)

    @staticmethod
    def combine(parts: list) -> Answer:
        sources, seen = [], set()
        for a in parts:
            for s in a.sources:
                if s.url not in seen:
                    seen.add(s.url)
                    sources.append(s)
        notes = [a.conflict_note for a in parts if a.conflict_note]
        return Answer(text="\n".join(a.text for a in parts), sources=sources,
                      confident=any(a.confident for a in parts), conflict_note=" ".join(notes) or None)

    def _answer_one(self, question: str, as_of: Optional[str] = None) -> Answer:
        view = self.view(as_of)
        asked = date.fromisoformat(str(as_of)[:10]) if as_of else None
        rate = answer_rate_question(view, question)   # step 2c: rate questions are answered from RateRows
        if rate is not None:
            text = rate.text
            if rate.confident:
                text += self.coverage_note(asked, rate.effective)
                if CHANGE_QUESTION.search(question):
                    text += self.previous_rates(view, question, rate.text)
            return Answer(
                text=text, confident=rate.confident, conflict_note=rate.note,
                sources=[Source(url=u, snapshot_id=s, quote=q) for u, q, s in rate.sources],
            )
        # step 3: everything else is answered with the sentence that holds the fact
        today = asked or date.fromisoformat(view.taken_on)    # "is it still open?" is judged on this day
        before_first = asked if asked and asked < date.fromisoformat(self.snaps[0].taken_on) else None
        hit = search(view, question, self.idf[view.snapshot_id], today, self.defs[view.snapshot_id], before_first)
        if hit is None:
            return Answer(text="I don't know.", confident=False)
        sources = [Source(url=hit.doc.url, snapshot_id=observed_in(view, hit.doc), quote=hit.quote)] if hit.doc else []
        sources += [Source(url=d.url, snapshot_id=observed_in(view, d)) for d in hit.also]   # pages saying the same
        published = hit.doc.published if hit.doc else None
        text = re.sub(r"\b1?\.?(\d{3})\.(\d{3})\.(\d{4})\b", r"\1-\2-\3", hit.text)    # 1.800.373.7600 -> 800-373-7600
        text = keep_asked_metrics(text, question)       # "What APY ...?": not the dividend rate printed beside it
        text += self.coverage_note(asked, published=published) if hit.confident else ""
        if hit.confident and CHANGED_FACT.search(question):
            text += self.previous_text(view, question, hit.quote)
        return Answer(text=text, sources=sources, confident=hit.confident)

    def previous_text(self, view, question: str, quote: str) -> str:
        """'Has the hardship grant amount changed?': the newest earlier download whose answer sentence gives
        other figures, labelled as the past. Nothing when the figures are the same or there are none."""
        vals = lambda t: set(KEY_VALUE.findall(t or ""))
        now = vals(quote)
        if not now:
            return ""
        for prev in reversed([s for s in self.snaps if s.taken_on < view.taken_on]):
            old = search(prev, question, self.idf[prev.snapshot_id], date.fromisoformat(prev.taken_on),
                         self.defs[prev.snapshot_id])
            if old is not None and old.confident and vals(old.quote) and vals(old.quote) != now:
                day = date.fromisoformat(prev.taken_on)
                return f"\nBefore that (the website as of {day:%B} {day.day}, {day.year}): {old.quote}"
        return ""

    def previous_rates(self, view, question: str, current: str) -> str:
        """Only when the question asks about a change: the newest earlier download whose answer differs,
        labelled as the past. Never in an ordinary answer, where an old number is the classic wrong answer."""
        body = lambda t: "\n".join(l for l in t.split("\n") if not l.startswith("Source:"))
        pcts = lambda t: sorted(set(re.findall(r"\d+(?:\.\d+)?%", body(t))))   # a relabelled table is no change
        for prev in reversed([s for s in self.snaps if s.taken_on < view.taken_on]):
            old = answer_rate_question(prev, question)
            if old is not None and old.confident and pcts(old.text) != pcts(current):
                day = date.fromisoformat(prev.taken_on)
                return (f"\nBefore that (the website as of {day:%B} {day.day}, {day.year}): "
                        + " ".join(body(old.text).split("\n")))
        return "\nThe earlier copies of the website show the same rates."

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
