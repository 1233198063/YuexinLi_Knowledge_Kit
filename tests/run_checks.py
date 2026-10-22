"""
Regression checks beyond the public eval. Run from the kit's top folder:

    python tests/run_checks.py

1. PARAPHRASES  59 reworded questions on the public topics (set A was tuned on; set B was written
                fresh and passed 27/30 on its first run, the misses were then fixed).
2. REVIEW       the cases from the 2026-10-21 code review (results/review/REVIEW.md), each pinned
                to the behaviour we decided on.
3. SYNTHETIC    tiny made-up snapshots for situations the real data doesn't contain.
Exit code 1 if anything fails.
"""
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


def main():
    kb = load()
    results = [check_paraphrases(kb, "A (tuned)", TUNED), check_paraphrases(kb, "B (fresh)", FRESH),
               check_review(kb), check_synthetic()]
    failed = 0
    for name, ok, total, bad in results:
        print(f"{name:24s} {ok}/{total}")
        for b in bad:
            print("   FAIL", b)
        failed += len(bad)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
