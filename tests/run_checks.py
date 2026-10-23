"""
Regression checks beyond the public eval. Run from the kit's top folder:

    python tests/run_checks.py

1. PARAPHRASES  59 reworded questions on the public topics (set A was tuned on; set B was written
                fresh and passed 27/30 on its first run, the misses were then fixed).
2. REVIEW       the cases from the 2026-10-21 code review (results/review/REVIEW.md), each pinned
                to the behaviour we decided on.
3. SYNTHETIC    tiny made-up snapshots for situations the real data doesn't contain.
4. MUTATIONS    one rule, one changed input each: future-effective tables, exact ties, a page missing from one
                download, a removed fee row, an expired offer, a stale calculator.
5. CONTROLS     paired controls for rules learned from bank items, in words no bank uses: an equivalent form
                must keep the answer, a minimally changed one (actor, qualifier, day, polarity) must change it.
6. DETERMINISM  the same answers under two hash seeds.
Exit code 1 if anything fails.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "solution"), str(ROOT / "harness")]
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from contract import Page, Snapshot  # noqa: E402
from inspect_kb import load  # noqa: E402
from kb_pages import canonical_url  # noqa: E402
from solution import build  # noqa: E402

REFUSE = "REFUSE"

# ---------------------------------------------------------------- 1. paraphrases: (question, expected substrings | REFUSE)
TUNED = [
    ("What's the 17 month certificate special paying?", ["4.10"]), ("current rate for a thirty year fixed mortgage", ["7.13", "7.25"]),
    ("auto loan APR for a 2026 car over 60 months", ["5.39"]), ("Tell me about your credit card interest rates", ["12.5", "15.5"]),
    ("What's the APY on Share Savings for a $15,000 balance?", ["0.15"]), ("What is the ABA routing number for Dupaco?", ["273974581"]),
    ("When is the lobby open?", ["8:30"]), ("What time does the drive-thru open?", ["8 a.m."]), ("Where is the Galena branch?", ["11375"]),
    ("How many locations does Dupaco currently operate?", ["22"]), ("Is the Hy-Vee location closed now?", ["March 31, 2026"]),
    ("Has Dupaco been recognized by Forbes?", ["fifth"]), ("Where should I go to see CD rates online?", ["savings-account"]),
    ("What rate does 1st Rate Checking pay?", ["2.50"]), ("What is the interest rate on a 7/1 ARM?", REFUSE),
    ("Who can join Dupaco?", ["Iowa"]), ("What is the Home$tart grant?", ["15,000"]), ("How much is a 36 month personal loan APR?", ["10.49"]),
    ("What's the rate on a land loan?", REFUSE), ("Which branches can former Hy-Vee branch members use?", ["Key West"]),
    ("How many employees took Volunteer Time Off?", ["256"]), ("Which mobile wallets can I use with my Dupaco card?", ["Apple Pay"]),
    ("What are the hours of the Dupaco branch on Mullan Ave?", REFUSE), ("How do I apply for membership online?", ["join.dupaco.com"]),
    ("What's the URL of the branch locator?", ["dupaco.com/contact"]), ("Phone number to update my address?", ["800-373-7600"]),
    ("Do you offer student loans?", ["student"]), ("What is the Bright Savings APY?", ["2.25"]), ("What's the top Share Savings rate?", ["0.20"]),
]
FRESH = [
    ("What does the 10-month jumbo certificate special pay?", ["4.00"]), ("Give me the 15 year mortgage rate", ["6.75"]),
    ("APR on an 84 month loan for a 2021 truck?", ["6.04"]), ("What's the Rewards Visa APR range?", ["15.5", "21"]),
    ("What's the HELOC APR?", ["6.25"]), ("Do you have a routing number I can use for direct deposit?", ["273974581"]),
    ("Are you open on Saturdays?", ["12:30"]), ("What's the address of the Platteville branch?", ["1100"]),
    ("How many branch offices does Dupaco have now?", ["22"]), ("When did the Hy-Vee branch shut down?", ["March 31, 2026"]),
    ("Is Dupaco a Forbes Best-in-State credit union?", ["Forbes"]), ("Where do I find Dupaco's certificate rates on the website?", ["savings-account"]),
    ("What APY does 1st Rate Checking earn on $10,000?", ["2.50"]), ("What is your rate on a 5/1 adjustable rate mortgage?", REFUSE),
    ("What are the membership requirements?", ["charter"]), ("How much down payment help does Home$tart give?", ["15,000"]),
    ("What's the APR for a 48 month personal loan?", ["10.99"]), ("What is the rate on a lot loan?", REFUSE),
    ("Where can Hy-Vee members bank now?", ["Sycamore"]), ("How many employees used VTO in 2023?", ["294"]),
    ("Can I use Samsung Pay with Dupaco?", ["Samsung Pay"]), ("What are the hours for the Dupaco branch in Springfield?", REFUSE),
    ("Where do I go to join Dupaco online?", ["join.dupaco.com"]), ("What's the link to find a branch or ATM?", ["dupaco.com/contact"]),
    ("Who do I call to change my email address on file?", ["800-373-7600"]), ("Does Dupaco offer student loan refinancing?", ["refinanc"]),
    ("What's the High-Yield Savings APY for $500,000?", ["2.25"]), ("Is there a savings account that pays 0.35%?", ["0.20"]),
    ("What's the boat loan rate for $50,000 over 120 months?", ["9.34"]), ("What does a 12-month certificate earn?", ["3.40"]),
]


def refused(a, question=""):
    """Declined, and no number that the question didn't contain (the scorer's rule)."""
    extra = set(re.findall(r"\d+", a.text)) - set(re.findall(r"\d+", question))
    return not a.confident and not extra


# ---------------------------------------------------------------- 1b. paired controls (anti-overfit gate)
# Each rule added from a bank item is checked in words no bank uses: SAME forms must give the asked facts, and a
# minimally CHANGED form (other actor, qualifier, day, polarity or clause order) must change the answer with it.
# (question, as_of, values that must appear, values that must not appear)
HAS = lambda *v: v
CONTROLS = {
    "regular and jumbo together": [
        ("What APY and opening minimum go with the standard 17-month special and with the jumbo one?", None, HAS("4.10%", "4.20%", "$100,000"), ()),
        ("Give me the 17-month special APY for both the regular version and the jumbo version.", None, HAS("4.10%", "4.20%"), ()),
        ("What is the APY on the regular 17-month special?", None, HAS("4.10%"), ("4.20%",)),
        ("What is the APY on the jumbo 17-month special?", None, HAS("4.20%"), ("4.10%",)),
    ],
    "personal and business cards": [
        ("List the APRs on Dupaco's personal and business Visa cards.", None, HAS("12.50%", "21.00%", "15.50%", "20.50%"), ()),
        ("How does the business Rewards Visa APR differ from the personal Rewards Visa APR?", None, HAS("21.00%", "20.50%"), ()),
        ("What APR does the Business Rewards Visa charge?", None, HAS("20.50%"), ("21.00%",)),
        ("What APR does the personal Rewards Visa charge?", None, HAS("21.00%"), ("20.50%",)),
    ],
    "each named day": [
        ("What was the 60-month APR for a 2023 model-year car on August 27 and on September 28?", None, HAS("5.19%", "5.64%"), ()),
        ("From the August 27 snapshot to the September 28 one, how did the 60-month APR on a 2023 car move?", None, HAS("5.19%", "5.64%"), ()),
        ("What was the 60-month APR for a 2023 model-year car on August 27, 2026?", None, HAS("5.19%"), ("5.64%",)),
        ("What is the 60-month APR for a 2023 model-year car today?", None, HAS("5.64%"), ("5.19%",)),
    ],
    "minimum: requirement or extreme": [
        ("What is the minimum opening deposit and the APY for the 17-month jumbo special?", None, HAS("4.20%", "$100,000"), ()),
        ("Which 17-month special has the minimum APY?", None, HAS("4.10%"), ("4.20%",)),
    ],
    "listed then, or offered at all": [
        ("Was a 96-month certificate listed in the September 28, 2026 rate table?", None, HAS("not listed"), ()),
        ("Is there a 96-month share certificate at Dupaco, and what does it earn?", None, REFUSE, ()),
    ],
    "fee by phone, or the phone number": [
        ("How much is the fee to pay with a card over the phone?", None, HAS("$15.00"), ()),
        ("What phone number do I call about my credit card?", None, HAS("800-373-7600"), ()),
    ],
    "a balance's tier and the top tier": [
        ("For $15,000 in Share Savings what APY applies, and what are the APY and starting balance of the top tier?", None,
         HAS("0.15%", "0.20%", "$25,000"), ()),
        ("What APY does $15,000 earn in Share Savings?", None, HAS("0.15%"), ("0.20%",)),
    ],
    "every asked part": [
        ("On Dupaco student loans, can I defer payments while in school, is there a graduated repayment option, and is "
         "there an origination fee?", None, HAS("graduated", "$0"), ()),
        ("What is the origination fee on Dupaco student loans?", None, HAS("$0"), ()),
    ],
    "several model years": [
        ("What 60-month APRs apply to a 2022 car and to a 2025 car?", None, HAS("5.64%", "5.39%"), ()),
        ("For 60 months, what does a 2025 car's APR compare to a 2022 car's?", None, HAS("5.64%", "5.39%"), ()),
        ("What 60-month APR applies to a 2025 car?", None, HAS("5.39%"), ("5.64%",)),
    ],
    "purchase and refinance together": [
        ("Give the 30-year purchase and refinance quotes for a $100,000 conventional loan.", None, HAS("7.27%", "7.28%"), ()),
        ("What is the 30-year refinance APR for $100,000?", None, HAS("7.28%"), ("7.27%",)),
        ("What is the 30-year purchase APR for $100,000?", None, HAS("7.27%"), ("7.28%",)),
    ],
    "the two ends of the terms": [
        ("Which personal loan terms are the shortest and the longest, and their APRs?", None, HAS("9.99%", "12.49%"), ("10.49%", "10.99%")),
        ("List every personal loan term and APR.", None, HAS("9.99%", "10.49%", "10.99%", "12.49%"), ()),
    ],
    "two terms compared are two rates": [
        ("How does a regular 36-month Roth IRA stack up against the 17-month Roth IRA special?", None, HAS("2.10%", "4.10%"), ()),
    ],
    "which tier and its rate: one question": [
        ("Which Investor's Choice tier covers $12,000, and what is its APY?", None, HAS("0.30%"), ("0.25%", "0.35%")),
    ],
    "the asker's own account": [
        ("Could you look up my savings balance from these pages?", None, REFUSE, ()),
        ("What is the minimum balance to earn the 1st Rate Checking APY?", None, HAS("$5,000"), ()),
    ],
    "the named kind of product": [
        ("Is there a penalty for paying off a Dupaco student loan early?", None, HAS("prepayment"), ()),
        ("Is there a penalty for paying off a Dupaco home equity loan early?", None, HAS("paying it off early"), ()),
    ],
    "the companion's specialist pages": [
        ("Can I put my Dupaco debit card or credit card in Samsung Pay or Google Pay?", None, HAS("debit", "credit", "Samsung Pay"), ()),
        ("What are the ways to qualify for Dupaco membership, and where do I start or continue an application?", None,
         HAS("Rural Ideas Network", "join.dupaco.com"), ()),
        ("What free admission do Dupaco members get through the museum partnership?", None, HAS("museum"), ("Rural Ideas",)),
    ],
    "a named product beats a family word": [
        ("Leave the money market numbers aside: what APY does Share Savings pay on $12,000?", None, HAS("0.15%"), ("0.30%",)),
        ("What APY does the Investor's Choice money market pay on $12,000?", None, HAS("0.30%"), ("0.15%",)),
    ],
}


def check_controls(kb):
    bad, total = [], 0
    for rule, cases in CONTROLS.items():
        for q, as_of, must, must_not in cases:
            total += 1
            a = kb.answer(q, as_of)
            ok = refused(a, q) if must == REFUSE else all(v in a.text for v in must) and not any(v in a.text for v in must_not)
            if not ok:
                bad.append(f"[{rule}] {q}  want {must} not {must_not}  ->  {a.text[:180]!r}")
    return "PAIRED CONTROLS", total - len(bad), total, bad


def check_paraphrases(kb, name, items):
    bad = []
    for q, exp in items:
        a = kb.answer(q)
        ok = refused(a, q) if exp == REFUSE else a.confident and all(e.lower() in a.text.lower() for e in exp)
        if not ok:
            bad.append(f"{q}  ->  {a.text[:160]!r}")
    return f"PARAPHRASES {name}", len(items) - len(bad), len(items), bad


# ---------------------------------------------------------------- 2. review cases: (question, as_of, test, what we expect)
REVIEW = [
    # 1. a percentage is checked against the number the question names (APY / APR / rate)
    ("Do any 17-month special certificates pay 4.06% APY?", None, lambda a: a.text.startswith("No"), "No: 4.06% is the dividend rate"),
    ("Do any 17-month special certificates pay 4.10% APY?", None, lambda a: a.text.startswith("Yes"), "Yes"),
    ("Is the 30-year mortgage APR 7.13%?", None, lambda a: a.text.startswith("No") and "7.27%" in a.text, "No: 7.13% is the rate; APR 7.27%"),
    ("Is the 30-year mortgage rate 7.13%?", None, lambda a: a.text.startswith("Yes"), "Yes"),
    # 2. a balance below the minimum (user decision A: give the rate, say the amount doesn't qualify)
    ("What is the APY for a 6-month certificate with a $500 deposit?", None,
     lambda a: "below the minimum" in a.text and "$1,000.00" in a.text and "3.40%" in a.text, "rate + $1,000 minimum"),
    ("What APY would $500 earn in High-Yield Savings?", None, lambda a: "$50,000.00" in a.text, "minimum to open $50,000"),
    ("What is the highest certificate APY available with a $1000 deposit?", None,
     lambda a: "4.10%" in a.text and "4.20%" not in a.text, "4.10% (the 4.20% jumbo needs $100,000)"),
    # 3. a loan kind the rate tables don't list (user decision C: decline, no numbers)
    ("What mortgage rate can I get for a construction loan?", None, refused, "declined"),
    ("What is the rate on a construction mortgage?", None, refused, "declined"),
    ("What is the APR on a land mortgage?", None, refused, "declined"),
    ("What is the rate on an FHA mortgage?", None, refused, "declined"),
    ("What is the VA mortgage rate?", None, refused, "declined"),
    ("What is the rate on a home equity loan?", None, lambda a: a.confident and "6.74%" in a.text, "known kind still answered"),
    ("What is the 30-year fixed mortgage rate?", None, lambda a: a.confident and "7.13%" in a.text, "plain mortgage still answered"),
    # 4. yes/no follows the question's polarity
    ("Is the Hy-Vee branch closed?", None, lambda a: a.text.startswith("Yes"), "Yes"),
    ("Is the Hy-Vee branch still open?", None, lambda a: a.text.startswith("No"), "No"),
    ("Has the Hy-Vee branch shut down?", None, lambda a: a.text.startswith("Yes"), "Yes"),
    # 5. a year the site has no figure for (user decision B: decline, no other year's number)
    ("How many employees used Volunteer Time Off in 2022?", None, refused, "declined"),
    ("How many employees used Volunteer Time Off in 2023?", None, lambda a: "294" in a.text, "294"),
    # later cases: a fee the site doesn't list, a product only a stale page still shows, change questions, dates in text
    ("How much does a lost debit card replacement cost?", None, refused, "declined (no such fee listed)"),
    ("What's the cashier's check fee?", None, refused, "declined (no such fee listed)"),
    ("How much is the incoming wire transfer fee?", None, lambda a: "$10.00" in a.text, "$10.00"),
    ("What is the Mortgage Rate Relief Program rate?", None, refused, "declined: only /homebuying-guidance still lists it"),
    ("What is the Mortgage Rate Relief Program rate?", "2026-06-01", lambda a: "5.125%" in a.text, "5.125% while /rates listed it"),
    ("Has the 10-month jumbo certificate special rate changed?", None,
     lambda a: "4.00%" in a.text and "Before that" in a.text and "3.90%" in a.text, "4.00% now, 3.90% before"),
    ("What was the 12-month certificate APY in May 2026?", None, lambda a: "2.90%" in a.text and "3.40%" not in a.text, "2.90%"),
    ("What is the 12-month certificate APY?", None, lambda a: "3.40%" in a.text and "2.90%" not in a.text, "3.40% only"),
    # reworded boilerplate: the newest wording carries the current figures
    ("What are Dupaco's total assets?", None, lambda a: "3.6 billion" in a.text and "2.6 billion" not in a.text, "$3.6 billion"),
    ("How many counties does Dupaco serve?", None, lambda a: "118 counties" in a.text, "118 counties"),
    ("Has the Dupaco Foundation hardship grant amount changed?", None,
     lambda a: "$3,500" in a.text and "Before that" in a.text and "$2,000" in a.text, "$3,500 now, $2,000 before"),
    ("How do I change my address with Dupaco?", None, lambda a: "Before that" not in a.text, "no change history for 'change my address'"),
]


def check_review(kb):
    bad = []
    for q, as_of, test, want in REVIEW:
        a = kb.answer(q, as_of)
        if not (test(a, q) if test is refused else test(a)):
            bad.append(f"{q}  want {want}  ->  {a.text[:160]!r}")
    # 6. a source's snapshot id is a download that really contained that page (not the view it was carried into)
    for q in ("What is the rate for the Bright Savings account?", "Do any Dupaco savings tiers pay 0.35% APY?"):
        for s in kb.answer(q).sources:
            view = next(v for v in kb.snaps if v.snapshot_id == s.snapshot_id)
            key = canonical_url(s.url)
            if key not in view.pages or key in view.carried:
                bad.append(f"{q}  source {s.url} is not in download {s.snapshot_id}")
    return "REVIEW cases", len(REVIEW) + 2 - len(bad), len(REVIEW) + 2, bad


# ---------------------------------------------------------------- 3. synthetic snapshots
def cert_page(url, rows, effective):
    text = "# Certificates\n\nRegular Certificates\n\n| Term | APY |\n| --- | --- |\n"
    text += "".join(f"| {term} Month | {rate}% |\n" for term, rate in rows)
    return Page(url, "Certificate rates", text + f"\nRates are effective as of {effective}.\n", "")


def check_synthetic():
    bad = []
    # 7. the newest table dropped the 6-month term; an old campaign page still prints it
    kb = build()
    stale = cert_page("https://www.dupaco.com/old-offer", [(6, "2.50")], "01/01/2026")
    kb.ingest(Snapshot("01", "2026-01-05", [cert_page("https://www.dupaco.com/rates", [(6, "3.00"), (12, "3.50")], "01/01/2026"), stale]))
    kb.ingest(Snapshot("02", "2026-03-01", [cert_page("https://www.dupaco.com/rates", [(12, "4.00")], "03/01/2026"), stale]))
    if kb.answer("What is the 6-month certificate APY?").confident:
        bad.append("retired term: the answer should decline")
    six = [c for c in kb.conflicts() if "6-month" in c.topic]
    if not six or six[0].resolution or any("[current" in v for v in six[0].values):
        bad.append(f"retired term: conflict should have no current value -> {six[0].resolution if six else 'missing'}")
    # 8. a fee page changed $2.00 -> $2.50
    kb = build()
    for sid, taken, fee in [("01", "2026-01-05", "2.00"), ("02", "2026-03-01", "2.50")]:
        kb.ingest(Snapshot(sid, taken, [Page("https://www.dupaco.com/fees", "Fee schedule",
                                             f"# Fee schedule\n\nThe lost debit card replacement fee is ${fee}.", taken)]))
    fee = kb.conflicts()
    if not fee or "$2.50" not in (fee[0].resolution or ""):
        bad.append(f"fee change: expected one conflict resolved to $2.50 -> {[c.resolution for c in fee]}")
    if "$2.00" not in kb.answer("How much is a lost debit card replacement?", "2026-01-31").text:
        bad.append("fee change: the January answer should be $2.00")
    return "SYNTHETIC snapshots", 4 - len(bad), 4, bad


# ---------------------------------------------------------------- 4. mutation tests: one rule, one changed input each
def page(url, title, text, taken=""):
    return Page(url, title, text, taken)


def table(term_rows, effective, caption="Regular Certificates"):
    t = f"{caption}\n\n| Term | APY |\n| --- | --- |\n" + "".join(f"| {m} Month | {v}% |\n" for m, v in term_rows)
    return t + f"\nRates are effective as of {effective}.\n"


def check_mutations():
    cases = []
    U = "https://www.dupaco.com"

    # M1 a table that takes effect after the download's date is announced, not current
    kb = build()
    pages = [page(f"{U}/rates", "Rates", "# Rates\n\n" + table([(12, "3.50")], "03/01/2026")),
             page(f"{U}/personal/savings-account", "Savings", "# Savings\n\n" + table([(12, "3.75")], "04/01/2026"))]
    kb.ingest(Snapshot("01", "2026-03-10", pages))
    a = kb.answer("What does a 12-month certificate pay?")
    cases.append(("future-effective table is not current yet", "3.50%" in a.text and "3.75%" not in a.text, a.text))
    kb.ingest(Snapshot("02", "2026-04-15", pages))
    a = kb.answer("What does a 12-month certificate pay?")
    cases.append(("...and is current once in effect", "3.75%" in a.text and "3.50%" not in a.text, a.text))

    # M2 equally trusted pages (both about certificates), same date, different numbers: both shown, no invented winner
    kb = build()
    kb.ingest(Snapshot("01", "2026-03-10", [
        page(f"{U}/personal/certificates", "Certificates", "# A\n\n" + table([(6, "3.00")], "03/01/2026")),
        page(f"{U}/personal/certificate-specials", "Certificate specials", "# B\n\n" + table([(6, "3.25")], "03/01/2026"))]))
    a = kb.answer("What is the 6-month certificate APY?")
    six = [c for c in kb.conflicts() if "6-month" in c.topic]
    cases.append(("exact tie: both values shown", "3.00%" in a.text and "3.25%" in a.text, a.text))
    cases.append(("exact tie: conflict without a winner", bool(six) and six[0].resolution is None,
                  six[0].resolution if six else "no conflict"))
    # M2b the same date and trust, but one page is about the product and the other embeds a copy (a certificate
    # table on the savings page): the product's own page wins
    kb = build()
    kb.ingest(Snapshot("01", "2026-03-10", [
        page(f"{U}/personal/certificates", "Certificates", "# A\n\n" + table([(6, "3.00")], "03/01/2026")),
        page(f"{U}/personal/savings-account", "Savings", "# B\n\n" + table([(6, "3.25")], "03/01/2026"))]))
    a = kb.answer("What is the 6-month certificate APY?")
    cases.append(("product page beats an embedded copy", "3.00%" in a.text and "3.25%" not in a.text, a.text))

    # M3 a page missing from one download is carried forward and cited from the download that had it
    kb = build()
    p1 = page(f"{U}/rates", "Rates", "# Rates\n\n" + table([(6, "3.00")], "01/01/2026"))
    p3 = page(f"{U}/rates", "Rates", "# Rates\n\n" + table([(6, "3.40")], "03/01/2026"))
    other = page(f"{U}/about", "About", "# About\n\nDupaco is a credit union.")
    kb.ingest(Snapshot("01", "2026-01-05", [p1, other]))
    kb.ingest(Snapshot("02", "2026-02-05", [other]))
    kb.ingest(Snapshot("03", "2026-03-05", [p3, other]))
    a = kb.answer("What is the 6-month certificate APY?", "2026-02-10")
    cases.append(("carried page answers the gap", "3.00%" in a.text and all(s.snapshot_id == "01" for s in a.sources),
                  f"{a.text} {[s.snapshot_id for s in a.sources]}"))
    a = kb.answer("What is the 6-month certificate APY?")
    cases.append(("...and the new version answers later", "3.40%" in a.text and "3.00%" not in a.text, a.text))

    # M4 a row removed from the new version of a page is not resurrected from the old one
    kb = build()
    kb.ingest(Snapshot("01", "2026-01-05", [page(f"{U}/fees", "Fee schedule",
              "# Fee schedule\n\nThe wire transfer fee is $25.00.\n\nThe stop payment fee is $30.00.")]))
    kb.ingest(Snapshot("02", "2026-02-05", [page(f"{U}/fees", "Fee schedule",
              "# Fee schedule\n\nThe stop payment fee is $30.00.")]))
    a = kb.answer("How much is the wire transfer fee?")
    cases.append(("removed fee row is unknown now", "$25" not in a.text and not a.confident, a.text))
    a = kb.answer("How much is the wire transfer fee?", "2026-01-20")
    cases.append(("...but known for its own date", "$25.00" in a.text, a.text))

    # M5 an expired offer page never answers, even with a higher, newer-looking rate
    kb = build()
    kb.ingest(Snapshot("01", "2026-03-10", [
        page(f"{U}/rates", "Rates", "# Rates\n\n" + table([(12, "3.40")], "01/01/2026")),
        page(f"{U}/cd-special-lp", "CD special", "Oops! This Offer Has Expired\n\n" + table([(12, "4.50")], "03/01/2026"))]))
    a = kb.answer("What does a 12-month certificate pay?")
    cases.append(("expired offer never answers", "3.40%" in a.text and "4.50%" not in a.text, a.text))

    # M6 a calculator's default rate loses to the rate sheet with the same date
    kb = build()
    kb.ingest(Snapshot("01", "2026-03-10", [
        page(f"{U}/rates", "Rates", "# Rates\n\n" + table([(12, "3.40")], "03/01/2026")),
        page(f"{U}/calculators/certificate", "Calculator", "# Calculator\n\n" + table([(12, "2.90")], "03/01/2026"))]))
    a = kb.answer("What does a 12-month certificate pay?")
    cases.append(("calculator loses to the rate sheet", "3.40%" in a.text and "2.90%" not in a.text, a.text))

    bad = [f"{name}  ->  {detail[:160]!r}" for name, ok, detail in cases if not ok]
    return "MUTATIONS", len(cases) - len(bad), len(cases), bad


def check_determinism():
    """The same question must get the same answer in every run. Python randomises set order per process
    (PYTHONHASHSEED), so any tie broken by set order would differ between runs: answer the paraphrase battery in
    two processes with different seeds and compare the texts."""
    import os
    import subprocess
    code = ("import json, sys; sys.path[:0] = ['solution', 'harness']; sys.stdout.reconfigure(encoding='utf-8');"
            "from inspect_kb import load; kb = load();"
            "qs = json.loads(sys.stdin.read()); print(json.dumps([kb.answer(q).text for q in qs]))")
    qs = [q for q, _ in TUNED + FRESH]
    outs = []
    for seed in ("1", "2"):
        p = subprocess.run([sys.executable, "-c", code], input=json.dumps(qs), capture_output=True, text=True,
                           encoding="utf-8", cwd=ROOT, env=dict(os.environ, PYTHONHASHSEED=seed))
        outs.append(json.loads(p.stdout.strip().splitlines()[-1]))
    bad = [f"{q}  ->  answers differ between runs" for q, a, b in zip(qs, *outs) if a != b]
    return "DETERMINISM (2 seeds)", len(qs) - len(bad), len(qs), bad


def main():
    kb = load()
    results = [check_paraphrases(kb, "A (tuned)", TUNED), check_paraphrases(kb, "B (fresh)", FRESH),
               check_controls(kb), check_review(kb), check_synthetic(), check_mutations(), check_determinism()]
    failed = 0
    for name, ok, total, bad in results:
        print(f"{name:24s} {ok}/{total}")
        for b in bad:
            print("   FAIL", b)
        failed += len(bad)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
