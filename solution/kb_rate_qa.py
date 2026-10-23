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
NEGATED = re.compile(r"\b(?:not|excluding|other than|besides|rather than|instead of|except|don'?t|do not|without|"
                     r"skip|leave out)\b[^,.;?]*"
                     r"|\bnon-?\s?(?:jumbo|business|refinanc\w*|intro\w*|promo\w*)"
                     r"|\bkeep(?:ing)?\s+[^,.;?]{0,40}?\b(?:separate|apart|aside)\b", re.I)
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
    ("certificate", r"certificate|\bcerts?\b|\bcds?\b|term.share|\bjumbo special|\b\d+.month (?:fixed )?(?:jumbo )?special|"
                    r"\b\d+.month (?:fixed )?jumbo|\bjumbo (?:apys?|dividends?|yields?)\b"),
    ("money_market", r"money market"),
    ("checking", r"checking"),
    ("credit_card", r"credit cards?|\bvisa\b|\bcards?\b"),
    ("atv", r"\batvs?\b|snowmobile|jet.?ski"),
    ("boat_rv", r"\bboats?\b|\brvs?\b|camper|recreational"),
    ("auto", r"\bauto|\bcars?\b|vehicle|truck|motorcycle|model.year"),
    ("heloc", r"heloc|line of credit"),
    ("home_equity_loan", r"home equity"),
    ("home_improvement", r"home improvement|renovat"),
    ("mortgage", r"mortgage|home loan|\bhouse\b|\d+.?(?:year|yr) fixed|conventional|refinanc|\brefi\b|\barms?\b|adjustable|"
                 r"home purchase|\d+.?(?:year|yr) (?:fixed )?purchase|purchase (?:loan|tier|row)"),
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
# "rate AND APR", "rate/apr": the nominal rate is asked too (not inside "annual percentage rate", "rate sheet" ...)
PLAIN_RATE = re.compile(r"\brates?\b")
NOT_PLAIN_RATE = re.compile(r"annual percentage rates?|dividend rates?|rates? (?:sheet|lock|relief|card)s?|"
                            r"\b(?:1st|first) rate\b|\brates?\s+(?:effective|as of)\b", re.I)


def plain_rate_asked(ql: str) -> bool:
    return bool(PLAIN_RATE.search(NOT_PLAIN_RATE.sub(" ", ql)))

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
           "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
           "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30}
Q_TERM = re.compile(r"\b(\d{1,3}|(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)[- ](?:one|two|three|four|five|six|"
                    r"seven|eight|nine)|" + "|".join(WORDNUM) + r")\s*-?\s*(months?|mos?\b|years?|yrs?\b)", re.I)
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


def term_number(word: str) -> int:
    """'24' 24; 'four' 4; 'twenty four' / 'twenty-four' 24."""
    if word.isdigit():
        return int(word)
    parts = re.split(r"[- ]", word.lower())
    return TENS.get(parts[0], 0) + WORDNUM.get(parts[-1], 0) if len(parts) == 2 else WORDNUM[parts[0]]
Q_AMOUNT = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(k|m|million|thousand)?\b|\b(\d+(?:\.\d+)?)\s*(k|thousand|million)\b", re.I)
Q_YEAR = re.compile(r"\b(19[89]\d|20[0-3]\d)\b")
Q_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
# "minimum"/"maximum" alone is usually the deposit or loan amount ("the APY/minimum pair"); next to a rate word
# ("the maximum APR", "minimum rate") it is the extreme
RATE_NEAR = r"(?=\s+(?:[\w-]+\s+)?(?:rates?|aprs?|apys?|yields?|dividends?|interest)\b)"
MAX_WORDS = re.compile(rf"\b(highest|most|top|(?:maximum|max){RATE_NEAR})\b", re.I)
MIN_WORDS = re.compile(rf"\b(lowest|cheapest|least|(?:minimum|min){RATE_NEAR})\b", re.I)
BEST = re.compile(r"\bbest\b", re.I)
# the top (or bottom) balance tier itself, asked next to a balance: "...for $12,000, and the highest tier's APY/threshold"
TOP_TIER = re.compile(r"\b(?:highest|top|largest|biggest|lowest|bottom|smallest)\b[^.?;]{0,60}"
                      r"\b(?:tiers?|thresholds?|starting balances?|(?:its|that) (?:minimum |required )?balance)\b"
                      r"|\b(?:tiers?|thresholds?)\b[^.?;]{0,15}\b(?:highest|top|lowest|bottom)\b", re.I)


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
    ruled_out: set = field(default_factory=set)  # qualifiers the question excludes ("non-jumbo" -> jumbo)
    terms: list = field(default_factory=list)   # every term named: "6-month or 24-month?" -> [6, 24]
    top_tier: bool = False   # "the $12,000 APY and the highest tier's threshold": that tier as well
    also_business: bool = False  # "the personal Rewards Visa APR vs the Business Rewards Visa APR": both

    @property
    def generic(self) -> bool:
        """'What are your certificate rates?' - no product, tier or term named: list everything."""
        return not self.names and not self.terms and not self.amounts and self.year is None


SMALL = {**WORDNUM, "eleven": 11, "thirteen": 13, "fourteen": 14, "sixteen": 16, "seventeen": 17, "eighteen": 18,
         "nineteen": 19, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
         "a": 1, "an": 1, "hundred": 100}
FRACTION = {"quarter": 0.25, "half": 0.5, "three-quarter": 0.75, "three quarter": 0.75, "three-quarters": 0.75}


def word_amounts(ql: str) -> list:
    """Amounts written in words: 'seven grand' 7,000; 'nine thousand bucks' 9,000; 'twenty-five thousand'
    25,000; 'three-quarter-million-dollar' 750,000; 'half a million' 500,000; 'a million' 1,000,000."""
    out, taken = [], []
    for m in re.finditer(r"\b(three[- ]quarters?|quarter|half)(?:[- ](?:of[- ])?an?)?[- ]million\b", ql):
        out.append(FRACTION[m.group(1).replace("quarters", "quarter")] * 1_000_000)
        taken.append(m.span())
    num = r"(\d+(?:\.\d+)?|(?:" + "|".join(SMALL) + r")(?:[- ](?:" + "|".join(SMALL) + r"))?)"
    for m in re.finditer(num + r"[- ](grand|thousand|k|million)\b", ql):
        if any(a <= m.start() < b for a, b in taken):
            continue          # "half a million" is not also "a million"
        words = re.split(r"[- ]", m.group(1))
        n = float(m.group(1)) if m.group(1)[0].isdigit() else sum(SMALL[w] for w in words if w in SMALL)
        if m.group(1) in ("a", "an") and m.group(2) != "million":
            continue
        out.append(n * (1_000_000 if m.group(2) == "million" else 1_000))
    return out


def word_year(ql: str) -> Optional[int]:
    """Model years written another way: "a '26 car" 2026; "twenty-twenty-five" 2025."""
    m = re.search(r"['’](\d{2})\b", ql)
    if m:
        return 2000 + int(m.group(1))
    m = re.search(r"\btwenty[- ]twenty(?:[- ](one|two|three|four|five|six|seven|eight|nine))?\b", ql)
    if m:
        return 2020 + (WORDNUM.get(m.group(1), 0) if m.group(1) else 0)
    return None


# product names members misspell ("brite savings", "launch pad savings"): the word right before the product noun,
# if it is close to a name keyword ("right now" is not "bright": it isn't followed by "savings")
FUZZY = {"savings": ({"bright": "bright savings", "launchpad": "launchpad savings", "holiday": "holiday club"},
                     r"savings|club|account"),
         "money_market": ({"investor": "investor's choice", "achieve": "achieve"}, r"choice|money market"),
         "credit_card": ({"platinum": "platinum visa", "rewards": "rewards visa"}, r"visa|card")}


def fuzzy_names(family: str, ql: str) -> set:
    import difflib
    targets, nouns = FUZZY.get(family, ({}, None))
    if not nouns:
        return set()
    words = re.findall(rf"\b([a-z][a-z']{{3,}})\s+(?:{nouns})\b", ql.replace("launch pad", "launchpad"))
    return {targets[t] for w in words for t in difflib.get_close_matches(w, list(targets), n=1, cutoff=0.7)}


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
            known = any(re.search(rx, w) for _, rx in Q_QUALS + Q_FAMILIES + [x for v in Q_NAMES.values() for x in v])
            if w not in GENERIC_NAME_WORDS and not known:    # "Roth", "Traditional", "Bright" are parsed already
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
        if m.group(1) in PLAIN_WORDS or m.group(1) in WORDNUM or m.group(1).isdigit() or Q_TERM.fullmatch(m.group(1)) \
                or any(s < b and a < e for s, e in spans):
            continue          # "thirty-year home loan": a term, not a kind of loan; "four cards": a count
        out.append(f"{m.group(1)} {m.group(2)}")
    return out


def normalize(question: str) -> str:
    """'personal-loan' -> 'personal loan', 'home-purchase' -> 'home purchase'; 'First Rate Checking' is the
    site's '1st Rate Checking'."""
    ql = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", question.lower())
    return re.sub(r"\bfirst rate\b", "1st rate", ql)


def parse_question(question: str) -> Optional[RateQuery]:
    ql = normalize(question)
    if CONDITION.search(ql):
        return None       # "what credit score do I need for the 6.25% HELOC rate?": the answer is in the text
    # "the older CHECKING-PAGE examples", "an August checking table" name where a figure was printed, not the
    # product asked about - unless nothing else names one
    pages = re.sub(r"\b(?:checking|savings|money market)\s+(?:pages?|tables?|tabs?|sheets?)\b", " ", ql)
    families = [f for f, rx in Q_FAMILIES if re.search(rx, pages)] or [f for f, rx in Q_FAMILIES if re.search(rx, ql)]
    # a product name implies its family ("What does a Holiday Club account earn?") and beats a bare family word
    # ("money-market yields were given for Share Savings": the question is about Share Savings)
    named = [f for f, names in Q_NAMES.items() if f not in ("certificate", "ira")
             for _, rx in names if re.search(rx, ql)]
    family = families[0] if families and (not named or families[0] in named) else named[0] if named else ""
    if not family:
        return None
    intent = RATE_IN_NAME.sub(" ", ql)
    if not (RATE_INTENT.search(intent) or (family in DEPOSITS and EARN_INTENT.search(ql))
            or (family not in DEPOSITS and CHARGE_INTENT.search(ql)) or MOVE_INTENT.search(ql)):
        return None
    names = {n for n, rx in Q_NAMES.get(family, []) if re.search(rx, ql)} or fuzzy_names(family, ql)
    quals = {q for q, rx in Q_QUALS if re.search(rx, NEGATED.sub(" ", ql))}
    both = "business" in quals and bool(re.search(r"\b(?:personal|consumer)\b", NEGATED.sub(" ", ql)))
    if both:
        quals.discard("business")     # "personal cards as well as business cards": both, the business ones after
    ruled_out = {q for q, rx in Q_QUALS for m in NEGATED.finditer(ql) if re.search(rx, m.group(0))}
    pair = r"\s*(?:,|and|&|plus|as well as|versus|vs\.?|or)\s+(?:the\s+)?"
    if "jumbo" in quals and (re.search(rf"\b(?:regular|standard|non-?jumbo){pair}jumbo\b|\bjumbo{pair}(?:regular|standard)\b", ql)
                             or re.search(r"\b(?:regular|standard)\b", ql) and re.search(r"\b(?:each|both)\b", ql)):
        quals.discard("jumbo")        # "the regular and jumbo 17-month specials": both, each with its own minimum
    elif re.search(r"\b(standard|regular|ordinary|normal|ongoing|non-?jumbo)\b", ql):
        ruled_out |= SECONDARY - quals         # "the standard 10-month special": not the jumbo or intro rows
    terms = []
    for m in Q_TERM.finditer(ql):
        n = term_number(m.group(1))
        terms.append(n * 12 if m.group(2).startswith("y") else n)
    term = terms[0] if terms else None
    amounts = []
    for m in Q_AMOUNT.finditer(ql):
        a = _amount(m.group(1), m.group(2)) if m.group(1) else _amount(m.group(3), m.group(4))
        if re.search(r"\b(more than|over|above|greater than|exceeding|bigger than)\s*$", ql[:m.start()]):
            a += 0.01     # "borrowing more than $300,000" is not in the "$300,000 or less" tier
        amounts.append(a)
    amounts += word_amounts(ql)
    year = None
    if family in ("auto", "atv"):         # the model year, not the year of a date ("in late August 2026 ... a 2017 car")
        undated = re.sub(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?:\d{1,2}(?:st|nd|rd|th)?,?\s+)?"
                         r"20\d\d\b|\b20\d\d-\d\d(?:-\d\d)?\b|\b\d{1,2}/\d{1,2}/20\d\d\b", " ", ql)
        m = Q_YEAR.search(undated)
        year = int(m.group(1)) if m else word_year(undated)
    # "its MINIMUM opening amount", "the maximum loan amount" name a requirement, not the lowest or highest rate
    plain = re.sub(r"\b(?:minimum|maximum|max|min)\s+(?:(?:opening|initial|required|loan)\s+)?(?:amounts?|deposits?|"
                   r"balances?|opening|to (?:open|earn)|credit|payments?|terms?|ltv)\b"
                   r"|\b(?:opening|deposit|balance)\s+(?:minimums?|maximums?)\b", " ", ql)
    extreme = "max" if MAX_WORDS.search(plain) else "min" if MIN_WORDS.search(plain) else None
    top_tier = bool(amounts and extreme and TOP_TIER.search(ql))
    if extreme is None and BEST.search(ql):
        extreme = "max" if family in DEPOSITS else "min"      # best savings rate = highest, best loan rate = lowest
    m = Q_PCT.search(ql)
    asked = NEGATED.sub(" ", ql)          # "the APY, not the dividend rate": only the APY is asked
    named = [k for metric, rx in Q_METRICS if re.search(rx, asked) for k in METRIC_KEYS[metric]]
    if named and plain_rate_asked(ql):
        named += ["rate", "dividend"]       # "rate and APR": the nominal rate (or dividend rate) too
    return RateQuery(family, names, quals, term, amounts, year, extreme, float(m.group(1)) if m else None,
                     metrics=tuple(named) or None, kinds=unknown_kinds(ql, family), terms=terms, ruled_out=ruled_out,
                     top_tier=top_tier, also_business=both)


# ---------------------------------------------------------------- choosing the current table

def table_rank(doc, row, today: Optional[date] = None):
    """Rule 2 then rule 3, then a fixed tie-break so the same question always gets the same answer. A table that
    takes effect after `today` (the download's date) is announced, not current: it ranks below every table in effect."""
    pending = bool(today and row.effective and row.effective > today)
    return (not pending, row.effective or date.min, doc.authority, -len(doc.key), doc.key, -row.table)


def _disagree(rows_a, rows_b) -> bool:
    """Two tables print different numbers for a tier both list."""
    slots = {r.slot: r for r in rows_a}
    return any(r.slot in slots and any(_values(v) != _values(slots[r.slot].rates[k])
                                       for k, v in r.rates.items() if k in slots[r.slot].rates) for r in rows_b)


def tied(winners) -> set:
    """Product keys whose winners come from more than one table: equally authoritative, equally dated, disagreeing."""
    tables = defaultdict(set)
    for d, r in winners:
        tables[r.key].add((d.key, r.table))
    return {k for k, t in tables.items() if len(t) > 1}


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


def compete(pairs, today: Optional[date] = None):
    """pairs: [(doc, row)] -> (winning pairs, losing pairs). One winning table per product key - unless another
    table is in effect, dated the same day, equally trusted and prints different numbers: then no winner is
    invented and both tables win (tied(); answers show both, conflicts get no resolution)."""
    tables = defaultdict(lambda: defaultdict(list))
    for doc, row in pairs:
        tables[row.key][(doc.key, row.table)].append((doc, row))
    winners, losers = [], []
    for by_table in tables.values():
        rank = {t: table_rank(*by_table[t][0], today) for t in by_table}
        best = max(by_table, key=rank.get)
        level = rank[best][:3]
        tie = {t for t in by_table if t != best and rank[t][:3] == level
               and _disagree([r for _, r in by_table[best]], [r for _, r in by_table[t]])}
        for t, members in by_table.items():
            (winners if t == best or t in tie else losers).extend(members)
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
    required = q.quals - {"arm", "intro"}
    either = {"roth", "traditional"} if {"roth", "traditional"} <= required else set()   # "Roth and Traditional": both
    pairs = [p for p in pairs if required - either <= p[1].quals and (not either or either & p[1].quals)
             and "arm" not in q.quals and ("intro" not in q.quals or promo(p[1]))]
    if q.names:
        pairs = [p for p in pairs if p[1].name in q.names]
    tagged = []
    for doc, r in pairs:
        unasked = r.quals - q.quals
        if "refinance" in unasked or ("business" in unasked and not (q.generic or q.also_business)) \
                or r.quals & q.ruled_out:
            continue
        tagged.append((doc, r, bool(unasked & (SECONDARY | {"business"}))))

    rows = [t[1] for t in tagged]
    if q.terms and any(r.term_months is not None for r in rows):
        tagged = [t for t in tagged if t[1].term_months in q.terms]     # "6-month or 24-month": both
    if q.year is not None and any(r.years for r in rows):
        tagged = [t for t in tagged if t[1].years and t[1].years[0] <= q.year <= t[1].years[1]]
    tiers = [t for t in tagged if not t[2] and t[1].tier_lo is not None]
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
    if q.top_tier and tiers:
        # the balance's tier and, besides it, each product's top (bottom) tier: the highest threshold's row
        edge = max if q.extreme == "max" else min
        for key in dict.fromkeys((t[1].key, t[1].term_months) for t in tiers):
            same = [t for t in tiers if (t[1].key, t[1].term_months) == key]
            lo = edge(t[1].tier_lo for t in same)
            main += [(d, r) for d, r, _ in same if r.tier_lo == lo and all(r is not m[1] for m in main)]
        return main, []
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


def fmt_row(r, title: str = "", metrics=None) -> str:
    """metrics: the rate keys the question names ("APY" -> apy, promo_apy). Only those are shown when the row has
    them: the dividend rate is a different number from the APY, and printing it to an APY question is a wrong value."""
    keys = [k for k, _ in METRICS if k in r.rates]
    if metrics and any(k in metrics for k in keys):
        keys = [k for k in keys if k in metrics]
    vals = [f"{r.rates[k]} {LABEL[k]}" for k in keys]
    name = r.display[len(title) + 3:] if title and r.display.startswith(f"{title} – ") else r.display
    # a balance tier already says how much is needed; otherwise the minimum is part of the fact ($100,000 jumbo)
    cond = f" ({fmt_minimum(r)})" if r.tier_lo is None and r.min_amount else ""
    return f"{name}: {' / '.join(vals)}{cond}"


METRIC_WORDS = {"apy": r"APY|annual percentage yield", "apr": r"APR|annual percentage rate",
                "dividend": r"dividend rate"}


def asked_metrics(question: str) -> set:
    ql = NEGATED.sub(" ", question.lower())
    return {m for m, rx in Q_METRICS if re.search(rx, ql)} | ({"rate"} if plain_rate_asked(ql) else set())


def keep_asked_metrics(text: str, question: str) -> str:
    """'APY 4.60%; dividend rate 4.55%' answering 'What APY ...?' -> 'APY 4.60%': a dividend rate is a different
    number from the APY, and repeating it to an APY question gives a wrong value. Only when one metric is asked."""
    asked = asked_metrics(question)
    if len(asked) != 1:
        return text
    for m, words in METRIC_WORDS.items():
        if m in asked:
            continue
        pct = r"\d+(?:\.\d+)?\s*%"
        text = re.sub(rf"[;,/]?\s*\b(?:{words})\s*(?:of|is|:)?\s*{pct}|[;,/]?\s*{pct}\s*(?:{words})\b", "", text, flags=re.I)
    text = re.sub(r"(:\s*)(?!//)[/;,]\s*", r"\1", text)    # "Special: / 4.10% APY" -> "Special: 4.10% APY" (not "https://")
    return re.sub(r"\s+([.;,])", r"\1", text)              # "4.06% dividend rate ." -> "4.06% dividend rate."


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


# "Was a 17-month special LISTED on May 19?" asks about the rate table: no, it wasn't there. "Does Dupaco OFFER a
# 96-month certificate?" asks about the product: a table without it doesn't prove there is none, so: don't know
PRESENCE = re.compile(r"\b(?:was|were|is|are|did|does|do|could|can)\b[^?]*\b(?:list(?:ed)?|find|found|show(?:n|s)?|"
                      r"include[ds]?|offered|appear(?:ed)?)\b", re.I)
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
    named = unknown_names(re.sub(r"(?i)\bfirst rate\b", "1st Rate", question))
    if any(w not in printed for w in named):
        return None       # a product no rate table names: text search
    today = date.fromisoformat(view.taken_on)
    winners, losers = compete(pairs, today)
    winners = fill_metrics(winners, losers)
    if named:             # "Mortgage Rate Relief Program": only rows of that product, from the current tables
        has = lambda r: all(w in re.sub(r"['’]", "", f"{r.caption} {r.display}".lower()) for w in named)
        winners = [(d, r) for d, r in winners if has(r)]
        if not winners:   # only an out-of-date page still lists it (rule 5: products compete as whole tables)
            return RateAnswer(text="I don't know a current rate for that: the current rate tables no longer list it. "
                                   "Please contact Dupaco or see https://www.dupaco.com/rates.", confident=False)
    main, extra = select(winners, q)
    if not main and not extra:
        if PRESENCE.search(question):
            # "Was a 17-month special listed on May 19?" asks whether it was there: no, and what was there instead
            listed = sorted({f"{r.term_months}-month {r.name or r.family.replace('_', ' ')}".strip()
                             for _, r in winners if r.term_months and r.name in (q.names or {r.name})})
            day = f"{today:%B} {today.day}, {today.year}"
            what = " ".join(x for x in (f"{q.terms[0]}-month" if q.terms else "",
                                        sorted(q.names)[0].title() if q.names and q.family not in ("certificate", "ira")
                                        else sorted(q.names)[0] if q.names else q.family.replace("_", " ")) if x)
            what = f"{'an' if what[:1].lower() in 'aeiou8' else 'a'} {what}" if what else "it"
            text = f"No. It was not listed: the rate tables as of {day} did not list {what}." + (
                f" Listed then: {', '.join(listed[:8])}." if listed else "")
            return RateAnswer(text=text, sources=[(d.url, r.raw, observed_in(view, d)) for d, r in winners[:1]])
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
        body = "; ".join(fmt_row(r, first.caption, q.metrics) for _, r in members)
        when = (f"takes effect {fmt_date(first.effective)}" if first.effective and first.effective > today
                else f"effective {fmt_date(first.effective)}" if first.effective else "no effective date printed")
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
    ties = tied(main + extra)
    if ties:
        lines.append("Note: equally authoritative pages dated the same day print different numbers for this "
                     "product, so both are shown; please confirm with Dupaco.")
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
