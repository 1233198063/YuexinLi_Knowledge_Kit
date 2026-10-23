"""
Step 1 - the data layer: clean each page, decide what kind of page it is, find its publish date.

Everything downstream asks three questions about a piece of text:
  * what kind of page did it come from?   (rate sheet beats calculator beats old blog post)
  * when was it written?                   (a 2026 press release beats a 2021 one)
  * which snapshot was it in?              (for "as of" questions)
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
from urllib.parse import urlparse

from kb_chunks import chunk_page
from kb_rates import parse_rate_tables

# ---------------------------------------------------------------- cleaning

# Everything after these headings is a sidebar of *other* articles (teaser text + their dates).
SIDEBAR = re.compile(r"^#{2,4}\s*(Handpicked for You|Recent News|Related (Posts|Articles))\b.*", re.M | re.I)
DATA_URI = re.compile(r"data:[a-z]+/[^\s)\"']+", re.I)
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
FLAG_LINE = re.compile(r"^\s*-\s*[\U0001F1E6-\U0001F1FF]{2}.*$", re.M)   # "- 🇲🇽 Mexico (México) +52"
MODAL = re.compile(r"^\s*(✕|\[Continue\]\([^)]*\)\s*Cancel|Third Party Plugins|Messenger( Launcher)?)\s*$", re.M)
READ_TIME = re.compile(r"^\s*\d+ min read\s*$", re.M)
DEAD_COUNTER = re.compile(r"^#{1,6}\s*(0\+?|NaN)\s*$", re.M)   # animated stat counters the crawler saw before they ran
EXIT_NOTICE = re.compile(r"\*\*Heads up! This link leads to a different website\.\*\*\s*(We only do this when[^\n]*)?")
ESCAPED_CRLF = re.compile(r"(\\\\r\\\\n|\\r\\n)+")
BLANKS = re.compile(r"\n{3,}")


def clean(markdown: str) -> str:
    t = markdown
    m = SIDEBAR.search(t)
    if m:
        t = t[: m.start()]
    t = DATA_URI.sub("", t)
    t = IMAGE.sub("", t)
    t = FLAG_LINE.sub("", t)
    t = MODAL.sub("", t)
    t = READ_TIME.sub("", t)
    t = DEAD_COUNTER.sub("", t)
    t = EXIT_NOTICE.sub("", t)
    t = t.replace("http://www.dupaco.com", "https://www.dupaco.com")
    t = ESCAPED_CRLF.sub(" ", t)
    t = t.replace(" ", " ")
    return BLANKS.sub("\n\n", t).strip()


# ---------------------------------------------------------------- URLs

def canonical_url(url: str) -> str:
    """Same key the scorer uses: host (no www) + path, no query/fragment, no trailing slash."""
    p = urlparse(url if "//" in url else "https://" + url)
    host = p.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return host + (p.path.rstrip("/").lower() or "")


# ---------------------------------------------------------------- page kinds

# How much we trust each kind of page when two pages disagree (1.0 = most trusted).
AUTHORITY = {
    "rates": 1.00,       # /rates, /business-rates: the official rate sheet, with "effective as of" dates
    "product": 0.90,     # product & service pages (savings, loans, contact, membership ...)
    "document": 0.70,    # PDFs / spreadsheets: fee schedules, terms & conditions
    "news": 0.55,        # press releases: dated, true when written
    "landing": 0.45,     # campaign landing pages (-lp): often outlive the offer
    "blog": 0.40,        # educational articles: dated, numbers are often examples
    "calculator": 0.30,  # calculators: default example rates are rarely updated
    "listing": 0.10,     # tag/author/category index pages: just teasers of other pages
    "expired": 0.00,     # "Oops ... This Offer Has Expired"
}


def page_kind(url: str, title: str) -> str:
    p = urlparse(url)
    path = p.path.lower().rstrip("/")
    if "offer has expired" in (title or "").lower():
        return "expired"
    if path in ("/rates", "/business-rates"):
        return "rates"
    if path.startswith("/calculators") or path == "/business-calculators":
        return "calculator"
    if (p.query and "category=" in p.query) or re.search(r"/(tag|author|page)(/|$)", path) or path in (
        "/newsroom", "/learn", "/learn/blog", "/resources", "/resources/dupaco-news",
        "/resources/personal-resources", "/resources/business-resources", "/business/resources",
    ):
        return "listing"
    if path.startswith("/newsroom/"):
        return "news"
    if path.startswith("/learn/master-your-money"):
        return "product"   # a product hub that carries the live mortgage rate table, not an article
    if (path.startswith("/learn/") or path.startswith("/business/resources/") or path.startswith("/dupacodaily")
            or re.match(r"^/\d{4}/", path)):
        return "blog"
    if path.startswith("/hubfs/"):
        return "document"
    if path.endswith("-lp"):
        return "landing"
    return "product"


# ---------------------------------------------------------------- dates

MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
LONG_DATE = re.compile(rf"\b({MONTHS})[a-z]*\.?\s+(\d{{1,2}}),?\s+(20\d\d|19\d\d)\b")
WRITTEN_BY = re.compile(r"^Written by .*$", re.M)


def parse_long_date(s: str) -> Optional[date]:
    """'April 23, 2026', 'Jan 22, 2021', 'Sept. 7, 2022' -> date."""
    m = LONG_DATE.search(s)
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)[:3]} {m.group(2)} {m.group(3)}", "%b %d %Y").date()
    except ValueError:
        return None


def publish_date(kind: str, raw_markdown: str) -> Optional[date]:
    """News and blog pages use one of two layouts:
         'N min read / [Author] / April 23, 2026 / # Title'          (date before the title)
         '# Title / Written by [Author] | Jan 22, 2021 8:15:00 PM'    (older posts: date after the title)"""
    if kind not in ("news", "blog"):
        return None
    head = raw_markdown[:1500]
    h1 = re.search(r"^# ", head, re.M)
    d = parse_long_date(head[: h1.start()]) if h1 else None
    if d is None:
        w = WRITTEN_BY.search(head)
        d = parse_long_date(w.group(0)) if w else None
    return d or (None if h1 else parse_long_date(head[:600]))


# ---------------------------------------------------------------- the stored page

@dataclass
class PageDoc:
    """One distinct version of one page (identical versions across snapshots are stored once)."""
    url: str
    key: str                       # canonical_url(url)
    title: str
    kind: str
    authority: float
    published: Optional[date]
    text: str                      # cleaned markdown
    version: str                   # hash of the cleaned text
    first_seen: str = ""           # snapshot_id where this exact version first appeared
    snapshots: list = field(default_factory=list)   # every snapshot_id that contained this version
    chunks: list = field(default_factory=list)      # list[Chunk]: paragraphs with their heading (step 2a)
    rates: list = field(default_factory=list)       # list[RateRow]: one record per rate-table row (step 2b)


@dataclass
class SnapView:
    """The whole website as it stood on one crawl date: canonical url -> PageDoc."""
    snapshot_id: str
    taken_on: str
    pages: dict = field(default_factory=dict)
    carried: set = field(default_factory=set)   # keys of pages not re-downloaded this time, kept from an earlier one


def observed_in(view: SnapView, doc: PageDoc) -> str:
    """The download that really contained this version of the page: the view's own, or for a page carried
    forward from an earlier download, the last download that fetched it (sources must be checkable)."""
    if view.snapshot_id in doc.snapshots:
        return view.snapshot_id
    earlier = [s for s in doc.snapshots if s <= view.snapshot_id]
    return max(earlier) if earlier else doc.first_seen


def make_doc(url: str, title: str, markdown: str) -> PageDoc:
    kind = page_kind(url, title)
    text = clean(markdown)
    if "offer has expired" in text[:1000].lower():
        kind = "expired"          # the notice can be in the page body, not only in its title
    return PageDoc(
        url=url, key=canonical_url(url), title=(title or "").strip(), kind=kind,
        authority=AUTHORITY[kind], published=publish_date(kind, markdown), text=text,
        version=hashlib.md5(text.encode("utf-8")).hexdigest()[:12],
    )


def index_doc(doc: PageDoc) -> PageDoc:
    """Step 2: cut the page into paragraphs and its rate tables into records (once per distinct version)."""
    path = urlparse(doc.url).path.lower()
    doc.chunks = chunk_page(doc.text, doc.title, path)
    doc.rates = parse_rate_tables(doc.text, path)
    return doc
