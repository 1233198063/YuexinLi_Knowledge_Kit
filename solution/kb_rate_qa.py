"""
Step 2c - answer rate questions from RateRows instead of from raw text.

    question ----parse----> family, product name, qualifiers, term, amount, model year
    RateRows of the view --compete--> one winning table per product       (the "what is current" rules)
    winning rows ---filter--> only the tiers the question asked for
    -> answer text + sources (+ a note naming the out-of-date values other pages still show)

Which table wins when several pages show the same product (see NOTES.md):
    1. expired pages never compete
    2. the newest "Rates are effective as of" date wins (a table with no date counts as oldest)
    3. same date -> the more trusted page wins (AUTHORITY in kb_pages: rate sheet > product page > ...)

Products compete as a whole table, not row by row: if the newest table no longer lists a tier
(e.g. "2023-26 Model Year"), an older page that still lists it does not get to answer.

A loan kind the tables don't have ("construction loan", "VA mortgage") is not answered with the plain
mortgage rows: the question goes to text search, which answers only from text about that kind.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Optional

from kb_pages import observed_in

# ---------------------------------------------------------------- reading the question

RATE_INTENT = re.compile(r"\b(rates?|apys?|aprs?|yields?|dividends?|interest|percent(age)?)\b|%", re.I)
EARN_INTENT = re.compile(r"\b(earn|earns|pay|pays|paying)\b", re.I)   # "what does a 12-month certificate pay?"
CHARGE_INTENT = re.compile(r"\b(charge|charges|charging)\b", re.I)    # "what are you charging for home loans?"
# "did the 17-month special go up?" asks about its rate too
MOVE_INTENT = re.compile(r"\b(go(ne)? up|went up|go(ne)? down|went down|chang\w*|increas\w*|decreas\w*|rais\w*|drop\w*)\b", re.I)
# a product NAME that contains "rate" isn't a rate question ("how do I avoid the fee on 1st Rate Checking?")
RATE_IN_NAME = re.compile(r"\b(1st|first) rate\b", re.I)
# "the purchase APR, not the intro rate", "the non-jumbo special": a qualifier named only to rule it out doesn't count
NEGATED = re.compile(r"\b(?:not|excluding|other than|besides|rather than|instead of|except)\b[^,.;?]*"
                     r"|\bnon-?\s?(?:jumbo|business|refinanc\w*|intro\w*|promo\w*)", re.I)
# what the question asks about the product is not its rate: a requirement, a limit, a term, a cost, a how-to.
# Those answers are in the text around the tables ("Rates based on a minimum 760 credit score and 75% LTV").
CONDITION = re.compile(r"\b(credit score|ltv|loan.to.value|qualif\w*|requirement\w*|eligib\w*|closing costs?|"
                       r"terms? (are )?(available|offered)|repayment|floor|cap(ped)?|maximum apr|highest apr|"
                       r"lowest (it|the rate) can|never (be )?(less|lower|more|higher)|expire\w*|how do i|what do i (have|need)|"
                       r"have to do|need to do|minimum credit limit|credit limit|payment on|monthly payment|paid out|"
                       r"how much (of|can i borrow)|borrow up to|down payment|convert\w*|catch|recoup|"
                       r"redemption\w*|redeem\w*|cash.?back|points?|fees?)\b", re.I)
DEPOSITS = {"savings", "money_market", "checking", "certificate", "ira", "hsa"}

# Members' words for each family (kb_rates.FAMILIES uses the site's words). First match wins.
Q_FAMILIES = [
    ("ira", r"\biras?\b|\broth\b|traditional ira|retirement"),
    ("hsa", r"\bhsa\b|health savings"),
    ("certificate", r"certificate|\bcds?\b|term.share|\bjumbo special|\b\d+.month (?:fixed )?(?:jumbo )?special"),
    ("money_market", r"money market"),
    ("checking", r"checking"),
    ("credit_card", r"credit cards?|\bvisa\b|\bcards?\b"),
    ("atv", r"\batvs?\b|snowmobile|jet.?ski"),
    ("boat_rv", r"\bboats?\b|\brvs?\b|camper|recreational"),
    ("auto", r"\bauto|\bcars?\b|vehicle|truck|motorcycle|model.year"),
    ("heloc", r"heloc|line of credit"),
    ("home_equity_loan", r"home equity"),
    ("home_improvement", r"home improvement|renovat"),
    ("mortgage", r"mortgage|home loan|\bhouse\b|\d+.?(?:year|yr) fixed|conventional|refinanc|\brefi\b|\barms?\b|adjustable"),
    ("personal_loan", r"personal loan"),
    ("savings", r"savings|\bhys\b"),
]
Q_NAMES = {
    "savings": [("share savings", r"share savings|share account|regular savings|basic savings"),
                ("bright savings", r"bright"), ("you name it savings", r"you.?name.?it"),
                ("holiday club", r"holiday|christmas club"), ("launchpad savings", r"launchpad"),
                ("high-yield savings", r"high.?yield|\bhys\b")],
    "money_market": [("investor's choice", r"investor"), ("achieve", r"achieve")],
    "checking": [("free checking", r"free checking"), ("1st rate checking", r"1st rate|first rate"),
                 ("analysis checking", r"analysis")],
    "credit_card": [("platinum visa", r"platinum"), ("rewards visa", r"rewards")],
    "certificate": [("special", r"special|promo"), ("", r"\bregular\b")],
    "ira": [("special", r"special|promo"), ("variable", r"variable"), ("", r"\bregular\b")],
}
Q_QUALS = [
    ("business", r"\bbusiness"),
    ("jumbo", r"jumbo"),
    ("refinance", r"refinanc|\brefi\b"),
    ("roth", r"\broth\b"),
    ("traditional", r"traditional"),
    ("intro", r"introductory|\bintro\b|balance transfer|promotional"),
    ("arm", r"adjustable|\barms?\b|\b\d/\d\b"),          # no row ever has this -> "not listed"
]
EXCLUSIVE = {"refinance", "business"}   # a different product: never shown unless asked (business: lists only)
SECONDARY = {"jumbo", "intro"}          # same product, special price: shown after the main rows

# Which number the question names: "4.06% APY?" is checked against APYs only (4.06% is the dividend rate).
Q_METRICS = [("apy", r"\bapys?\b|annual percentage yield|\byields?\b"),
             ("apr", r"\baprs?\b|annual percentage rate"),
             ("dividend", r"\bdividend")]
METRIC_KEYS = {"apy": ("apy", "promo_apy"), "apr": ("apr",), "dividend": ("dividend", "promo_dividend")}

# The kind of loan a question names: "construction loan", "VA mortgage", "land mortgage". A kind that no
# vocabulary word above explains must be printed in the family's rate rows, or the rows don't answer it.
LOAN_KIND = re.compile(r"\b([a-z][a-z/'-]*)\s+(?:home\s+|credit\s+|savings\s+|checking\s+|money market\s+)?"
                       r"(loans?|mortgages?|propert(?:y|ies)|cards?|accounts?)\b")
PLAIN_WORDS = frozenset("""a an the my your our any this that which what current new used today's best lowest
    highest top cheapest good standard regular fixed fixed-rate rate interest year yr month term conventional
    purchase home house mortgage loan first primary dupaco dupaco's credit debit savings checking money market
    cash back personal individual normal basic online joint plain have has had offer offers get got all other
    some both these those more any do does you i we""".split())

WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
           "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30}
Q_TERM = re.compile(r"\b(\d{1,3}|" + "|".join(WORDNUM) + r")\s*-?\s*(months?|mos?\b|years?|yrs?\b)", re.I)
Q_AMOUNT = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(k|m|million|thousand)?\b|\b(\d+(?:\.\d+)?)\s*(k|thousand|million)\b", re.I)
Q_YEAR = re.compile(r"\b(19[89]\d|20[0-3]\d)\b")
Q_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
MAX_WORDS = re.compile(r"\b(highest|maximum|max|most|top)\b", re.I)
MIN_WORDS = re.compile(r"\b(lowest|cheapest|minimum|least)\b", re.I)
BEST = re.compile(r"\bbest\b", re.I)


@dataclass
class RateQuery:
    family: str
    names: set
    quals: set
    term: Optional[int]
    amounts: list
    year: Optional[int]
    extreme: Optional[str]          # "max" / "min" / None
    check_pct: Optional[float]      # "Do any tiers pay 0.35%?" -> 0.35
    metrics: Optional[tuple] = None # rate keys the question names ("APY" -> apy, promo_apy); None = any
    kinds: list = field(default_factory=list)   # loan kinds no vocabulary explains: ["construction loan"]
    terms: list = field(default_factory=list)   # every term named: "6-month or 24-month?" -> [6, 24]

    @property
    def generic(self) -> bool:
        """'What are your certificate rates?' - no product, tier or term named: list everything."""
        return not self.names and not self.terms and not self.amounts and self.year is None


def _amount(num: str, unit: Optional[str]) -> float:
    v = float(num.replace(",", ""))
    u = (unit or "").lower()
    return v * 1_000 if u in ("k", "thousand") else v * 1_000_000 if u in ("m", "million") else v


# A product the question names in capitals ("Mortgage Rate Relief Program"): its distinctive words must be
# printed in the family's rate rows, or the plain rows would answer for a product they don't describe.
NAME_RUN = re.compile(r"[A-Z][\w'’$-]*(?:\s+[A-Z][\w'’$-]*)+")
GENERIC_NAME_WORDS = frozenset("""mortgage mortgages rate rates loan loans account accounts savings saving checking
    certificate certificates card cards credit visa program plan special fixed home auto personal business money
    market club share the and for dupaco dupacos what how is are can do does did which when where who why will
    would tell give please your our january february march april may june july august september october november
    december""".split())


def unknown_names(question: str) -> list:
    """'What is the Mortgage Rate Relief Program rate?' -> ['relief']; 'Bright Savings APY?' -> ['bright']."""
    out = []
    for m in NAME_RUN.finditer(question):
        words = m.group(0).split()
        if not question[:m.start()].strip() or re.search(r"[.?!:]\s*$", question[:m.start()]):
            words = words[1:]     # a sentence's first word is capitalised anyway ("Highest APY ...?")
        for w in words:
            if w.rstrip("s").isupper() or len(w) < 3:
                continue          # APY, APRs, IRA ...
            w = re.sub(r"['’]", "", re.sub(r"['’]s$", "", w.lower()))     # "Checking's" -> "checking"
            if w not in GENERIC_NAME_WORDS:
                out.append(w)
    return out


def unknown_kinds(ql: str, family: str) -> list:
    """'what mortgage rate can I get for a construction loan?' -> ['construction loan'];
    'home equity loan', 'jet ski loan', '30-year fixed mortgage' -> [] (vocabulary or plain words)."""
    vocab = [rx for _, rx in Q_FAMILIES + Q_NAMES.get(family, []) + Q_QUALS]
    spans = [m.span() for rx in vocab for m in re.finditer(rx, ql)]
    out = []
    for m in LOAN_KIND.finditer(ql):
        a, b = m.span(1)
        if m.group(1) in PLAIN_WORDS or Q_TERM.fullmatch(m.group(1)) or any(s < b and a < e for s, e in spans):
            continue          # "thirty-year home loan": a term, not a kind of loan
        out.append(f"{m.group(1)} {m.group(2)}")
    return out


def parse_question(question: str) -> Optional[RateQuery]:
    ql = question.lower()
    if CONDITION.search(ql):
        return None       # "what credit score do I need for the 6.25% HELOC rate?": the answer is in the text
    family = next((f for f, rx in Q_FAMILIES if re.search(rx, ql)), "")
    if not family:        # a product name implies its family: "What does a Holiday Club account earn?"
        family = next((f for f, names in Q_NAMES.items() if f not in ("certificate", "ira")
                       for _, rx in names if re.search(rx, ql)), "")
    if not family:
        return None
    intent = RATE_IN_NAME.sub(" ", ql)
    if not (RATE_INTENT.search(intent) or (family in DEPOSITS and EARN_INTENT.search(ql))
            or (family not in DEPOSITS and CHARGE_INTENT.search(ql)) or MOVE_INTENT.search(ql)):
        return None
    names = {n for n, rx in Q_NAMES.get(family, []) if re.search(rx, ql)}
    quals = {q for q, rx in Q_QUALS if re.search(rx, NEGATED.sub(" ", ql))}
    terms = []
    for m in Q_TERM.finditer(ql):
        n = int(m.group(1)) if m.group(1).isdigit() else WORDNUM[m.group(1)]
        terms.append(n * 12 if m.group(2).startswith("y") else n)
    term = terms[0] if terms else None
    amounts = []
    for m in Q_AMOUNT.finditer(ql):
        a = _amount(m.group(1), m.group(2)) if m.group(1) else _amount(m.group(3), m.group(4))
        if re.search(r"\b(more than|over|above|greater than|exceeding|bigger than)\s*$", ql[:m.start()]):
            a += 0.01     # "borrowing more than $300,000" is not in the "$300,000 or less" tier
        amounts.append(a)
    year = None
    if family in ("auto", "atv"):         # the model year, not the year of a date ("in late August 2026 ... a 2017 car")
        undated = re.sub(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?:\d{1,2}(?:st|nd|rd|th)?,?\s+)?"
                         r"20\d\d\b|\b20\d\d-\d\d(?:-\d\d)?\b|\b\d{1,2}/\d{1,2}/20\d\d\b", " ", ql)
        m = Q_YEAR.search(undated)
        year = int(m.group(1)) if m else None
    extreme = "max" if MAX_WORDS.search(ql) else "min" if MIN_WORDS.search(ql) else None
    if extreme is None and BEST.search(ql):
        extreme = "max" if family in DEPOSITS else "min"      # best savings rate = highest, best loan rate = lowest
    m = Q_PCT.search(ql)
    named = [k for metric, rx in Q_METRICS if re.search(rx, ql) for k in METRIC_KEYS[metric]]
    return RateQuery(family, names, quals, term, amounts, year, extreme, float(m.group(1)) if m else None,
                     tuple(named) or None, unknown_kinds(ql, family), terms)


# ---------------------------------------------------------------- choosing the current table

def table_rank(doc, row):
    """Rule 2 then rule 3, then a fixed tie-break so the same question always gets the same answer."""
    return (row.effective or date.min, doc.authority, -len(doc.key), doc.key, -row.table)


def _values(v: str) -> tuple:
    return tuple(float(x) for x in re.findall(r"\d+(?:\.\d+)?", v))


def fill_metrics(winners, losers):
    """The winning table may leave out a column another current page prints for the same product and tier
    (Achieve Money Market: the dated table has no "1st 6 months" promo columns, /earn-more has them). When every
    number the two rows share is equal, the other row's extra columns are added: same fact, more detail."""
    others = defaultdict(list)
    for _, r in losers:
        others[(r.key, r.slot)].append(r)
    out = []
    for d, r in winners:
        add = {}
        for o in others.get((r.key, r.slot), []):
            common = set(o.rates) & set(r.rates)
            if common and all(_values(o.rates[k]) == _values(r.rates[k]) for k in common):
                add.update({k: v for k, v in o.rates.items() if k not in r.rates and k not in add})
        out.append((d, replace(r, rates={**r.rates, **add}) if add else r))
    return out


def compete(pairs):
    """pairs: [(doc, row)] -> (winning pairs, losing pairs). One winning table per product key."""
    tables = defaultdict(lambda: defaultdict(list))
    for doc, row in pairs:
        tables[row.key][(doc.key, row.table)].append((doc, row))
    winners, losers = [], []
    for by_table in tables.values():
        best = max(by_table, key=lambda t: table_rank(*by_table[t][0]))
        for t, members in by_table.items():
            (winners if t == best else losers).extend(members)
    return winners, losers


# ---------------------------------------------------------------- filtering to what was asked

def _first_number(s: str) -> float:
    m = re.search(r"\d+(?:\.\d+)?", s or "")
    return float(m.group(0)) if m else 0.0


def headline(row, family: str) -> float:
    order = ("apy", "dividend", "rate", "apr") if family in DEPOSITS else ("apr", "rate", "apy", "dividend")
    return next((_first_number(row.rates[k]) for k in order if k in row.rates), 0.0)


def select(pairs, q: RateQuery):
    """-> (main rows, secondary rows) that answer the question."""
    # an "intro" question is also answered by rows that print a promotional rate ("for the 1st 6 months")
    promo = lambda r: "intro" in r.quals or any(k.startswith("promo_") for k in r.rates)
    pairs = [p for p in pairs if q.quals - {"arm", "intro"} <= p[1].quals and "arm" not in q.quals
             and ("intro" not in q.quals or promo(p[1]))]
    if q.names:
        pairs = [p for p in pairs if p[1].name in q.names]
    tagged = []
    for doc, r in pairs:
        unasked = r.quals - q.quals
        if "refinance" in unasked or ("business" in unasked and not q.generic):
            continue
        tagged.append((doc, r, bool(unasked & (SECONDARY | {"business"}))))

    rows = [t[1] for t in tagged]
    if q.terms and any(r.term_months is not None for r in rows):
        tagged = [t for t in tagged if t[1].term_months in q.terms]     # "6-month or 24-month": both
    if q.year is not None and any(r.years for r in rows):
        tagged = [t for t in tagged if t[1].years and t[1].years[0] <= q.year <= t[1].years[1]]
    if q.amounts and any(t[1].tier_lo is not None for t in tagged):
        inside = lambda r, a: r.tier_lo is not None and r.tier_lo <= a <= r.tier_hi
        fits = [t for t in tagged if all(inside(t[1], a) for a in q.amounts)] or \
               [t for t in tagged if inside(t[1], q.amounts[0])]
        narrowest = {}
        for t in fits:                        # "$250,000" fits "$300,000 or less" AND "$832,750 or less": keep the tighter
            k = (t[1].key, t[1].term_months, t[1].years)
            if k not in narrowest or t[1].tier_hi - t[1].tier_lo < narrowest[k]:
                narrowest[k] = t[1].tier_hi - t[1].tier_lo
        tagged = [t for t in fits if t[1].tier_hi - t[1].tier_lo == narrowest[(t[1].key, t[1].term_months, t[1].years)]]
    if q.amounts:
        # a balance below the minimum to open / to earn doesn't get that rate; if nothing qualifies, the rows
        # stay and the answer says the amount is too small (user decision, 2026-10-21)
        amount = max(q.amounts)
        tagged = [t for t in tagged if t[1].min_amount is None or t[1].min_amount <= amount] or tagged

    main = [(d, r) for d, r, sec in tagged if not sec]
    extra = [(d, r) for d, r, sec in tagged if sec]
    if q.extreme and main:
        vals = [headline(r, q.family) for _, r in main]
        pick = max(vals) if q.extreme == "max" else min(vals)
        main = [p for p, v in zip(main, vals) if v == pick]
        extra = []
    return main, extra


# ---------------------------------------------------------------- writing the answer

METRICS = [("rate", "rate"), ("dividend", "dividend rate"), ("apy", "APY"), ("apr", "APR"),
           ("promo_dividend", "dividend rate for the first 6 months"), ("promo_apy", "APY for the first 6 months")]
LABEL = dict(METRICS)
MIN_LABEL = {"min_open": "minimum to open", "min_earn": "minimum to earn", "min_balance": "minimum balance"}


def fmt_minimum(r) -> str:
    """'minimum to earn $1,000.00': the larger of the row's minimums."""
    kind = max(r.minimums, key=lambda k: _first_number(r.minimums[k].replace(",", "")))
    return f"{MIN_LABEL[kind]} {r.minimums[kind]}"


def fmt_row(r, title: str = "") -> str:
    vals = [f"{r.rates[k]} {label}" for k, label in METRICS if k in r.rates]
    name = r.display[len(title) + 3:] if title and r.display.startswith(f"{title} – ") else r.display
    # a balance tier already says how much is needed; otherwise the minimum is part of the fact ($100,000 jumbo)
    cond = f" ({fmt_minimum(r)})" if r.tier_lo is None and r.min_amount else ""
    return f"{name}: {' / '.join(vals)}{cond}"


def fmt_money(a: float) -> str:
    return f"${a:,.0f}" if float(a).is_integer() else f"${a:,.2f}"


def _span(value: str):
    """'4.10%' -> (4.10, 4.10); '12.50% – 19.50%' -> (12.50, 19.50)."""
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", value)]
    return (min(nums), max(nums)) if nums else None


def _holds(value: str, pct: float) -> bool:
    s = _span(value)
    return bool(s) and s[0] - 1e-9 <= pct <= s[1] + 1e-9


def check_line(rows, q: RateQuery) -> str:
    """'Do any 17-month specials pay 4.06% APY?' -> 'No: 4.06% is the dividend rate ...; its APY is 4.10%.'
    Only the number the question names counts (APY, APR, dividend rate); a range counts if it contains it."""
    pct = q.check_pct
    for r in rows:
        for k, v in r.rates.items():
            if (q.metrics is None or k in q.metrics) and _holds(v, pct):
                within = f", which includes {pct:g}%" if _span(v)[0] != _span(v)[1] else ""
                return f"Yes: the {LABEL[k]} on {r.display} is {v}{within}."
    if q.metrics:
        for r in rows:
            other = next((k for k, v in r.rates.items() if _holds(v, pct)), None)
            if other:
                asked = next((k for k in q.metrics if k in r.rates), None)
                its = f"; its {LABEL[asked]} is {r.rates[asked]}" if asked else ""
                return f"No: {pct:g}% is the {LABEL[other]} on {r.display}, not its {LABEL[q.metrics[0]]}{its}."
    return f"No, none of the current rates in this category is {pct:g}%. Current rates:"


def fact(r):
    return tuple(sorted(r.rates.items()))


def fmt_date(d: Optional[date]) -> str:
    return d.strftime("%m/%d/%Y") if d else "no effective date printed"


@dataclass
class RateAnswer:
    text: str
    sources: list = field(default_factory=list)    # [(url, quote, snapshot_id where that page version was seen)]
    confident: bool = True
    note: Optional[str] = None
    effective: list = field(default_factory=list)  # effective dates of the rows shown (None = not printed)


NOT_LISTED = ("I don't know: the website doesn't list a rate for that. "
              "Please contact Dupaco or see the rate sheet at https://www.dupaco.com/rates.")


def answer_rate_question(view, question: str) -> Optional[RateAnswer]:
    q = parse_question(question)
    if q is None:
        return None
    pairs = [(d, r) for d in view.pages.values() if d.kind != "expired" for r in d.rates if r.family == q.family]
    if not pairs:
        return None                                   # the site has no rate table for this: leave it to text search
    printed = re.sub(r"['’]", "", " ".join(f"{r.caption} {r.display}" for _, r in pairs).lower())
    if any(not re.search(rf"\b{re.escape(k.split()[0])}", printed) for k in q.kinds):
        return None       # "construction loan" is not a row of the mortgage table: text search, about that kind only
    named = unknown_names(question)
    if any(w not in printed for w in named):
        return None       # a product no rate table names: text search
    winners, losers = compete(pairs)
    winners = fill_metrics(winners, losers)
    if named:             # "Mortgage Rate Relief Program": only rows of that product, from the current tables
        has = lambda r: all(w in re.sub(r"['’]", "", f"{r.caption} {r.display}".lower()) for w in named)
        winners = [(d, r) for d, r in winners if has(r)]
        if not winners:   # only an out-of-date page still lists it (rule 5: products compete as whole tables)
            return RateAnswer(text="I don't know a current rate for that: the current rate tables no longer list it. "
                                   "Please contact Dupaco or see https://www.dupaco.com/rates.", confident=False)
    main, extra = select(winners, q)
    if not main and not extra:
        return RateAnswer(text=NOT_LISTED, confident=False)

    # business twins that pay exactly what the personal account pays: say so once instead of repeating them
    twin = lambda r, quals: (r.family, r.name, quals, r.term_months, r.tier_hi, r.years, fact(r))
    personal = {twin(r, r.quals) for _, r in main + extra if "business" not in r.quals}
    twins = {id(r) for _, r in extra if "business" in r.quals and twin(r, r.quals - {"business"}) in personal}
    extra = [(d, r) for d, r in extra if id(r) not in twins]

    # group rows by the table they came from: "<caption> (effective MM/DD/YYYY): row; row"
    groups, order = defaultdict(list), []
    for doc, r in main + extra:
        g = (doc.url, r.table)
        if g not in groups:
            order.append(g)
        groups[g].append((doc, r))
    lines = []
    if q.check_pct is not None:
        lines.append(check_line([r for _, r in main + extra], q))
    if q.amounts and all(r.min_amount and r.min_amount > max(q.amounts) for _, r in main + extra):
        low = min((r for _, r in main + extra), key=lambda r: r.min_amount)
        lines.append(f"{fmt_money(max(q.amounts))} is below the {fmt_minimum(low)}, so it would not earn "
                     f"the rate{'s' if len(main + extra) > 1 else ''} below; you need at least that amount.")
    shown_main = {id(r) for _, r in main}
    for g in order:
        members = groups[g]
        doc, first = members[0]
        title = first.caption or first.display.split(":")[0]
        if "business" in first.quals and "business" not in title.lower():
            title = "Business " + title
        prefix = "" if id(first) in shown_main else "Also: "
        body = "; ".join(fmt_row(r, first.caption) for _, r in members)
        when = f"effective {fmt_date(first.effective)}" if first.effective else "no effective date printed"
        if not first.caption and len(members) == 1:
            lines.append(f"{prefix}{body} ({when}).")      # a lone prose line: its label already names it
        else:
            lines.append(f"{prefix}{title} ({when}): {body}.")
    if twins:
        lines.append("The business versions of these accounts pay the same rates.")

    # sources: the winning pages first, then other pages that print the very same numbers
    current = {(r.key, r.slot): fact(r) for _, r in winners}
    shown = {(r.key, r.slot, fact(r)) for _, r in main + extra}
    urls = []
    agree = sorted(((d, r) for d, r in losers if (r.key, r.slot, fact(r)) in shown),
                   key=lambda p: (-p[0].authority, p[0].url, p[1].raw))
    for doc, r in main + extra + agree:
        if doc.url not in [u for u, _, _ in urls]:
            urls.append((doc.url, r.raw, observed_in(view, doc)))
    lines.append("Source: " + ", ".join(u for u, _, _ in urls[:3]))

    # stale values: rows from losing tables that would also have answered this question, and whose
    # numbers differ from the current table (or whose tier the current table no longer lists)
    stale_main, stale_extra = select(losers, q)
    stale = sorted({(d.url, fmt_date(r.effective), fmt_row(r)) for d, r in stale_main + stale_extra
                    if current.get((r.key, r.slot)) != fact(r)})
    note = None
    if stale:
        note = ("Answered from the table with the newest effective date. Out-of-date values on other pages: "
                + "; ".join(f"{url} (effective {d}): {row}" for url, d, row in stale[:4]))
    return RateAnswer(text="\n".join(lines), sources=urls[:5], note=note,
                      effective=[r.effective for _, r in main + extra])
