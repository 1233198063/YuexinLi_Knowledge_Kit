"""
Step 2b - rate tables -> structured records (RateRow).

Every rate table on the site has the same shape:

    Special Certificates                                  <- caption: the title line above the table
    | Certificate | Dividend Rate | APY | Min. to Earn |
    | 17 Month Fixed Certificate Special | 4.06% | 4.10%2 | $1,000.00 |
    Rates are effective as of 09/01/2026 ...              <- effective date: the line below the table

Each data row becomes one RateRow that says
  * WHICH product      family ("certificate"), name ("special"), qualifiers ({"jumbo"}, {"business"} ...)
  * WHICH tier         term (17 months) / balance or loan amount ($10,000-$24,999.99) / model years (2024-2027)
  * the numbers        dividend rate, APY, rate, APR
  * the conditions     minimum to open / to earn ($1,000.00 for a certificate, $50,000 to open High-Yield Savings)
  * WHEN               the "Rates are effective as of" date printed under the table

Answering and conflict detection compare RateRows, never raw text, so "6-month vs 12-month"
or "$10k vs $25k tier" can never be mistaken for a contradiction.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

# ---------------------------------------------------------------- product identity

# Which product family a table belongs to. First match wins, so the order matters
# (an "IRA certificate" is an IRA; "Home Equity Refinance" rows are mortgages).
FAMILIES = [
    ("ira", r"\bira|\broth\b|traditional:"),
    ("hsa", r"health savings|\bhsa\b"),
    ("certificate", r"certificate"),
    ("money_market", r"money market"),
    ("checking", r"checking"),
    ("credit_card", r"\bvisa\b|credit card|balance transfer"),
    ("atv", r"\batv\b|snowmobile|jet ski"),
    ("boat_rv", r"\bboat|\brv\b|recreational"),
    ("auto", r"\bauto|motorcycle|vehicle"),
    ("heloc", r"heloc|line of credit"),
    ("home_equity_loan", r"home equity loan|loan . standard"),
    ("home_improvement", r"home improvement"),
    ("mortgage", r"mortgage|home loan|year fixed|purchase:|refinance:"),
    ("personal_loan", r"personal loan"),
    ("savings", r"savings"),
]

# Several products share a family; the name tells them apart ("" = the family's plain product,
# e.g. regular certificates or regular IRAs).
NAMES = {
    "savings": [("share savings", r"share savings"), ("bright savings", r"bright"),
                ("you name it savings", r"you.?name.?it"), ("holiday club", r"holiday"),
                ("launchpad savings", r"launchpad"), ("high-yield savings", r"high.?yield")],
    "money_market": [("investor's choice", r"investor"), ("achieve", r"achieve")],
    "checking": [("free checking", r"free checking"), ("1st rate checking", r"1st rate|first rate"),
                 ("analysis checking", r"analysis")],
    "credit_card": [("platinum visa", r"platinum"), ("rewards visa", r"rewards")],
    "certificate": [("special", r"special")],
    "ira": [("special", r"special"), ("variable", r"variable")],
}

# Qualifiers: same family and name, but a different product or a different price.
QUALIFIERS = [
    ("business", r"\bbusiness"),
    ("jumbo", r"jumbo"),
    ("refinance", r"refinanc|\brefi\b"),
    ("roth", r"\broth\b"),
    ("traditional", r"traditional"),
    ("intro", r"introductory|\bintro\b|balance transfer"),
]


def classify_family(*texts: str) -> str:
    """Try each text in turn (row label first, then wider context) until one names a family."""
    for t in texts:
        t = (t or "").lower()
        for fam, rx in FAMILIES:
            if re.search(rx, t):
                return fam
    return ""


def product_name(family: str, text: str) -> str:
    t = text.lower()
    for name, rx in NAMES.get(family, []):
        if re.search(rx, t):
            return name
    return ""


def qualifiers(text: str) -> frozenset:
    t = text.lower()
    return frozenset(q for q, rx in QUALIFIERS if re.search(rx, t))


# ---------------------------------------------------------------- the record

@dataclass
class RateRow:
    family: str                 # "certificate", "mortgage", "savings", ...
    name: str                   # product within the family ("special", "share savings", "" = plain)
    quals: frozenset            # {"jumbo"}, {"business"}, {"refinance"}, {"roth"} ...
    label: str                  # first cell as printed: "17 Month Fixed Certificate Special"
    display: str                # human name for answers: "Regular Certificates – 60 Month"
    caption: str                # title line above the table
    term_months: Optional[int]  # 17, 60, 360 (30-year) ...
    tier: str                   # printed balance / loan-amount tier: "$10,000 – $24,999.99"
    tier_lo: Optional[float]
    tier_hi: Optional[float]
    years: Optional[tuple]      # model years (lo, hi) for vehicle loans
    rates: dict                 # "dividend" / "apy" / "rate" / "apr" / "promo_*" -> "4.10%" or "12.50% – 19.50%"
    effective: Optional[date]   # "Rates are effective as of ..." under the table (None = not printed)
    table: int                  # which rate table on the page (0, 1, 2 ...)
    raw: str                    # the markdown row, for quoting
    minimums: dict = field(default_factory=dict)   # "min_open" / "min_earn" / "min_balance" -> "$1,000.00"

    @property
    def min_amount(self) -> Optional[float]:
        """The balance needed before this rate applies: the larger of 'to open' and 'to earn'."""
        vals = [_num(m.group(1)) for v in self.minimums.values() for m in [re.search(AMOUNT, v)] if m]
        return max(vals) if vals else None

    @property
    def key(self):
        """Product identity: rows with the same key on different pages describe the same product."""
        return (self.family, self.name, self.quals)

    @property
    def slot(self):
        """Tier identity inside a product: same key + same slot = the same fact."""
        return (self.term_months, self.tier_lo, self.tier_hi, self.years)


# ---------------------------------------------------------------- parsing helpers

PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
BARE_RATE = re.compile(r"^\d{1,2}\.\d{1,3}$")          # older tables sometimes print "7.29" without the % sign
TERM = re.compile(r"\b(\d{1,3})\s*-?\s*(months?|mo\b|years?|yrs?\b)", re.I)
AMOUNT = r"\$\s?(\d[\d,]*(?:\.\d+)?)"
EFFECTIVE = re.compile(r"effective(?:\s+as\s+of)?\s+(\d{1,2})/(\d{1,2})/(\d{2,4})", re.I)
FOOTNOTE = re.compile(r"^\W*\d(?!st\b|nd\b|rd\b|th\b)[A-Za-z]")   # "1Rates are effective..." = footnote 1 ("1st Rate" is not)
SEPARATOR = re.compile(r"^\|\s*:?-{3}")
RATE_COLUMN = re.compile(r"rate|apy|apr|yield|dividend", re.I)
HEADING = re.compile(r"^#{1,6}\s+")
TAB_LINK = re.compile(r"^-\s*\[([^\]]*Rates)\]\(")      # older layout: "- [Money Market Account Rates](...#)"
RATE_KINDS = ("rate", "dividend", "apy", "apr", "promo_dividend", "promo_apy")
MIN_KINDS = ("min_open", "min_earn", "min_balance")


def split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def clean_cell(c: str) -> str:
    c = re.sub(r"<br\s*/?>", " ", c).replace("\\*", "*").replace("**", "")
    return re.sub(r"\s+", " ", c).strip()


def column_kind(header: str) -> str:
    h = header.lower()
    promo = "1st 6 months" in h or "introductory" in h
    if "payment" in h:
        return "payment"
    if "point" in h:
        return "points"
    if "min" in h and "open" in h:
        return "min_open"
    if "min" in h and "earn" in h:
        return "min_earn"
    if "min" in h and "balance" in h:
        return "min_balance"
    if "max" in h:
        return "max_balance"
    if "yield" in h or "apy" in h:
        return "promo_apy" if promo else "apy"
    if "dividend" in h:
        return "promo_dividend" if promo else "dividend"
    if "annual percentage rate" in h or re.search(r"\bapr\b", h):
        return "apr"
    if re.match(r"^\W*rate\b", h):
        return "rate"
    if "term" in h:
        return "term"
    if "balance" in h or "amount" in h or "tier" in h:
        return "tier"
    return "other"


def term_months(text: str) -> Optional[int]:
    m = TERM.search(text or "")
    if not m:
        return None
    n = int(m.group(1))
    return n * 12 if m.group(2).lower().startswith("y") else n


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_tier(text: str):
    """'$25,000+' / '$10,000 – $24,999.99' / '$832,750 or less' / '$10,000-24,999' -> (lo, hi)."""
    t = (text or "").replace("–", "-").replace("—", "-")
    m = re.search(AMOUNT + r"\s*(?:-|to)\s*\$?\s?(\d[\d,]*(?:\.\d+)?)", t)
    if m:
        return _num(m.group(1)), _num(m.group(2))
    m = re.search(AMOUNT + r"\s*\+", t)
    if m:
        return _num(m.group(1)), float("inf")
    m = re.search(AMOUNT + r"\s*(?:or less|and under|or below)", t)
    if m:
        return 0.0, _num(m.group(1))
    m = re.search(r"(?:up to|under)\s*" + AMOUNT, t)
    if m:
        return 0.0, _num(m.group(1))
    return None, None


def parse_model_years(text: str) -> Optional[tuple]:
    """'2024-27 Model Year' -> (2024, 2027); 'Model Year 2026-23' -> (2023, 2026);
       '2016 Model Year (and older)' -> (1900, 2016)."""
    t = (text or "").replace("–", "-")
    if "model year" not in t.lower():
        return None
    m = re.search(r"(\d{4})\s*-\s*(\d{2,4})", t)
    if m:
        a, b = int(m.group(1)), m.group(2)
        b = int(b) if len(b) == 4 else a // 100 * 100 + int(b)
        return (min(a, b), max(a, b))
    m = re.search(r"(\d{4})", t)
    if m:
        y = int(m.group(1))
        return (1900, y) if "older" in t.lower() else (y, y)
    return None


def format_pcts(cell: str) -> str:
    """'4.10%2' -> '4.10%' (drops the footnote marker); '12.50% – 19.50%2' -> '12.50% – 19.50%'.
    Only two values joined by a dash / 'to' are a range: '2.90% APR for 6 mos. (after that ... 12.50%)' -> '2.90%'."""
    first = PCT.search(cell)
    m = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:-|–|—|to)\s*(\d+(?:\.\d+)?)\s*%").match(cell, first.start())
    if m:
        return f"{m.group(1)}% – {m.group(2)}%"
    return first.group(1) + "%"


def parse_date(m) -> Optional[date]:
    mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y = y + 2000 if y < 100 else y
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def is_title(line: str, from_heading: bool) -> bool:
    if not (2 <= len(line) <= 90) or not re.search(r"[A-Za-z]", line):
        return False
    if line[0] in "[-*!\\>|" or "](" in line or "$" in line or "effective" in line.lower() or FOOTNOTE.match(line):
        return False
    return from_heading or not line.endswith((".", ":", "?", "!", ","))


# ---------------------------------------------------------------- tables on a page

def find_tables(lines: list[str]) -> list[tuple[int, int]]:
    """(header line, end line exclusive) for every markdown table."""
    out, i = [], 0
    while i < len(lines) - 1:
        if lines[i].startswith("|") and SEPARATOR.match(lines[i + 1]):
            j = i + 2
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def is_rate_table(lines: list[str], start: int, end: int) -> bool:
    if not RATE_COLUMN.search(lines[start]):
        return False
    return any(PCT.search(l) or any(BARE_RATE.match(c) for c in split_row(l)) for l in lines[start + 2:end])


def titles_above(lines: list[str], start: int, rate_lines: set) -> list[str]:
    """Up to two title lines above a table: [caption, section]. Stops at the previous rate table."""
    out, i, steps = [], start - 1, 0
    while i >= 0 and len(out) < 2 and steps < 30:
        raw = lines[i].strip()
        idx, i, steps = i, i - 1, steps + 1
        if not raw:
            continue
        if raw.startswith("|"):
            if idx in rate_lines:
                break
            continue                       # a layout table (feature bullets etc.): look past it
        tab = TAB_LINK.match(raw)
        if tab:
            out.append(tab.group(1))
            continue
        heading = bool(HEADING.match(raw))
        t = HEADING.sub("", raw).strip().strip("*_").strip()
        if is_title(t, heading):
            out.append(t)
        if heading:
            break                          # a markdown heading closes the block
    return out


def effective_below(lines: list[str], end: int, stop: int) -> Optional[date]:
    """The table's own "Rates are effective as of" line; a footnote date only if there is no other."""
    footnote_date, seen = None, 0
    for line in lines[end:stop]:
        if not line.strip():
            continue
        seen += 1
        if seen > 15:
            break
        m = EFFECTIVE.search(line)
        if m:
            d = parse_date(m)
            if FOOTNOTE.match(line.strip()):
                footnote_date = footnote_date or d
            elif d:
                return d
    return footnote_date


def display_name(caption: str, label: str, term_cell: str, tier_cell: str, quals) -> str:
    name = label if classify_family(label) else (f"{caption} – {label}" if caption else label)
    extra = ", ".join(x for x in (term_cell, tier_cell) if x)
    name = f"{name}, {extra}" if extra else name
    if "business" in quals and "business" not in name.lower():
        name = "Business " + name
    return name


# A rate written as one "label metric: value" line instead of a table ("6-month certificate APY: 3.50%").
# Strict on purpose: the whole line must be that, so marketing sentences with a % never become rate records.
PROSE_RATE = re.compile(r"^\W*(?P<label>[A-Za-z0-9][A-Za-z0-9 ,.'’()/&-]{2,60}?)\s+(?P<metric>APY|APR|dividend rate|"
                        r"interest rate|rate)\s*:?\s*(?P<pct>\d+(?:\.\d+)?)\s*%\s*(?P<rest>\(.*\))?\s*$", re.I)
ENDED = re.compile(r"\b(ended|expired|no longer available|discontinued)\b", re.I)
PROSE_METRIC = {"apy": "apy", "apr": "apr", "dividend rate": "dividend", "interest rate": "rate", "rate": "rate"}


def parse_prose_rates(lines: list[str], table_index: int, url_path: str) -> list[RateRow]:
    rows = []
    for line in lines:
        if line.startswith("|") or len(line) > 120:
            continue
        m = PROSE_RATE.match(line.strip())
        if not m or ENDED.search(m.group("rest") or ""):
            continue                  # "(offer ended 2025-09-30)": an expired promotion is not a current rate
        label = m.group("label").strip(" :")
        family = classify_family(label, url_path.replace("-", " "))
        if not family:
            continue
        rows.append(RateRow(
            family=family, name=product_name(family, label), quals=qualifiers(f"{label} {url_path}"), label=label,
            display=label, caption="", term_months=term_months(label), tier="", tier_lo=None, tier_hi=None,
            years=parse_model_years(label), rates={PROSE_METRIC[m.group("metric").lower()]: m.group("pct") + "%"},
            effective=None, table=table_index, raw=line.strip(),
        ))
    return rows


def parse_rate_tables(text: str, url_path: str = "") -> list[RateRow]:
    lines = text.split("\n")
    tables = [t for t in find_tables(lines) if is_rate_table(lines, *t)]
    rate_lines = {i for s, e in tables for i in range(s, e)}
    heading_at, cur = [], ""
    for line in lines:
        if HEADING.match(line):
            cur = HEADING.sub("", line).strip()
        heading_at.append(cur)

    rows, section = [], ""
    for ti, (start, end) in enumerate(tables):
        header = [clean_cell(h) for h in split_row(lines[start])]
        kinds = [column_kind(h) for h in header]
        titles = titles_above(lines, start, rate_lines)
        caption = titles[0] if titles else ""
        section = titles[1] if len(titles) > 1 else section   # no new section title: still in the previous one
        stop = tables[ti + 1][0] if ti + 1 < len(tables) else len(lines)
        eff = effective_below(lines, end, stop)
        for line in lines[start + 2:end]:
            cells = [clean_cell(c) for c in split_row(line)]
            if len(cells) < 2 or not cells[0]:
                continue
            label = cells[0]
            rates, term_cell, tier_cell, minimums = {}, "", "", {}
            for kind, cell in zip(kinds[1:], cells[1:]):
                if not cell or cell in ("—", "-", "None", "N/A"):
                    continue
                if PCT.search(cell) and kind not in ("points", "payment"):
                    # the cell's own unit beats the header (a calculator labels APRs as "Annual Percentage Yield")
                    k = "apr" if re.search(r"\bAPR\b", cell) else "apy" if re.search(r"\bAPY\b", cell) else kind
                    rates[k if k in RATE_KINDS else "rate"] = format_pcts(cell)
                elif BARE_RATE.match(cell) and kind in RATE_KINDS:
                    rates[kind] = cell + "%"
                elif TERM.search(cell) and kind in ("term", "tier", "other"):
                    term_cell = cell
                elif "$" in cell and kind == "tier":
                    tier_cell = cell
                elif "$" in cell and kind in MIN_KINDS:
                    minimums[kind] = cell
            if not rates:
                continue
            # the header's first cell sometimes names the product ("| Business Platinum Visa | APR |")
            context = f"{caption} {header[0]} {label}"
            family = classify_family(label, context, section, heading_at[start], url_path.replace("-", " "))
            quals = qualifiers(f"{context} {section} {url_path}")
            lo, hi = parse_tier(tier_cell or (label if "$" in label else ""))
            rows.append(RateRow(
                # the table's own caption/label name it first; the section line only if they don't
                family=family, name=product_name(family, context) or product_name(family, section), quals=quals, label=label,
                display=display_name(caption, label, term_cell, tier_cell, quals),
                caption=caption, term_months=term_months(term_cell) or term_months(label),
                tier=tier_cell, tier_lo=lo, tier_hi=hi, years=parse_model_years(label),
                rates=rates, effective=eff, table=ti, raw=line.strip(), minimums=minimums,
            ))
    # the page's prose rate lines count as one more table (they compete together as one product table)
    return rows + parse_prose_rates([l for i, l in enumerate(lines) if i not in rate_lines], len(tables), url_path)
