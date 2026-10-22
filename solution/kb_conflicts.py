"""
Step 7 - where the website contradicts itself, which value is right, and why.

Two kinds of contradiction, both found on structured data (never by comparing raw text):

 1. RATE conflicts - the same rate fact printed with different numbers, either on two pages at the same
    time (a stale page still live: /homebuying-guidance 6.037% APR vs /rates 7.29% APR) or on the same
    page in different downloads (10-month jumbo certificate 3.90% -> 4.00%).
    "The same fact" = same product (family, name, qualifiers), same term, same balance/loan tier and
    overlapping model years. Different tiers or terms are different facts, never conflicts.
    One conflict per product + term (its tiers are listed together), to keep the list short.

 2. TEXT conflicts - one statement repeated across pages with different numbers: press-release
    boilerplate ("... 24 / 23 / 22 branch office locations") or a running count ("the fourth / fifth
    time Forbes recognized Dupaco"). Statistics labelled with a year ("256 employees in 2024") are
    history, not contradictions (user decision), and are skipped.

 3. PAGE changes - an undated page (product page, PDF) that changed a dollar figure or count between
    downloads: "hardship grants up to $2,000" -> "$3,500", "minimum cash back redemption $50.00" -> "$25.00".

The winner follows the same rules as answers: newest "effective as of" date, then page trust, decided
for the whole product table (kb_rate_qa.compete); for news text, the newest publish date; for an
undated page, its version in the newest download.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from kb_chunks import tokens
from kb_pages import observed_in
from kb_rate_qa import compete, fmt_date, fmt_row
from kb_search import same_statement, signature

ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
            "eighth": 8, "ninth": 9, "tenth": 10}
NUMBER = re.compile(r"(?<![\w$.,])(\d[\d,]*(?:\.\d+)?)(\+?)\s+((?:[A-Za-z’'-]+\s+){0,2}[A-Za-z’'-]+)|"
                    r"\b(" + "|".join(ORDINALS) + r")\s+(time)\b", re.I)
YEAR = re.compile(r"\b(?:19|20)\d\d\b")


@dataclass
class Found:
    topic: str
    values: list
    sources: list = field(default_factory=list)      # [(url, snapshot_id)]
    resolution: Optional[str] = None
    reason: Optional[str] = None


# ---------------------------------------------------------------- 1. rate conflicts

def _num_value(v: str) -> tuple:
    """'20.5%' and '20.50%' are the same number; '12.50% – 19.50%' -> (12.5, 19.5)."""
    return tuple(float(x) for x in re.findall(r"\d+(?:\.\d+)?", v))


def _common_differs(a: dict, b: dict) -> bool:
    shared = set(a) & set(b)
    return bool(shared) and any(_num_value(a[k]) != _num_value(b[k]) for k in shared)


def _same_slot(r1, r2) -> bool:
    if (r1.tier_lo, r1.tier_hi) != (r2.tier_lo, r2.tier_hi):
        return False
    if r1.years is None or r2.years is None:
        return r1.years == r2.years
    # 2023-26 vs 2024-27 share three model years: the same tier, renamed. 2021-23 vs 2023-26 share only
    # 2023: two different tiers.
    shared = min(r1.years[1], r2.years[1]) - max(r1.years[0], r2.years[0]) + 1
    return r1.years == r2.years or shared >= 2


def _topic(r) -> str:
    name = {"certificate": "certificate", "ira": "IRA certificate", "credit_card": "credit card",
            "money_market": "money market", "home_equity_loan": "home equity loan", "boat_rv": "boat & RV loan",
            "atv": "ATV loan", "auto": "auto loan", "personal_loan": "personal loan", "heloc": "HELOC",
            "home_improvement": "home improvement loan", "hsa": "health savings account"}.get(r.family, r.family)
    term = ""
    if r.term_months:
        term = f"{r.term_months // 12}-year " if r.term_months % 12 == 0 and r.term_months >= 120 else f"{r.term_months}-month "
    parts = [" ".join(sorted(r.quals)), r.name, term + name]
    return " ".join(p for p in parts if p).strip()


def _fact(r):
    return (r.tier_lo, r.tier_hi, r.years, tuple(sorted((k, _num_value(v)) for k, v in r.rates.items())))


def _tier_label(r) -> str:
    """'2024-27 Model Year' / '$832,750 or less' / '$10,000 – $24,999.99' - whatever names this row's tier."""
    if r.years:
        m = re.search(r"(?:Model Year\s*)?\d{4}\s*[-–]\s*\d{2,4}(?:\s*Model Year)?|\d{4} Model Year[^,]*", r.label)
        return m.group(0) if m else ""
    if r.tier:
        return r.tier
    m = re.search(r"\$[\d,]+(?:\.\d+)?\s*(?:or less|\+|\s*[-–]\s*\$?[\d,]+(?:\.\d+)?)", r.label)
    return m.group(0) if m else ""


def rate_conflicts(snaps) -> list[Found]:
    """One conflict per precise fact (user decision, 2026-10-19): product + term + tier, where tiers with
    overlapping model years are the same tier ('2023-26' and '2024-27' both cover a 2025 car)."""
    latest = snaps[-1]
    seen = defaultdict(list)                          # product + term -> [(snapshot, doc, row)]
    for s in snaps:
        for doc in s.pages.values():
            if doc.kind == "expired":
                continue
            for r in doc.rates:
                seen[(r.key, r.term_months)].append((s, doc, r))
    # the current table is chosen per PRODUCT, exactly as answers do: when the newest table dropped a
    # term, an older page still listing that term is outdated, not current
    win_all, lose_all = compete([(d, r) for d in latest.pages.values() if d.kind != "expired" for r in d.rates])
    win_table = {}
    for d, r in win_all:
        win_table.setdefault(r.key, (d, r))
    out = []
    for group, rows in seen.items():
        facts = {}                                    # distinct (tier, numbers) -> where and when it was printed
        for s, doc, r in rows:
            f = facts.setdefault(_fact(r), {"row": r, "pages": set(), "snaps": set(), "eff": r.effective})
            f["pages"].add(doc.url)
            f["snaps"].add(s.snapshot_id)
        items = list(facts.values())
        # tiers: connected groups of "same slot" facts (overlapping model years chain together)
        parent = list(range(len(items)))
        def root(i):
            while parent[i] != i:
                i = parent[i]
            return i
        for i, a in enumerate(items):
            for j in range(i + 1, len(items)):
                if _same_slot(a["row"], items[j]["row"]) and root(i) != root(j):
                    parent[root(j)] = root(i)
        tiers = defaultdict(list)
        for i, f in enumerate(items):
            tiers[root(i)].append(f)
        winners = [(d, r) for d, r in win_all if (r.key, r.term_months) == group]
        losers = [(d, r) for d, r in lose_all if (r.key, r.term_months) == group]
        for tier in tiers.values():
            if not any(_common_differs(a["row"].rates, b["row"].rates) for i, a in enumerate(tier) for b in tier[i + 1:]):
                continue                              # one tier, one set of numbers: no contradiction
            rows_here = {_fact(f["row"]) for f in tier}
            win = [(d, r) for d, r in winners if _fact(r) in rows_here]
            current = {_fact(r) for _, r in win}
            tier.sort(key=lambda f: (max(f["snaps"]), f["eff"] or date.min))
            values = []
            for f in tier:
                r = f["row"]
                where = ", ".join(sorted(u.replace("https://www.dupaco.com", "") or "/" for u in f["pages"])[:3])
                when = ", ".join(sorted(x[:2] for x in f["snaps"]))
                tag = "current" if _fact(r) in current else "outdated"
                values.append(f"{fmt_row(r)} [{tag}; {where}; effective {fmt_date(f['eff'])}; snapshots {when}]")
            label = _tier_label((win[0][1] if win else tier[-1]["row"]))
            topic = _topic(tier[-1]["row"]) + " rate" + (f" ({label})" if label else "")
            if win:
                win_doc, win_row = win[0]
                stale_now = sorted({d.url.replace("https://www.dupaco.com", "") for d, r in losers
                                    if _fact(r) in rows_here and _fact(r) not in current})
                resolution = "; ".join(fmt_row(r) for _, r in win[:3])
                reason = (f"Newest 'effective as of' date ({fmt_date(win_row.effective)}) on the most trusted page "
                          f"({win_doc.url.replace('https://www.dupaco.com', '') or '/'}) in the latest download")
                reason += (f"; still showing older numbers: {', '.join(stale_now[:4])}." if stale_now
                           else "; the other values are from earlier downloads (the rate changed over time).")
            elif group[0] in win_table:
                d, r = win_table[group[0]]
                resolution = None
                reason = (f"The current table for this product ({d.url.replace('https://www.dupaco.com', '') or '/'}, "
                          f"effective {fmt_date(r.effective)}) no longer lists this tier, so every value shown "
                          f"for it is outdated and the rate is unknown.")
            else:
                resolution, reason = None, "No longer listed in the latest download."
            sources = sorted({(u, max(f["snaps"])) for f in tier for u in f["pages"]})[:8]
            out.append(Found(topic=topic, values=values, sources=sources, resolution=resolution, reason=reason))
    return out


# ---------------------------------------------------------------- 2. text conflicts

def _numbers(sentence: str):
    """{what is counted: value} for each count / running count in a sentence:
    'It has over 600 employees and 22 branch office locations.' -> {'employe': '600', 'branch': '22'}."""
    out = {}
    for m in NUMBER.finditer(sentence):
        if m.group(4):
            out["time"] = (m.group(4).lower(), "times recognized")
        else:
            word = tokens(m.group(3))
            if word:
                what = re.split(r"\s+(?:and|with|in|to|of|throughout|who|that|across)\b", m.group(3).strip())[0]
                out.setdefault(word[0], (m.group(1).replace(",", ""), what))
    return out


def text_conflicts(view, min_pages: int = 3) -> list[Found]:
    """Boilerplate repeated on >= min_pages pages with different numbers, or a running count
    ('the fifth time ...') on >= 2 pages. One-off article facts (a survey size, an event date)
    describe different events, not a contradiction, and are left out."""
    sents = []
    for doc in view.pages.values():
        if doc.kind in ("expired", "listing") or not doc.published:
            continue
        for ch in doc.chunks:
            for s, terms in ch.sents:
                if YEAR.search(s) or not NUMBER.search(s):
                    continue                          # year-labelled statistics are history (user decision)
                sig = signature(frozenset(t for t in terms if not t[0].isdigit()))
                if len(sig) >= 4:
                    sents.append((doc, s, sig))
    index = defaultdict(list)                         # word -> sentences using it (only compare sentences that share words)
    for i, (_, _, sig) in enumerate(sents):
        for t in sig:
            index[t].append(i)
    parent = list(range(len(sents)))                  # connected components of "says the same thing"
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, (_, _, sig) in enumerate(sents):
        for j in {j for t in sig for j in index[t] if j > i}:
            if root(i) != root(j) and same_statement(sig, sents[j][2]):
                parent[root(j)] = root(i)
    groups = defaultdict(list)
    for i, x in enumerate(sents):
        groups[root(i)].append(x)

    found = []
    for g in groups.values():
        by_word = defaultdict(lambda: defaultdict(list))         # counted word -> value -> [(doc, sentence)]
        label = {}
        for d, s, _ in g:
            for word, (val, words) in _numbers(s).items():
                by_word[word][val].append((d, s))
                label.setdefault(word, words)
        changing = []                                            # the quantities that really changed
        for word, vals in by_word.items():
            pages = {d.key for where in vals.values() for d, _ in where}
            widest = max(len({d.key for d, _ in where}) for where in vals.values())
            if len(vals) < 2 or len(pages) < (2 if word == "time" else min_pages):
                continue
            if word != "time" and widest < min_pages:
                continue      # one page per value = a yearly article about that year, not a repeated claim
            changing.append(word)
        if not changing:
            continue
        # one conflict per repeated statement: its versions, newest first
        versions = defaultdict(list)
        for d, s, _ in g:
            nums = _numbers(s)
            versions[tuple(nums.get(w, ("?",))[0] for w in changing)].append((d, s))
        newest = lambda where: max(d.published for d, _ in where)
        ranked = sorted(versions.values(), key=newest, reverse=True)
        sample = max(ranked[0], key=lambda x: x[0].published)[1]
        values = [f"{max(where, key=lambda x: x[0].published)[1][:160]} [{len({d.key for d, _ in where})} page(s), "
                  f"newest {newest(where):%B} {newest(where).day}, {newest(where).year}]" for where in ranked]
        what = "Forbes recognition count" if changing == ["time"] else "number of " + " / ".join(label[w] for w in changing)
        found.append(Found(
            topic=f"{what}: {sample[:90]}",
            values=values,
            sources=sorted({(d.url, observed_in(view, d)) for where in ranked for d, _ in where})[:8],
            resolution=sample,
            reason="The same statement is repeated across press releases with different numbers; the most "
                   "recently published version is current, older releases describe the past.",
        ))
    return found


# ---------------------------------------------------------------- 3. page changes

MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?")
STATIC_KINDS = ("expired", "listing", "calculator", "news", "blog")   # calculators recompute their examples


def _dollar_sentences(doc) -> dict:
    """{sentence with its $ figures as '#': (figures, sentence)} for one page version. Skipped: tables,
    paragraphs that print a rate (payment examples follow the rate table), and a template used twice
    with different figures on one page (two cards' credit limits are two facts, not one that changed)."""
    out, clash = {}, set()
    for ch in doc.chunks:
        if any("%" in s for s, _ in ch.sents):
            continue
        for s, _ in ch.sents:
            vals = tuple(MONEY.findall(s))
            if not vals or "|" in s:
                continue
            tpl = MONEY.sub("#", s).strip()
            if len(tpl) < 25:
                continue
            if tpl in out and out[tpl][0] != vals:
                clash.add(tpl)
            out.setdefault(tpl, (vals, s))
    return {t: v for t, v in out.items() if t not in clash}


def page_changes(snaps) -> list[Found]:
    """A dollar figure an undated page changed between downloads ('grants up to $2,000' -> '$3,500').
    The newest download's version is current; the same change on several pages is one conflict."""
    latest = snaps[-1]
    seen = defaultdict(list)          # (page key, template) -> [(snapshot id, figures, sentence, doc)]
    for s in snaps:
        for key, doc in s.pages.items():
            if key in s.carried or doc.kind in STATIC_KINDS or doc.published:
                continue
            for tpl, (vals, sent) in _dollar_sentences(doc).items():
                seen[(key, tpl)].append((s.snapshot_id, vals, sent, doc))
    changes = defaultdict(list)       # (old figures, current figures) -> [(key, history)]
    for (key, tpl), hist in seen.items():
        if len({v for _, v, _, _ in hist}) < 2 or key not in latest.pages:
            continue
        now = latest.pages[key]
        if tpl not in _dollar_sentences(now):
            continue                  # reworded since: the current figure can't be read off this sentence
        current = hist[-1][1]
        old = tuple(sorted({v for _, v, _, _ in hist if v != current}))
        changes[(old, current)].append((key, hist))
    found = []
    for (old, current), where in sorted(changes.items()):
        versions = defaultdict(lambda: {"snaps": set(), "pages": set(), "sent": ""})
        for key, hist in where:
            for sid, vals, sent, doc in hist:
                v = versions[vals]
                v["snaps"].add(sid)
                v["pages"].add(doc.url)
                v["sent"] = sent
        order = sorted(versions, key=lambda v: max(versions[v]["snaps"]))
        values = []
        for v in order:
            x = versions[v]
            pages = ", ".join(sorted(u.replace("https://www.dupaco.com", "") or "/" for u in x["pages"])[:3])
            values.append(f"{x['sent'][:160]} [{'current' if v == current else 'outdated'}; {pages}; "
                          f"snapshots {', '.join(sorted(s[:2] for s in x['snaps']))}]")
        sample = versions[current]["sent"]
        title = latest.pages[where[0][0]].title.split("|")[0]
        title = re.sub(r"^\s*Microsoft Word\s*-\s*|\.docx?\s*$", "", title).strip()   # PDF titles from Word files
        found.append(Found(
            topic=f"{title}: {sample[:90]}",
            values=values,
            sources=sorted({(u, max(versions[v]["snaps"])) for v in order for u in versions[v]["pages"]})[:8],
            resolution=sample,
            reason=(f"The page itself changed this figure between downloads ({' / '.join(', '.join(v) for v in old)} "
                    f"-> {', '.join(current)}); the version in the newest download is current."),
        ))
    return found


PCT_VALUE = re.compile(r"(\d+(?:\.\d+)?)%")


def merge_twins(found: list[Found]) -> list[Found]:
    """The same change printed on twin products (personal / business / Roth / Traditional IRA versions of
    one certificate special) is one contradiction: keep the plainest topic, mention the twins."""
    by_numbers = {}
    for c in found:
        nums = frozenset(PCT_VALUE.findall(" ".join(v.split(" [")[0] for v in c.values)))
        if nums in by_numbers:
            keep = by_numbers[nums]
            twin_words = lambda f: len(re.findall(r"\b(business|roth|traditional|IRA)\b", f.topic))
            if (-twin_words(c), len(c.sources)) > (-twin_words(keep), len(keep.sources)):
                c, keep = keep, c             # keep the plain personal product, then the one shown on more pages
                by_numbers[nums] = keep
            keep.reason = (keep.reason or "") + f" Same change also shown for: {c.topic}."
            keep.sources = sorted(set(keep.sources) | set(c.sources))[:8]
        else:
            by_numbers[nums] = c
    return list(by_numbers.values())


def find_conflicts(snaps) -> list[Found]:
    """Most specific first (fewest competing values), so a broad conflict never stands in for a narrow one."""
    found = merge_twins(rate_conflicts(snaps)) + text_conflicts(snaps[-1]) + page_changes(snaps)
    return sorted(found, key=lambda c: (len(c.values), c.topic))
