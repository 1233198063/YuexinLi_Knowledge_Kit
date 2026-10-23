"""
Step 2a - pages -> paragraphs (Chunk).

A page is too big to be an answer and a single line is too small to carry its context, so each
page is cut into paragraph-sized chunks that remember the heading they sit under:

    # Home Guidance That Puts You First
    ## Build Your Dream Home                 <- heading path: "Home Guidance That Puts You First > Build Your Dream Home"
    If eligible, you may borrow up to 80% of construction costs. ...

Rules
  * a markdown heading starts a new chunk and becomes part of the heading path
  * short blocks above the first heading (byline, date, "4 min read") are dropped
  * short blocks under the same heading are merged until a chunk reaches ~TARGET characters
  * very long blocks (PDF text, legal copy) are split at sentence ends
  * rate tables are NOT chunked: they live as RateRows (kb_rates.py), where tiers can't be mixed up
  * each chunk also keeps its sentences (one per line / sentence end), so search can answer with
    the one sentence that holds the fact instead of a whole paragraph
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

TARGET = 500     # merge small blocks up to about this many characters
MAX = 1200       # split blocks longer than this

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])")
WORD = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")
STOP = frozenset("""
a an and are as at be by can do does for from has have how i if in is it its me my of on or our
so that the their them there this to us was we what when where which who why will with you your
dupaco s many much any some would could should like know tell give provide get please also just going
want need im go
""".split())


@dataclass
class Chunk:
    heading: str                 # "Page H1 > Section H2"
    text: str
    pos: int                     # order on the page
    terms: frozenset = field(default_factory=frozenset)       # search terms (heading + text)
    head_terms: frozenset = field(default_factory=frozenset)  # search terms of the heading path only
    sect_terms: frozenset = field(default_factory=frozenset)  # terms of its own section title (## or deeper, not the H1)
    sents: list = field(default_factory=list)                 # [(sentence, its terms)]


def stem(w: str) -> str:
    """Crude but predictable: drop plural / -ed / -ing / final e, then keep 6 letters, so that
    branches~branch, employees~employee, recognized~recognition, volunteered~volunteer."""
    if len(w) <= 3 or not w[0].isalpha():
        return w
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 4 and w.endswith(("sses", "shes", "ches", "xes")):
        w = w[:-2]
    elif w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    for suffix in ("ing", "ed"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            w = w[: -len(suffix)]
            break
    if len(w) > 4 and w.endswith("e"):
        w = w[:-1]
    return w[:6]


def tokens(text: str) -> list[str]:
    """Lower-case, lightly stemmed words and numbers, minus stop words: the vocabulary search works with."""
    text = re.sub(r"https?://\S+", " ", re.sub(r"\]\([^)]*\)", "] ", text))   # link text counts, its URL doesn't
    words = WORD.findall(text.lower().replace("$", " ").replace("’", "").replace("'", ""))
    out = [stem(w) for w in words if w not in STOP and (len(w) > 1 or w.isdigit())]
    return [s for s in out if s not in STOP]     # "Dupaco's" -> "dupacos" -> "dupaco": still a stop word


ABBREV = re.compile(r"\b(St|Ave|Dr|Rd|Ln|Blvd|Mr|Mrs|Ms|Jr|Sr|Inc|Co|No|U\.S|a\.m|p\.m|Jan|Feb|Mar|Apr|Aug|"
                    r"Sept?|Oct|Nov|Dec|Ill|Wis|vs|etc)\.$")


def sentences(text: str) -> list[str]:
    out = []
    for line in re.sub(r"<br\s*/?>", "\n", text).split("\n"):   # layout tables pack whole lists into one cell
        merged = []
        for piece in (s.strip() for s in SENTENCE_END.split(line.strip()) if s.strip()):
            if merged and ABBREV.search(merged[-1]):
                merged[-1] += " " + piece      # "South Locust St. Hy-Vee store" is one sentence
            else:
                merged.append(piece)
        out.extend(merged)
    return out


def _is_rate_table(block: str) -> bool:
    lines = block.split("\n")
    return (len(lines) > 2 and lines[0].startswith("|") and bool(re.search(r"rate|apy|apr|yield|dividend", lines[0], re.I))
            and "%" in block)


def _split_long(block: str) -> list[str]:
    parts, cur = [], ""
    for sent in SENTENCE_END.split(block):
        if cur and len(cur) + len(sent) > MAX:
            parts.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        parts.append(cur)
    return parts


def chunk_page(text: str, title: str = "", url_path: str = "") -> list[Chunk]:
    """url_path words count as part of every chunk's heading: /about/join is about joining."""
    url_words = " " + re.sub(r"[/_.-]+", " ", url_path)
    heads: dict[int, str] = {}
    chunks: list[Chunk] = []
    pending: list[str] = []

    def path() -> str:
        hs = [heads[k] for k in sorted(heads)]
        if title and (not hs or hs[0].lower() != title.lower()):
            hs.insert(0, title)
        return " > ".join(hs)

    def emit(body: str):
        h = path()
        deepest = max(heads) if heads else 0
        sect = heads[deepest] if deepest >= 2 else ""
        chunks.append(Chunk(heading=h, text=body, pos=len(chunks), terms=frozenset(tokens(h + url_words + " " + body)),
                            head_terms=frozenset(tokens(h + url_words)), sect_terms=frozenset(tokens(sect)),
                            sents=[(x, frozenset(tokens(x))) for x in sentences(body)]))

    def flush():
        if pending:
            emit("\n\n".join(pending))
            pending.clear()

    # a heading is its own block even when no blank line sets it apart ("## Platinum Visa" right above its bullets)
    text = re.sub(r"(?m)^(#{1,6}[ \t]+\S.*)$", r"\n\1\n", text)
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    first_heading =next((i for i, b in enumerate(blocks) if "\n" not in b and HEADING.match(b)), 0)
    for i, block in enumerate(blocks):
        if i < first_heading and len(block) < 120:
            continue          # byline / date / read-time above the title: metadata, not content
        m = HEADING.match(block) if "\n" not in block else None
        if m:
            flush()
            level = len(m.group(1))
            heads = {k: v for k, v in heads.items() if k < level}
            heads[level] = m.group(2).strip().strip("*")
            continue
        if _is_rate_table(block):
            flush()
            continue
        if len(block) > MAX:
            flush()
            for part in _split_long(block):
                emit(part)
            continue
        pending.append(block)
        if sum(len(p) for p in pending) >= TARGET:
            flush()
    flush()
    return chunks
