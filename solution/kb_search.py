"""
Step 3 - answer everything that is not a rate table by finding the ONE sentence that holds the fact.

    question --> search terms + the TYPE of answer it needs
                 ("how many branches" needs a number next to "branch", "when" needs a date, ...)
    BM25 over paragraph chunks       --> the most relevant chunks
    every sentence in those chunks is scored: its own words count fully, words found only in its
    heading path or in the sentence just before/after count half ("This location will close
    March 31, 2026." sits under "Hy-Vee Branch Closure"); questions are never answers; a sentence
    that never mentions the product the question names (loan, card, branch ...) counts half
    sentences without the needed answer type are dropped (as long as at least one sentence has it)
    repeated statement first: if one of the near-ties is said on 3+ pages (press-release boilerplate,
    possibly reworded / with other numbers), it beats one-off mentions, and its newest copy answers
    (user decision: "22 branch offices" in 100 releases beats an old bio's "18 branches" on /about)
    otherwise, which PAGE answers: near-ties (within 10% of the best) are settled by the "what is current" rules:
        1. the more trusted page wins          (AUTHORITY in kb_pages)
        2. then the newest publish date wins   (news facts: the April 2026 release says 22 branches,
                                                 the March 2026 one still says 23)
    which SENTENCE on that page: the one holding the most (and rarest) question words itself; ties go
                                 to the earliest (news puts the key fact first)
    answer = that sentence plus the one or two after it (or the bullet list it introduces),
    never a whole page: every extra sentence is a chance to repeat an old number.
    year-labelled statistics ("256 employees ... in 2024") also list the same statement's earlier
    years ("294 ... in 2023"): different years are history, not a conflict (user decision).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Optional

from kb_chunks import STOP, WORD, stem, tokens
from kb_pages import canonical_url, parse_long_date

# ---------------------------------------------------------------- what kind of answer the question needs

MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
DATE = re.compile(rf"\b{MONTH}\s+\d{{1,2}},?\s+\d{{4}}\b|\b\d{{1,2}}/\d{{1,2}}/\d{{2,4}}\b"
                  r"|\b(?:in|since|of)\s+(?:19|20)\d\d\b")          # "founded in 1948" answers "when" too
TIME = re.compile(r"\b\d{1,2}(:\d\d)?\s*(a\.?m\b\.?|p\.?m\b\.?)|\bnoon\b", re.I)
PHONE = re.compile(r"\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")
URL = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(com|org|net)\b", re.I)
ADDRESS = re.compile(r"\b\d{2,6}\s+(?:[A-Z0-9][\w.'-]*\s+){1,4}(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Lane|Ln|"
                     r"Blvd|Boulevard|Way|Court|Ct|Highway|Hwy|Parkway|Pkwy|Place|Pl|Circle|Cir)\b"
                     r"|\bP\.?\s?O\.?\s+Box\s+\d+")
MONEY = re.compile(r"\$\s?\d")
ROUTING = re.compile(r"\b\d{9}\b")
# a rate value is printed like a rate ("6.25%", "5% APR"); "adjust up to 2%" or "80% of costs" is not one
RATE_VALUE = re.compile(r"\b\d{1,2}\.\d{1,3}\s*%|\b\d{1,2}(?:\.\d+)?\s*%\s*(?:APR|APY|annual percentage)", re.I)
RATE_WORDS = re.compile(r"\b(interest( rates?)?|rates?|aprs?|apys?|dividend rates?|yields?)\b", re.I)
ORDINAL = r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th))"
TIMES = re.compile(rf"\b{ORDINAL}\s+(?:[\w’'-]+\s+){{0,2}}times?\b|\b\d+\s+times\b|\b(?:once|twice)\b", re.I)
WH_WORD = re.compile(r"\b(which|where|who|what|how)\b", re.I)
STATUS = re.compile(r"\bstill\b.*\b(open|available|offered|operating|around|exist)|\b(closed|discontinued|shut down)\b"
                    r"|^\s*(is|are)\b.*\bopen\b", re.I)
CLOSED_ASKED = re.compile(r"\b(closed|closing|clos(e|es) down|shut|shutting|discontinued|no longer)\b", re.I)
WH_QUESTION = re.compile(r"^\W*(when|what|where|which|how|why|who)\b", re.I)
SCHEDULE_WORDS = re.compile(r"\b(hours?|time|(monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?|weekends?|weekdays?)\b", re.I)


BRANCH_NAME = re.compile(r"\b((?:[A-Z][\w.'’-]+\s+(?:(?:and|or|&)\s+)?)+)(?:branch|branches|office|offices|location|locations)\b")
NOT_BRANCH_NAMES = frozenset("the a an this that our your each every any all new nearest closest main other its their".split())


class BranchNames:
    """'Which branches serve Hy-Vee members?' needs a branch NAME ('Key West and Sycamore Street branches'),
    other than the ones the question already contains ('Dupaco Hy-Vee branch' doesn't answer it)."""
    def __init__(self, question_names):
        self.skip = {n.lower() for n in question_names} | NOT_BRANCH_NAMES

    def search(self, text: str):
        for m in BRANCH_NAME.finditer(text):
            if m.group(1).split()[-1].lower() not in self.skip:
                return m
        return None


def is_status(question: str) -> bool:
    """'Is the Hy-Vee branch still open?' (but not 'Is the lobby open on Saturday?', an hours question,
    nor 'After the Hy-Vee branch closed, which branches serve its members?', a which-question)."""
    return bool(STATUS.search(question)) and not SCHEDULE_WORDS.search(question) and not WH_WORD.search(question)


def answer_kind(question: str) -> tuple[str, Optional[re.Pattern]]:
    """What the question asks for (in words, for "I don't know" answers) and the shape it must have."""
    ql = question.lower()
    if "routing" in ql:
        return "a routing number", ROUTING
    if re.search(r"\bhow (many|often)\s+times\b|\bhow often\b", ql):
        return "how many times", TIMES     # "how many times has Forbes recognized Dupaco?" -> "the fifth time"
    m = re.search(r"\bhow many\s+(.+)|\bnumber of\s+(.+)", ql)
    if m:
        words = [w for w in WORD.findall(m.group(1) or m.group(2)) if w not in STOP]
        # a count is not a $ amount, a year or a duration ("over 18 years of age")
        count = r"(?<![$\d.,])(?!(?:19|20)\d\d\b)\d[\d,]*\+?(?!\s*(?:years?|months?|days?|hours?|%|percent)\b)"
        if words and words[0] in ("people", "persons", "individuals", "folks"):
            return "that number", re.compile(rf"{count}\s+[A-Za-z]")    # "how many people used VTO?" -> "294 employees"
        if words:   # "how many branches": "22 branch office locations" or "membership has grown to more than 179,000"
            noun = re.escape(stem(words[0]))
            if noun.endswith("y"):
                noun = noun[:-1] + "(?:y|ies)"     # the stem "county" must still match "118 counties"
            return "that number", re.compile(rf"{count}\s+(?:[\w’'-]+\s+){{0,3}}{noun}|\b{noun}\w*\s+(?:[\w’'-]+\s+)"
                                             rf"{{0,5}}(?:more than|over|nearly|about|approximately|almost|exceeding)\s+{count}", re.I)
    # the phone as a way to pay ("the fee when payment is made BY PHONE versus online") asks for an amount
    channel = re.search(r"\b(?:by|over the|via|through the|on the)\s+(?:phone|telephone)\b", ql) and \
        re.search(r"\b(fees?|costs?|charges?|price|how much)\b", ql)
    if not channel and re.search(r"\b(phone|telephone|call|contact)\b", ql) or \
            re.search(r"\b(change|update|correct)\b.*\b(address|email|name)\b", ql):   # "how do I update my info" -> call ...
        return "a phone number", PHONE
    if is_status(ql):
        return "a date", DATE  # "is the Hy-Vee branch still open today?" -> its closing date
    if re.search(r"\b(cut-?off|deadline)\b", ql):
        return "a cutoff time", TIME     # "daily cutoff time for a same-day wire?"
    if re.search(r"\b(hours?|what time|open until|close at|closing time|opening time)\b", ql) or \
            (re.search(r"\b(when|open|close)\b", ql) and SCHEDULE_WORDS.search(ql)) or \
            (re.search(r"\b(when|open|close)\b", ql) and re.search(r"\b(lobby|lobbies|drive[- ]?(up|thru|through))\b", ql)):
        return "hours", TIME   # "when is the lobby open?" asks for hours; "when does the Hy-Vee branch close?" for a date
    # "when" asking for a date, not "the fee WHEN payment is made by phone"
    if re.search(r"(?:^|[,;?.]\s*)when\b|\bwhen\s+(?:does|do|did|is|was|will|can|could|should|are|were|would|has|"
                 r"have|must)\b|\bwhen\s+(?:the|it|its|my|our|a|an|this|that)\s+(?:[\w'-]+\s+){0,3}(?:opens?|opened|"
                 r"closes?|closed|starts?|started|ends?|ended|expires?|expired|matures?|launch\w*|begins?|began|"
                 r"changed?|took effect|takes effect)\b|\b(what date|which date|what day)\b", ql) or is_status(ql):
        return "a date", DATE
    if re.search(r"\bwhich (branch|branches|location|locations|office|offices)\b", ql) or \
            (re.search(r"\bwhere (do|should|can|could) (i|we|members?|they) (go|bank)\b", ql)
             and not re.search(r"\bonline\b|\bgo to (join|apply|open|sign|enroll|find|see|check)", ql)):
        return "a branch", None    # the pattern is built in search(): a branch name the question doesn't contain
    if re.search(r"\b(link|url|web ?address|website|web ?page)\b", ql) or \
            re.search(r"\b(join|apply|sign up|open|enroll|register)\b.*\bonline\b", ql):
        return "a link", URL
    if re.search(r"\b(address|located|location of|where is|where's)\b", ql):
        return "an address", ADDRESS
    # "1st Rate Checking" is a name, and "what credit score do I need for the 6.25% rate?" asks for a requirement
    if RATE_WORDS.search(re.sub(r"\b(1st|first) rate\b", " ", ql)) and \
            not re.search(r"\b(credit score|qualif\w*|requirement\w*|eligib\w*|ltv|loan.to.value)\b", ql):
        return "a rate", RATE_VALUE
    if re.search(r"\b(how much|fee|cost|charge|price|limits?)\b", ql):
        return "an amount", MONEY
    return "", None


# ---------------------------------------------------------------- what the question is about

NOT_NAMES = frozenset("""dupaco i visa january february march april may june july august september october november
december monday tuesday wednesday thursday friday saturday sunday""".split())
# words that start a question: a capitalised first word is a name only if it isn't one of these ("Mullan Avenue ...?")
STARTERS = frozenset("""what how is are can could do does did when where who whom whose which why will would should
tell give please i my the a an any list show get find has have was were may after before if in on for at as
there this that hi hello hey so and but okay ok last next since provide describe explain help need want
looking also thanks thank during until within between from by with without about compare state name check
confirm verify summarize using according based assuming suppose imagine im we're our its their these those
sorry quick question just again same different every each all both either neither""".split())
PRODUCT_NOUN = re.compile(r"\b([a-z][a-z-]+)\s+(?:(?:credit|debit|savings|checking)\s+)?"
                          r"(?:loans?|accounts?|cards?|mortgages?|certificates?|lines? of credit|propert(?:y|ies))\b")


GENERIC_ACRONYMS = frozenset("url apr apy aba faq pdf usa us".split())
# Credit-union words that don't single out a product: a "share certificate" is just a certificate.
GENERIC_KINDS = frozenset("share savings checking regular standard new deposit".split())


def subject(question: str, idf: dict) -> tuple[str, set, set]:
    """The specific thing a question is about: its names ("Mullan Avenue", "Galena"), acronyms ("ARM")
    or the kind of product ("construction" loan). Returns (the phrase as asked, its search terms,
    the terms of its proper names only: those must exist on the site at all, its acronyms)."""
    words = re.findall(r"[A-Za-z][A-Za-z'’$-]*", question)
    base = lambda w: re.split(r"['’]", w.lower())[0]
    # the first word is capitalised anyway: it is a name only as part of a longer one ("Mullan Avenue ...?"),
    # not in "Number of branches?" or "Sorry, what was the routing number?"
    first_ok = len(words) > 1 and words[1][0].isupper() and base(words[0]) not in STARTERS
    # every sentence's first word is capitalised anyway ("... routing number. What exact values ...?")
    starts = {m.end() for m in re.finditer(r"[.?!:;]\s+", question)}
    at_start = [k > 0 and question.find(w) in starts and base(w) in STARTERS for k, w in enumerate(words)]
    names = [w for k, w in enumerate(words) if w[0].isupper() and not w.isupper() and not at_start[k]
             and (k > 0 or first_ok) and base(w) not in NOT_NAMES and not re.fullmatch(r"(?i)po-?box", w)]
    acronyms = [w for w in words if len(w) > 1 and w.isupper() and w.lower() not in GENERIC_ACRONYMS]
    kinds = [m for m in PRODUCT_NOUN.finditer(re.sub(r"(?<=[a-z])-(?=[a-z])", " ", question.lower()))
             if m.group(1) not in STOP and m.group(1) not in GENERIC_KINDS]   # "student-loan page" = student loan
    phrase = " ".join(names + acronyms) or (kinds[0].group(0) if kinds else "")
    return (phrase, set(tokens(" ".join(names + acronyms + [m.group(1) for m in kinds]))),
            set(tokens(" ".join(names))), {a.lower() for a in acronyms})


RUN = re.compile(r"[A-Z][\w'’-]*(?:\s+[A-Z][\w'’-]*)+")
RUN_GENERIC = frozenset(tokens("program programs account accounts loan loans card cards rate rates branch branches "
                               "office plan the of and dupaco po box"))


def name_runs(question: str) -> list:
    """Multi-word capitalised names as token lists: 'Visa Signature' -> ['visa', 'signatur'];
    'Mineral Point Road' -> [...]. A sentence's first word is capitalised anyway and is dropped if it starts a
    question; months, Dupaco and generic product words don't count."""
    out = []
    for m in RUN.finditer(question):
        words = m.group(0).split()
        if (not question[:m.start()].strip() or re.search(r"[.?!:]\s*$", question[:m.start()])) and \
                re.split(r"['’]", words[0].lower())[0] in STARTERS:
            words = words[1:]
        toks = [t for w in words if re.split(r"['’]", w.lower())[0] not in NOT_NAMES - {"visa"}
                for t in tokens(w) if t not in RUN_GENERIC and not t.isdigit()]
        if len(toks) >= 2:
            out.append(toks)
    return out


def abbrev_in(token: str, terms) -> bool:
    """'avenu' is in the context, or an abbreviation of it is ('ave')."""
    return token in terms or any(len(x) >= 3 and token.startswith(x) for x in terms)


def dont_know(text: str) -> "Hit":
    return Hit(text=f"I don't know: {text} Please contact Dupaco or visit https://www.dupaco.com/contact.",
               doc=None, quote="", confident=False)


# ---------------------------------------------------------------- retrieval

def build_definitions(view) -> dict:
    """Terms the site defines with a list: '...in Dupaco's charter area:' + '- Iowa: Any county' ...
    -> {'charter area': 'Iowa: Any county; Illinois: Carroll, ...; Wisconsin: ...'} (newest page wins)."""
    found = {}
    for doc in sorted(view.pages.values(), key=lambda d: d.published or date.min):
        if doc.kind in ("expired", "listing"):
            continue
        sents = [s for c in doc.chunks for s, _ in c.sents]
        for k, s in enumerate(sents[:-1]):
            m = re.search(r"([A-Za-z][\w’'-]*(?:\s+[A-Za-z][\w’'-]*)?)\s*:\**$", LINK_ONLY.sub(r"\1", s).strip())
            if not m or not sents[k + 1].startswith(BULLET):
                continue
            items = []
            for x in sents[k + 1:k + 12]:
                item = re.sub(r"^[-*\s]+", "", x).replace("**", "")
                labelled = re.match(r"^[\w .’'-]{1,30}:", item)
                if not x.startswith(BULLET) or (items and bool(labelled) != bool(re.match(r"^[\w .’'-]{1,30}:", items[0]))):
                    break     # the list ends where its items stop looking alike ("Iowa: Any county" vs a GPA rule)
                items.append(item)
            if len(items) >= 2:
                found[m.group(1).lower()] = "; ".join(items)
    return found


def expand_definitions(text: str, defs: dict, question: str = "") -> str:
    """An answer that links a term the site defines elsewhere ('[charter area](map.jpg)'), or answers a question
    naming such a term ("Which Illinois counties are in the charter area?"), gets the site's definition."""
    extra, seen = [], set()
    terms = LINK_ONLY.findall(text) + [t for t in defs if len(t) > 6 and re.search(rf"\b{re.escape(t)}\b", question.lower())]
    for term in terms:
        d = defs.get(term.lower().strip())
        if d and d not in seen and d not in text:
            seen.add(d)
            extra.append(f"{term[0].upper()}{term[1:]}: {d}")
    return text + ("\n" + "\n".join(extra) if extra else "")


def build_idf(view) -> dict:
    df, n = Counter(), 0
    for doc in view.pages.values():
        for ch in doc.chunks:
            df.update(ch.terms)
            n += 1
    return {t: math.log(1 + n / c) for t, c in df.items()}


def candidate_chunks(view, q: set):
    """Every chunk sharing a word with the question. Expired and listing pages never answer."""
    for doc in view.pages.values():
        if doc.kind in ("expired", "listing"):
            continue
        for ch in doc.chunks:
            if q & ch.terms:
                yield doc, ch


ANAPHORA = re.compile(r"^(This|That|It|These|Those|They|He|She)\b")


BULLET = ("- ", "* ")


COVER_STOP = frozenset(tokens("not no yes can could will would must may might should does did is are was were "
                              "also still yet ever never i'm im"))


def cover_rest(doc, ch, text: str, q: set, idf: dict) -> str:
    """'Does the student-loan page permit deferring payments, name a GRADUATED option, and charge an ORIGINATION
    fee?': the chosen sentences answer one part; sentences of the same section (same heading, on the same page) that
    hold the parts still unanswered are added, at most two. Never another section: a neighbouring branch, product
    or speaker is not what was asked."""
    floor = 0.25 * max(idf.values(), default=0.0)      # specific words only, whatever the size of the site
    asked = {t for t in q - SHAPE_WORDS - KEY_IGNORE - COVER_STOP
             if idf.get(t, 0.0) >= floor and not re.fullmatch(r"[\d,.]+", t)}
    missing = asked - set(tokens(text))
    if len(asked) < 3 or not missing:
        return ""
    # its own section; another section of the page only for a sentence holding two of the missing parts
    added = []
    for _ in range(2):
        best = max(((sum(idf.get(t, 0.0) for t in missing & terms), -c.pos, -k, s)
                    for c in doc.chunks for k, (s, terms) in enumerate(c.sents)
                    if s not in text and s not in added
                    and len(missing & terms) >= (1 if c.heading == ch.heading else 2)),
                   default=None)
        if best is None:
            break
        added.append(best[3])
        missing -= set(tokens(best[3]))
    return "".join(f" {s}" for s in added)


def compose(ch, i: int) -> str:
    """The winning sentence + the next one or two; if it introduces a bullet list, the whole list;
    if it IS one bullet of a list, the whole list (one eligibility rule out of three is a wrong answer).
    A sentence that starts with "This/It/They ..." gets the sentence before it, so it makes sense alone."""
    if ch.sents[i][0].startswith(BULLET):
        a = i
        while a > 0 and ch.sents[a - 1][0].startswith(BULLET):
            a -= 1
        run = [s for s, _ in ch.sents[a:]]
        return "\n".join(s for k, s in enumerate(run) if k <= 10 and all(x.startswith(BULLET) for x in run[:k + 1]))
    parts = [ch.sents[i][0]]
    if i > 0 and ANAPHORA.match(parts[0]):
        parts.insert(0, ch.sents[i - 1][0])
    rest = [s for s, _ in ch.sents[i + 1:]]
    if rest and rest[0].startswith(BULLET):
        for s in rest:
            if not s.startswith(BULLET) or len(parts) > 10:
                break
            parts.append(s)
        return "\n".join(parts)
    visible = lambda x: len(LINK_ONLY.sub(r"\1", x))     # a long link URL is not a long answer
    for s in rest[:2]:
        if visible(" ".join(parts)) + visible(s) > 400:
            break
        parts.append(s)
    return " ".join(parts)


# ---------------------------------------------------------------- "is it still open?"

FULL_DATE = rf"\b{MONTH}\s+\d{{1,2}},?\s+\d{{4}}\b"
CLOSING = re.compile(rf"\b(clos\w*|discontinu\w*|end\w*|expir\w*)\b[^.]{{0,60}}?({FULL_DATE})", re.I)


UNANNOUNCED = re.compile(r"\b(?:will be announced|to be announced|not (?:yet )?(?:been )?announced|have not announced|"
                         r"has not announced|haven't announced|hasn't announced|dates? (?:are |is )?(?:tbd|tba))\b", re.I)


def status_prefix(question: str, text: str, today: date) -> str:
    """'Is the Hy-Vee branch still open?' + 'This location will close March 31, 2026.' -> 'No. ...';
    'Is the Hy-Vee branch closed?' asks the opposite, so the same facts answer 'Yes. ...'."""
    if not is_status(question) or WH_QUESTION.match(question):
        return ""         # "when was the Hy-Vee branch closed?" wants the date, not a yes or no
    m = CLOSING.search(text)
    d = parse_long_date(m.group(2)) if m else None
    if d is None:
        return ""
    when = f"{d:%B} {d.day}, {d.year}"
    closed_asked = bool(CLOSED_ASKED.search(question)) and not re.search(r"\bstill\b.*\bopen\b", question, re.I)
    if d <= today:
        return f"{'Yes' if closed_asked else 'No'}. It was scheduled to close on {when}, and that date has passed. "
    if closed_asked:
        return f"Not yet: it is scheduled to close on {when}. "
    return f"Yes, for now: it is scheduled to close on {when}. "


# ---------------------------------------------------------------- the search

@dataclass
class Hit:
    text: str
    doc: object
    quote: str
    confident: bool = True
    also: tuple = ()          # other pages that print the same value(s): extra sources, most trusted first


# values specific enough that another page printing them states the same fact
KEY_VALUE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?|\b\d+(?:\.\d+)?%|\b\d{9}\b|\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b"
                       r"|\b\d{1,2}:\d\d\b|\b[\w-]+(?:\.[\w-]+)*\.(?:com|org)(?:/[\w-]+)*")


SITE_LINK = re.compile(r"https?://(?:www\.)?dupaco\.com[^\s)\]]*")


def linked_pages(view, text: str, exclude) -> tuple:
    """Site pages the answer itself points to ('All locations: https://www.dupaco.com/contact')."""
    out = []
    for m in SITE_LINK.finditer(text):
        d = view.pages.get(canonical_url(m.group(0).rstrip(".,")))
        if d is not None and all(d is not x for x in list(exclude) + out):
            out.append(d)
    return tuple(out)


def corroborate(view, doc, text: str, limit: int = 4) -> tuple:
    """Pages besides `doc` whose text contains every key value of the answer sentence (routing number,
    amount, time, link), most trusted then newest first. Nothing for a sentence without such values."""
    vals = list(dict.fromkeys(m.group(0) for m in KEY_VALUE.finditer(text)))[:3]
    if not vals:
        return ()
    found = [d for d in view.pages.values()
             if d is not doc and d.kind not in ("expired", "listing") and all(v in d.text for v in vals)]
    found.sort(key=lambda d: (-d.authority, -(d.published or date.min).toordinal(), d.url))
    return tuple(found[:limit])


LINK_ONLY = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# Product words: a question that names one must be answered by text about it (its sentence,
# heading or neighbours), so "student ... loan options" is not answered by a scholarship sentence.
PRODUCT_WORDS = frozenset(tokens("loan card account certificate mortgage savings checking insurance "
                                 "atm branch ira visa wallet"))


# ---------------------------------------------------------------- the same statement on many pages

QUANTITY = frozenset(tokens("over more than nearly about approximately almost exceeding"))
YEAR = re.compile(r"\b(?:19|20)\d\d\b")
REPEATED = 3          # a statement on at least this many pages counts as "repeated"


def signature(terms: frozenset) -> frozenset:
    """'It has over 600 employees and 22 branch office locations.' and 'It has nearly 600 employees
    and 23 branch office locations.' -> the same signature: numbers become '#', quantity words drop."""
    return frozenset("#" if t[0].isdigit() else t for t in terms if t not in QUANTITY)


def same_statement(a: frozenset, b: frozenset) -> bool:
    return bool(a and b) and len(a & b) / len(a | b) >= 0.6


def repeated_statement(near, cands):
    """The best-supported statement among the near-ties, if it appears on >= REPEATED pages:
    all candidate sentences that say the same thing (possibly reworded, with other numbers)."""
    sigs = [signature(x[2].sents[x[3]][1]) for x in cands]
    best, support = None, 0
    for c in sorted(near, key=lambda c: -c[0])[:30]:
        sig = signature(c[2].sents[c[3]][1])
        group = [x for x, s in zip(cands, sigs) if same_statement(sig, s)]
        pages = len({x[1].key for x in group})
        if pages > support:
            best, support = group, pages
    return best if support >= REPEATED else None


def newer_wording(rep, cands):
    """Boilerplate gets reworded over the years: 'membership totals more than 141,000 with assets exceeding
    $2.6 billion' (2020-23 releases) became 'membership has grown to more than 179,000 with assets exceeding
    $3.6 billion'. If another repeated statement (3+ pages) about the same thing (shares at least a third of the
    words) has a newer copy, that wording is the current one."""
    newest = lambda group: max(x[1].published or date.min for x in group)
    sig = signature(rep[0][2].sents[rep[0][3]][1])
    pool = [c for c in cands if c[1].published and re.search(r"\d", c[2].sents[c[3]][0])]
    sigs = {id(c): signature(c[2].sents[c[3]][1]) for c in pool}
    related = [c for c in pool if sigs[id(c)] and len(sig & sigs[id(c)]) / len(sig | sigs[id(c)]) >= 0.3]
    best, best_date = rep, newest(rep)
    for c in sorted(related, key=lambda c: c[1].published, reverse=True)[:20]:
        if c[1].published <= best_date:
            break
        group = [x for x in related if same_statement(sigs[id(c)], sigs[id(x)])]
        if len({x[1].key for x in group}) >= REPEATED:
            best, best_date = group, newest(group)
            break
    return best


def earlier_years(sent, doc, cands) -> str:
    """Year-labelled statistics are history, not conflicts (user decision, 2026-10-18):
    '256 employees used VTO in 2024' is answered together with '294 ... in 2023'."""
    m = YEAR.search(sent[0])
    if not m:
        return ""
    sig, seen, out = signature(sent[1]), {m.group(0)}, []
    others = sorted((x for x in cands if x[1] is not doc), key=lambda x: x[1].published or date.min, reverse=True)
    for x in others:
        s = x[2].sents[x[3]]
        y = YEAR.search(s[0])
        if y and y.group(0) not in seen and same_statement(sig, signature(s[1])):
            seen.add(y.group(0))
            out.append(re.sub(r"^[-*\s]+", "", s[0]).replace("**", ""))
        if len(out) == 2:
            break
    return ("\nEarlier years: " + " ".join(out)) if out else ""


SCHED_LINE = re.compile(r"^\W*(lobby|drive[- ]?up|branch hours|(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\b)", re.I)


def schedule_block(doc, ch, i: int) -> str:
    """The run of schedule lines around sentence i: 'Branch hours are: Lobby Monday-Friday: ... Drive-up ...'.
    A schedule can run on into the page's next chunk, so this works on the whole page's sentences."""
    s = [x for c in doc.chunks for x in c.sents]
    i += sum(len(c.sents) for c in doc.chunks[:ch.pos])
    j = next((k for k in range(i, min(i + 3, len(s))) if SCHED_LINE.match(s[k][0])), None)
    if j is None:
        return ""
    a, b = j, j
    while a > 0 and SCHED_LINE.match(s[a - 1][0]):
        a -= 1
    while b + 1 < len(s) and SCHED_LINE.match(s[b + 1][0]):
        b += 1
    return " ".join(x[0].replace("**", "").strip() for x in s[a:b + 1])


def hours_overview(cands) -> Optional[Hit]:
    """'What are your lobby hours?' with no branch named: hours differ by branch, so list the different
    schedules the site gives (most common first) instead of passing one branch's hours off as everyone's."""
    blocks = {}
    for c in cands:
        text = schedule_block(c[1], c[2], c[3])
        if not TIME.search(text):
            continue
        key = re.sub(r"\s+", " ", re.sub(r"\s*[–—-]\s*", "-", text.lower()))
        pages, newest, _, docs = blocks.get(key, (set(), date.min, text, []))
        pages.add(c[1].key)
        docs.append(c[1])
        blocks[key] = (pages, max(newest, c[1].published or date.min), text, docs)
    if len(blocks) < 2:
        return None
    ranked = sorted(blocks.values(), key=lambda b: (-len(b[0]), b[1]), reverse=False)[:4]
    lines = [f"{k}) {text}" for k, (_, _, text, _) in enumerate(ranked, 1)]
    # one source per schedule shown (its most trusted, newest page), then the other pages of the first one
    unique = lambda docs: list({id(d): d for d in docs}.values())       # PageDoc isn't hashable
    best = lambda docs: sorted(unique(docs), key=lambda d: (-d.authority, -(d.published or date.min).toordinal(), d.url))
    docs = unique([best(b[3])[0] for b in ranked] + best(ranked[0][3]))
    return Hit(text="Hours vary by branch. These schedules are listed on the website:\n" + "\n".join(lines)
                    + "\nWhich branch do you need? All locations: https://www.dupaco.com/contact",
               doc=docs[0], quote=ranked[0][2], also=tuple(docs[1:5]))


def main_number(cands):
    """'What's your phone number?' with no branch or team named: the number printed on the most pages
    (800-373-7600 is on ~60). Only for phone numbers: for counts, the most repeated value is often the old one."""
    pages = Counter()
    found = {}
    for c in cands:
        nums = {re.sub(r"\D", "", m.group(0)) for m in PHONE.finditer(compose(c[2], c[3]))}
        found[id(c)] = nums
        for n in nums:
            pages[n] += 1
    if not pages:
        return cands
    top = pages.most_common(1)[0][0]
    return [c for c in cands if top in found[id(c)]]


def mentions(c, term: str, acronyms: set, abbrev: bool = False) -> bool:
    """Does the candidate's context mention the term? An acronym the question wrote in capitals also
    counts when spelled out: 'VTO' is mentioned by '... called Volunteer Time Off ...'."""
    if term in context(c) or (abbrev and abbrev_in(term, context(c))):   # a name: "avenu" is mentioned by "Ave."
        return True
    if term not in acronyms or len(term) < 3:
        return False
    initials = "".join(w[0].lower() for w in re.findall(r"[A-Za-z]+", compose(c[2], c[3])))
    return term in initials


def context(c) -> frozenset:
    """A candidate sentence's words plus its heading path's and its neighbours'."""
    ch, i = c[2], c[3]
    out = set(ch.head_terms)
    for j in (i - 1, i, i + 1):
        if 0 <= j < len(ch.sents):
            out |= ch.sents[j][1]
    return frozenset(out)


# Members' words -> the site's words (only the question is rewritten).
SYNONYMS = [(re.compile(r"\b(?:expiry|expiration)\b", re.I), "expires"),       # "its expiry clock" ~ "expires eight months ..."
            # "a penalty for paying it off early" ~ "no prepayment penalties"
            (re.compile(r"\bpay(?:ing|s)?\s+(?:[\w-]+\s+){0,4}?off\s+early\b|\bpay(?:ing|s)?\s+off\s+(?:[\w$,.-]+\s+){0,5}?early\b"
                        r"|\bearly\s+pay-?off\b", re.I), lambda m: m.group(0) + " (prepayment)"),   # keeps "student loan"
            (re.compile(r"\bbecome (?:a |an )?(?:dupaco )?member\b", re.I), "join as a member"),
            (re.compile(r"\b(?:apply for|sign up for|get) (?:a )?membership\b", re.I), "join as a member"),
            (re.compile(r"\bwho (?:can|may|is allowed to) join\b", re.I), "who is eligible to join"),
            (re.compile(r"\bmembership (?:requirements?|eligibility|criteria|rules)(?: rules)?\b", re.I), "eligible to join as a member"),
            (re.compile(r"\b(?:can|could|may) (?:anyone|anybody|someone|everyone) (?:join|become a member)\b", re.I),
             "who is eligible to join"),
            (re.compile(r"\bborrow(?:ing)? (?:money )?(?:to pay )?for (?:college|school|university|tuition)\b", re.I), "student loan"),
            (re.compile(r"\b(?:staff|staffers|team members|workers|employes)\b", re.I), "employees"),
            (re.compile(r"\bdrive[- ]?(?:thru|through)s?\b", re.I), "drive-up"),
            (re.compile(r"\blobbies\b", re.I), "lobby")]
# Question words that carry no topic ("how many branches does Dupaco operate NOW?", "what has Forbes SAID?")
FILLER = frozenset(tokens("now currently current today presently right said say says nowadays these days "
                          "operate operates run runs own owns about carry carries offer offers provide provides "
                          "through via"))
# Words about the archive or the answer's form, never about the thing asked: they can't be the word a typed value's
# text must contain ("what APRs were SHOWN on the 2026-05-12 SNAPSHOT BOUNDARY", "the LOWEST its rate can GO")
KEY_IGNORE = frozenset(tokens("shown show shows showed displayed listed list lists published posted snapshot snapshots "
                              "crawl crawls crawled recrawl boundary captured downloaded copy copies version latest "
                              "newest recent most supplied available matching match exact exactly give only highest "
                              "lowest maximum max least top bottom floor ceiling cap capped band bands range ranges "
                              "reach go run compare compared comparison versus vs difference january february march "
                              "april may june july august september october november december explain describe "
                              "clock clocks timing rule rules detail details summarize tell"))
# words that only say WHICH kind of answer is wanted: "what's the LINK to the branch locator?" is about the locator
KIND_WORDS = {"a link": frozenset(tokens("link links url urls website web page site online address")),
              "that number": frozenset(tokens("number count total"))}
# words that only name the answer shape, never what it is about: "what NUMBER do I CALL if my card is stolen?"
SHAPE_WORDS = frozenset(tokens("number numbers call phone telephone extension ext contact address located location "
                               "hours open time link url website page date day when"))
AMOUNT_WORDS = frozenset(tokens("fee fees cost costs charge charges price prices much pay amount limit limits "
                                "per month monthly daily"))
CHANNEL_WORDS = frozenset(tokens("phone telephone"))
RATE_SHAPE_WORDS = frozenset(tokens("rate rates interest apr aprs apy apys yield dividend percentage"))
# "has the number of branches CHANGED?" asks about time, not about sentences that contain "changed"
CHANGE_ASKED = re.compile(r"\b(changed|previous(ly)?|used to|increased|decreased|raised|lowered|dropped)\b", re.I)
CHANGE_WORDS = frozenset(tokens("changed change previous previously used increased decreased raised lowered dropped"))
# A call to action ("For more information ... visit ...", "Learn more") points elsewhere instead of answering
CTA = re.compile(r"^\W*(for more (information|details)|to learn more|learn more|click here|find out more|visit\b|"
                 r"apply (now|today|online)|contact us|call us|get started)", re.I)


def search(view, question: str, idf: dict, today: date, defs: Optional[dict] = None,
           published_by: Optional[date] = None) -> Optional[Hit]:
    """published_by: for a date before the first download, news/blog pages published after it didn't
    exist yet on that day, so they can't answer."""
    for rx, repl in SYNONYMS:
        question = rx.sub(repl, question)
    if re.search(r"\b(address|located|location|where|hours|open)\b", question, re.I):
        question = re.sub(r"\boffice\b", "branch", question, flags=re.I)    # "the Galena office" is a branch
    q = set(tokens(question)) - FILLER
    if CHANGE_ASKED.search(question):
        q = (q - CHANGE_WORDS) or q
    kind, pattern = answer_kind(question)
    q = (q - KIND_WORDS.get(kind, frozenset())) or q
    if not q:
        return None
    # "I don't know" only when the site truly doesn't know (user decision, 2026-10-19):
    # (a) the question names something the site never mentions
    phrase, about, names, acronyms = subject(question, idf)
    missing = [t for t in names if t not in idf]
    if missing and phrase:
        return dont_know(f"the website doesn't mention {phrase}.")
    products = q & PRODUCT_WORDS
    # the kind of product named ("STUDENT loan", "PERSONAL loan", "share-SECURED loan"): text about another kind
    # (a home equity loan's "no penalty for paying it off early") doesn't answer it
    kind_words = sorted({m.group(1) for m in PRODUCT_NOUN.finditer(re.sub(r"(?<=[a-z])-(?=[a-z])", " ", question.lower()))
                         if m.group(1) not in STOP and m.group(1) not in GENERIC_KINDS})
    # (matched as whole words, not stems: "personalized repayment plans" is not about a PERSONAL loan)
    if kind == "a branch":
        pattern = BranchNames(re.findall(r"[A-Z][\w'’-]+", question))
    cands = []
    for doc, ch in candidate_chunks(view, q):
        if published_by and doc.published and doc.published > published_by:
            continue
        head = q & ch.head_terms
        for i, (sent, terms) in enumerate(ch.sents):
            own = q & terms
            visible = LINK_ONLY.sub(r"\1", sent).rstrip(" *_>")
            bare_link = not LINK_ONLY.sub("", sent).strip(" -*_>|·.:")
            listed = sent.startswith(BULLET) and q & ch.sect_terms     # a bullet under "Who can join"-like section
            if not (own or listed) or visible.endswith("?") or (bare_link and pattern is not URL):
                continue      # a question (FAQ link, form label) is never the answer; a bare link only for "which link?"
            near = set()
            for j in (i - 1, i + 1):
                if 0 <= j < len(ch.sents):
                    near |= q & ch.sents[j][1]
            own |= q & ch.sect_terms          # its own section title ("You're Eligible to Join ...") counts fully
            # sums over sets are rounded: float addition in a set's (per-run random) order would otherwise break
            # ties differently from one run to the next
            own_w = round(sum(idf.get(t, 0.0) for t in sorted(own)), 6)
            score = round(own_w + 0.5 * sum(idf.get(t, 0.0) for t in sorted((head | near) - own)), 6)  # title, neighbours: half
            if products and not products & (own | head | near):
                score *= 0.5
            cta = bool(CTA.match(visible)) and pattern not in (URL, PHONE)
            if cta:
                score *= 0.5          # "For more information about Home$tart, visit ..." doesn't say what it is
            cands.append((score, doc, ch, i, (not cta, len(own), own_w)))
    # (a) also for an acronym: one the site never prints, not even spelled out ("SWIFT code"), is unknown
    # a kind only if the site titles a product that way ("Student Loans", "Home Equity Loan"): "posted mortgage
    # rates", "supported card types", "hourly account research" name no product
    titled = [w for w in kind_words if not w.endswith(("ed", "ing")) and any(
        re.search(rf"\b{re.escape(w)}s?\s+(?:[a-z]+\s+)?(?:loans?|cards?|accounts?|mortgages?|certificates?|lines? of credit)\b",
                  c[2].heading, re.I) for c in cands)]
    if titled:
        # text about the named kind (in its heading or around it - not the URL: every consumer page's URL says
        # "personal"), when there is any; otherwise every candidate stays
        kind_rx = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in titled) + r")s?\b", re.I)
        about_kind = lambda c: kind_rx.search(" ".join([c[2].heading] + [x for x, _ in c[2].sents[max(0, c[3] - 1):c[3] + 2]]))
        cands = [c for c in cands if about_kind(c)] or cands
    unknown_acr = [a for a in acronyms if len(a) > 2 and a not in idf]
    if unknown_acr and not any(mentions(c, a, acronyms) for a in unknown_acr for c in cands):
        return dont_know(f"the website doesn't mention {' '.join(a.upper() for a in unknown_acr)}.")
    if pattern is TIME and about:
        # a branch's hours are a schedule block under "The phone number for the Mineral Point Road branch is ...
        # Branch hours are:" in its opening release; the release as a whole is about that branch
        key = max(about, key=lambda t: (idf.get(t, 0.0), t))
        on_page = {id(d): any(key in ch.terms for ch in d.chunks) for d in {id(c[1]): c[1] for c in cands}.values()}
        sched = [(c, schedule_block(c[1], c[2], c[3])) for c in cands if on_page[id(c[1])]]
        sched = [(c, s) for c, s in sched if TIME.search(s)]
        if sched:
            c, block = max(sched, key=lambda x: (x[0][0], x[0][1].published or date.min, x[0][1].url))
            text = compose(c[2], c[3]).split("Branch hours are")[0].rstrip()     # the block repeats that line
            return Hit(text=f"{text} {block}".strip(), doc=c[1], quote=c[2].sents[c[3]][0])
    if pattern:
        # the needed shape must appear in what we would answer (the sentence and the one or two after it),
        # in text about the thing asked ("Mullan Avenue" hours, not some other branch's hours)
        if about:
            # text about the thing asked: the candidates mentioning the most of its words ("Pennsylvania Avenue
            # ... Dubuque"); and when the question also names a product ("Visa Signature CARD"), text about that
            # product, not a news story that happens to say "Signature"
            key = max(about, key=lambda t: (idf.get(t, 0.0), t))      # its most specific word must be there ("Mullan")
            cands = [c for c in cands if mentions(c, key, acronyms, abbrev=True)]
            count = {id(c): sum(mentions(c, t, acronyms, abbrev=True) for t in about) for c in cands}
            top = max(count.values(), default=0)
            cands = [c for c in cands if count[id(c)] == top]
            if products:
                cands = [c for c in cands if products & context(c)] or cands
        for run in name_runs(question):
            # a multi-word name must be there whole ("Visa Signature" is not a story about Signature Bank;
            # "Mineral Point Road"), allowing abbreviations ("Pennsylvania Ave.")
            cands = [c for c in cands if all(abbrev_in(t, context(c)) for t in run)]
        shape = AMOUNT_WORDS if pattern is MONEY else RATE_SHAPE_WORDS if pattern is RATE_VALUE else \
            frozenset() if kind == "a cutoff time" else None
        # the phone as the way to pay ("the fee to pay by PHONE") is what the amount is about, not an answer shape
        shapes = SHAPE_WORDS - CHANNEL_WORDS if pattern is MONEY else SHAPE_WORDS
        if shape is not None and q - shape - shapes:
            # an amount, rate or cutoff must be the one asked about: the "lost debit card REPLACEMENT" fee, the
            # "AUTO INSURANCE" premium (two words for an amount), the "EUROS" exchange rate, the WIRE cutoff - not
            # some other fee, rate or deadline. If no text has them, the site doesn't say
            # the keys are the question's most specific topic words - not its numbers, months or words about the
            # archive ("SHOWN on the SNAPSHOT"). A key no text with such a value contains means the site doesn't
            # give it ("EUROS" exchange rate): finding another word's value instead would answer something else
            words = {t for t in q - shape - shapes - KEY_IGNORE if not re.fullmatch(r"[\d,.]+", t)} or \
                q - shape - shapes
            if pattern is MONEY:
                # an amount: most of the question's three most specific words ("domestic", "international" wire;
                # both of "cashier" check) - one generic word ("check") can't let another fee answer. In a question
                # of several parts, the words of the part that asks the amount ("..., and charge an ORIGINATION fee?")
                priced = {t for p in re.split(r"[,;?]|\band\b|\bor\b", question)
                          if re.search(r"\b(fees?|costs?|charges?|price|how much)\b", p, re.I) for t in tokens(p)} & words
                top = sorted(priced or words, key=lambda t: (-idf.get(t, 0.0), t))[:3]
                need = -(-len(top) * 3 // 5)            # ceil(60%)
                cands = [c for c in cands if sum(mentions(c, t, acronyms | {t}) for t in top) >= need]
            else:
                keys = sorted(words, key=lambda t: (-idf.get(t, 0.0), t))[:1]
                cands = [c for c in cands if all(mentions(c, k, acronyms | {k}) for k in keys)]
        typed = [c for c in cands if pattern.search(compose(c[2], c[3]))]
        if not typed and pattern is DATE:   # a news release about the event is dated even if its text isn't
            typed = [c for c in cands if c[1].published]
        if not typed:   # (b) nothing on the site gives that kind of value for that thing
            return dont_know(f"the website doesn't list {kind} for {phrase or 'that'}.")
        if pattern is PHONE and not about:
            typed = main_number(typed)
        if pattern is TIME and not about:
            overview = hours_overview(typed)
            if overview:
                overview.also += linked_pages(view, overview.text, (overview.doc,) + overview.also)
                return overview
        rest = q - SHAPE_WORDS - AMOUNT_WORDS - about
        if rest and pattern is not MONEY:
            # prefer text holding the question's most specific other word ("STOLEN card" -> ext. 201, not ext. 204)
            key = max(rest, key=lambda t: (idf.get(t, 0.0), t))
            typed = [c for c in typed if key in context(c)] or typed
        cands = typed
    elif about and (names or acronyms):
        # no answer shape to check, but the question names something ("VTO usage last year?"): text about it
        key = max(about, key=lambda t: (idf.get(t, 0.0), t))
        cands = [c for c in cands if mentions(c, key, acronyms, abbrev=True)] or cands
    if not cands:
        return None
    asked_years = set(YEAR.findall(question))
    if asked_years:   # "how many ... in 2023": text about 2023, even if a newer article exists
        years = lambda c: set(YEAR.findall(compose(c[2], c[3])))
        dated = [c for c in cands if asked_years & years(c)
                 or (not years(c) and c[1].published and str(c[1].published.year) in asked_years)]
        if not dated and years(max(cands, key=lambda c: c[0])):
            # the site gives this figure year by year, just not for the year asked: another year's
            # number would be a wrong answer (user decision, 2026-10-21)
            return dont_know(f"the website doesn't give that figure for {' or '.join(sorted(asked_years))}.")
        cands = dated or cands
    best = max(c[0] for c in cands)
    near = [c for c in cands if c[0] >= 0.9 * best]

    # 0) a statement the site repeats on many pages (press-release boilerplate) beats a one-off
    #    mention; among its copies the newest publish date wins (user decision, 2026-10-18)
    rep = repeated_statement(near, cands)
    if rep:
        rep = newer_wording(rep, cands)
        doc = max(rep, key=lambda c: (c[1].published or date.min, c[1].authority, c[0], c[1].key))[1]
    else:
        # 1) which page answers: near-ties settled by trust, then publish date
        doc = max(near, key=lambda c: (c[1].authority, c[1].published or date.min, c[0],
                                       len(q & c[2].head_terms),     # tie: the page whose title/URL is about it
                                       c[1].key, -c[2].pos, -c[3]))[1]
    # 2) where on that page: the sentence holding the most (and rarest) question words itself;
    #    ties go to the earliest (news puts the key fact first)
    mine = [c for c in cands if c[1] is doc]
    most = max(c[4] for c in mine)
    _, doc, ch, i, _ = min((c for c in mine if c[4] == most), key=lambda c: (c[2].pos, c[3]))

    text = compose(ch, i) + cover_rest(doc, ch, compose(ch, i), q, idf)
    section = ch.heading.split(" > ")[-1].strip()
    if section and len(section) <= 60 and not re.search(r"\d", section) and section.lower() not in text.lower():
        text = f"{section}: {text}"       # context ("Student Loans: ..."); never a heading with a number in it
    if SCHEDULE_WORDS.search(question) and not TIME.search(text):
        block = schedule_block(doc, ch, i)       # "the Platteville branch's phone number AND its Saturday hours"
        if TIME.search(block):
            text = text.split("Branch hours are")[0].rstrip() + " " + block
    if pattern is DATE and not DATE.search(text) and doc.published:
        text += f" (Dupaco news release published {doc.published:%B} {doc.published.day}, {doc.published.year}.)"
    if (is_status(question) or re.search(r"\b(?:currently|now|still)\s+(?:open|accepting|available)\b|"
                                         r"\bopen (?:now|currently|today)\b", question, re.I)) \
            and UNANNOUNCED.search(text):
        # "Are applications open now?" + "the next cycle will be announced in 2036": the site doesn't say it is
        # open, and an old cycle's opening date is not the current one
        return dont_know("the website says the next dates have not been announced yet.")
    text = status_prefix(question, text, today) + text + earlier_years(ch.sents[i], doc, cands)
    also = corroborate(view, doc, ch.sents[i][0])
    also += linked_pages(view, text, (doc,) + also)
    return Hit(text=expand_definitions(text, defs or {}, question), doc=doc, quote=ch.sents[i][0], also=also[:6])
