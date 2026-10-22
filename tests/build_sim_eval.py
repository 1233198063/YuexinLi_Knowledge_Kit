"""
Writes tests/sim_eval.jsonl: a stand-in for the hidden question set, in the harness's own format.

    python tests/build_sim_eval.py
    python harness/run_eval.py --submission solution --eval tests/sim_eval.jsonl --out results/sim

The organisers say the hidden set has (1) reworded versions of the public questions, (2) "as of" date
questions and (3) questions about things that changed between downloads. So:
  * every public question with three rewordings, all in the public question's group (consistency is
    scored per group), keeping its must_include / must_not_include;
  * "as of" questions on rate-sheet rows that changed between downloads, the expected value read
    straight off /rates in that download (old values are the traps), with the date passed as as_of,
    written into the question only, or both;
  * current-value questions on facts that changed (the older value is the trap) and more refusals.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFUSE = "should_refuse"

# public id -> three rewordings
REWORDS = {
    "dup-001": ["How much does the 17 month certificate special earn?", "17-month CD special APY?",
                "What's the yield on your 17-month fixed certificate special?"],
    "dup-009": ["What's the current rate on a 30 year fixed mortgage?", "How much interest is charged on a thirty-year home loan?",
                "30-year fixed mortgage rates at Dupaco?"],
    "dup-011": ["What are today's home loan rates?", "Current mortgage rates please",
                "What mortgage rates is Dupaco offering right now?"],
    "dup-016": ["APR on a 60 month car loan for a 2025 vehicle?", "If I finance a 2025 car over 5 years, what's the APR?",
                "What rate would I get on a 60-month auto loan for a 2025 model year car?"],
    "dup-034": ["Which credit cards does Dupaco have, and what APRs do they charge?", "List your credit cards with their interest rates.",
                "What are all of your Visa credit cards and their APRs?"],
    "dup-045": ["What's the dividend rate on a Share Savings balance of $15,000?",
                "If I keep $12,000 in Share Savings, what dividend rate do I get?",
                "Share Savings dividend rate for the $10,000 to $24,999.99 tier?"],
    "dup-054": ["What's the routing number for Dupaco?", "Dupaco ABA routing number?",
                "I need Dupaco's routing number for direct deposit."],
    "dup-064": ["What hours are Dupaco lobbies open?", "When are your branch lobbies open?",
                "What are the normal lobby hours at Dupaco branches?"],
    "dup-066": ["When is the drive-up open?", "What time does the drive-thru open and close?",
                "What are your drive-up window hours?"],
    "dup-068": ["Where is the Galena branch located?", "What's the street address of Dupaco's Galena office?",
                "Galena branch address?"],
    "dup-073": ["How many branch locations does Dupaco have?", "How many branches does Dupaco operate now?",
                "What's the number of Dupaco branch offices?"],
    "dup-075": ["Is the Hy-Vee branch still operating in October 2026?", "Can I still bank at the Hy-Vee branch today (October 2026)?",
                "Is Dupaco's Hy-Vee location still open now, in October 2026?"],
    "dup-087": ["How many times has Forbes recognized Dupaco?", "Has Forbes ever named Dupaco a top credit union?",
                "What has Forbes said about Dupaco?"],
    "dup-008": ["Where on the website can I find certificate rates?", "What page shows Dupaco's CD rates?",
                "Give me the link to your certificate rates."],
    "dup-052": ["What interest do your checking accounts pay?", "What are the checking account rates?",
                "How much does 1st Rate Checking earn?"],
    "dup-035": ["What's the regular APR on the Platinum Visa?", "Platinum Visa standard purchase APR?",
                "What interest rate does the Dupaco Platinum Visa card charge on purchases?"],
    "dup-145": ["What's the rate on a 7/1 ARM?", "Do you have a 7/1 adjustable rate mortgage rate?",
                "How much is a 7-1 adjustable-rate home loan?"],
    "dup-065": ["When are your lobbies open?", "What hours is the lobby open?", "Lobby hours?"],
    "dup-074": ["When is the Hy-Vee branch closing?", "What date did the Hy-Vee branch close?",
                "On what date does Dupaco's Hy-Vee location close?"],
    "dup-050": ["What APY does Bright Savings pay?", "How much does the Bright Savings account earn?",
                "Bright Savings interest rate?"],
    "dup-040": ["What are your credit card rates?", "Tell me the APRs on Dupaco credit cards.",
                "Credit card interest rates please"],
    "dup-080": ["Where can I find a Dupaco branch or ATM online?", "What's the link to the branch locator?",
                "Which web page lists your branches and ATMs?"],
    "dup-049": ["Is there any savings tier paying 0.35% APY?", "Does any Share Savings balance tier earn 0.35%?",
                "Can I get 0.35% APY on a savings account?"],
    "dup-031": ["What is Home$tart?", "Tell me about the Home$tart down payment program.",
                "How does Dupaco's Home$tart grant work?"],
    "dup-028": ["36-month personal loan APR?", "What rate is a 3-year personal loan?",
                "How much is the APR on a personal loan for 36 months?"],
    "dup-147": ["What's the rate on a construction loan?", "Construction loan interest rate?",
                "How much interest do you charge for a home construction loan?"],
    "dup-076": ["Which branches should former Hy-Vee branch members use?", "Where should Hy-Vee branch members bank now?",
                "After the Hy-Vee branch closed, which branches serve its members?"],
    "dup-006": ["What did the 10-month jumbo certificate special pay in May 2026?",
                "As of May 2026, what was the APY on the 10-month fixed jumbo special?",
                "10-month jumbo special certificate rate as of May 2026?"],
    "dup-055": ["What's that routing number again?", "Tell me the routing number once more.", "Routing number please"],
    "dup-005": ["What are your certificate rates?", "Give me all of the certificate rates.", "CD rates?"],
    "dup-017": ["APR on an 84 month auto loan for a 2024 car?", "If I finance a 2024 vehicle for 7 years, what's the APR?",
                "What rate would I get on an 84-month auto loan for a 2024 model year vehicle?"],
    "dup-081": ["Who can join Dupaco?", "Who can become a member of Dupaco?", "What are Dupaco's membership eligibility rules?"],
    "dup-060": ["How do I change my address with Dupaco?", "How can I update my phone number on my account?",
                "Who do I contact to update my contact info?"],
    "dup-046": ["What's the best Share Savings APY?", "What is the top rate on Share Savings?",
                "Highest APY you pay on a Share Savings account?"],
    "dup-102": ["What are the hours at the Mullan Avenue branch?", "When is the Mullan Ave branch lobby open?",
                "Mullan Avenue branch lobby hours?"],
    "dup-104": ["Are lobby hours the same at every branch?", "Do lobby hours differ between Dupaco branches?",
                "Is every Dupaco branch open the same hours?"],
    "dup-088": ["How many employees used VTO last year?", "Last year, how many Dupaco employees took Volunteer Time Off?",
                "How many staff used volunteer time off last year?"],
    "dup-101": ["Do you offer student loans?", "What loan options do you have for college students?",
                "Can I get a student loan from Dupaco?"],
    "dup-094": ["Which mobile wallets work with Dupaco cards?", "Can I use Apple Pay, Google Pay or Samsung Pay with my Dupaco card?",
                "Does Dupaco support mobile wallets?"],
    "dup-082": ["Can I join Dupaco online?", "Where do I apply for membership online?", "How do I become a member online?"],
}

# a second, messier batch: lower case, abbreviations, chatty context, two-part questions
REWORDS2 = {
    "dup-001": ["hey whats the apy on the 17 mo special cd", "I have $5,000 for the 17-month certificate special. What APY would I get?"],
    "dup-009": ["thinking about buying a house, what's the 30yr mortgage rate", "30 yr fixed mortgage rate?"],
    "dup-011": ["mortgage rates?", "What are you charging for home loans these days?"],
    "dup-016": ["2025 car, 60 months: what APR?", "auto loan rate for a 2025 model, 60 mo term"],
    "dup-034": ["what credit cards can I get and what are the rates", "Do you have credit cards? What APRs?"],
    "dup-045": ["dividend on share savings if I have 20k", "Share Savings dividend rate for a $10k balance"],
    "dup-054": ["routing #?", "what's dupaco's routing and transit number"],
    "dup-064": ["what time do branch lobbies open", "What are the lobby hours on weekdays?"],
    "dup-066": ["drive thru hours", "When does the drive-up close on weekdays?"],
    "dup-068": ["galena branch address", "How do I get to the Galena branch? What's the address?"],
    "dup-073": ["how many locations do you have", "Number of branches?"],
    "dup-075": ["Is the Hy-Vee branch in Dubuque still open as of October 2026?", "Can I still visit the Hy-Vee branch?"],
    "dup-087": ["Is Dupaco recognized by Forbes?", "forbes recognition dupaco"],
    "dup-008": ["where are the CD rates on your site", "url for certificate rates"],
    "dup-052": ["checking account interest rate?", "Does checking earn interest? How much?"],
    "dup-035": ["platinum visa apr", "What's the normal purchase APR on the Platinum Visa, not the intro rate?"],
    "dup-145": ["7/1 arm rate?", "rate for a seven-year ARM mortgage"],
    "dup-065": ["what are the lobby hours", "When can I visit a branch lobby?"],
    "dup-074": ["hy-vee branch closing date", "When will the Hy-Vee branch be closed?"],
    "dup-050": ["bright savings apy", "What's the rate on Bright Savings?"],
    "dup-040": ["credit card rates", "What APR do your credit cards have?"],
    "dup-080": ["branch locator url", "Where on the website can I look up branch and ATM locations?"],
    "dup-049": ["any savings tier at 0.35%?", "Do you pay 0.35% APY on savings?"],
    "dup-031": ["what is home$tart", "Home$tart program details"],
    "dup-028": ["personal loan rate 36 months", "APR for a three-year personal loan?"],
    "dup-147": ["construction loan rates", "Do you have a rate for construction loans?"],
    "dup-076": ["The Hy-Vee branch closed, where do I go now?", "Which branches replaced the Hy-Vee branch?"],
    "dup-006": ["In May 2026 what did the 10 month jumbo special pay?", "10-month jumbo CD special APY as of May 2026"],
    "dup-055": ["routing number?", "Sorry, what was the routing number?"],
    "dup-005": ["certificate rates", "What do your certificates pay?"],
    "dup-017": ["84 month auto loan 2024 car apr", "APR for a 7-year loan on a 2024 vehicle"],
    "dup-081": ["who's eligible for membership", "Can anyone join Dupaco?"],
    "dup-060": ["update my phone number", "I moved. How do I change my address with you?"],
    "dup-046": ["max share savings apy", "What's the highest rate Share Savings pays?"],
    "dup-102": ["Mullan Ave branch hours", "Is the Mullan Avenue branch open on Saturdays?"],
    "dup-104": ["Same lobby hours at all branches?", "Do lobby hours vary from branch to branch?"],
    "dup-088": ["VTO usage last year?", "How many people at Dupaco used Volunteer Time Off last year?"],
    "dup-101": ["student loans?", "Can I borrow money for college from Dupaco?"],
    "dup-094": ["Which mobile wallets can I add my Dupaco debit card to?", "Can I put my Dupaco card in Apple Pay, Google Pay or Samsung Pay?"],
    "dup-082": ["join online?", "Is there a website to apply for membership?"],
}

# "as of" questions on rate-sheet rows that changed: (question, as_of, must_include, must_not_include)
AS_OF = [
    ("What was the 10-month fixed jumbo special certificate APY?", "2026-05-15", ["3.90%"], ["4.00%"]),
    ("What was the 10-month fixed jumbo special certificate APY?", "2026-08-30", ["3.90%"], ["4.00%"]),
    ("What is the 10-month fixed jumbo special certificate APY?", None, ["4.00%"], ["3.90%"]),
    ("What was the APY on the 17-month certificate special?", "2026-06-15", ["3.85%"], ["4.10%"]),   # 3.95% = that day's jumbo
    ("What was the APY on the 17-month certificate special?", "2026-09-01", ["3.95%"], ["4.10%", "3.85%"]),
    ("What did a 12-month certificate pay?", "2026-05-20", ["2.90%"], ["3.40%"]),
    ("What does a 12-month certificate pay?", None, ["3.40%"], ["2.90%"]),
    ("What APY did 1st Rate Checking pay on a $10,000 balance?", "2026-05-20", ["3.00%"], ["2.50%"]),
    ("What APY does 1st Rate Checking pay on a $10,000 balance?", None, ["2.50%"], ["3.00%"]),
    ("What was the 30-year fixed mortgage rate for a $100,000 loan?", "2026-05-12", ["5.875%"], ["7.13%", "6.250%"]),
    ("What was the 30-year fixed mortgage rate for a $100,000 loan?", "2026-05-25", ["6.250%"], ["7.13%", "5.875%"]),
    ("What was the 30-year fixed mortgage rate for a $100,000 loan?", "2026-06-30", ["6.125%"], ["7.13%", "6.250%"]),
    ("What was the 30-year fixed mortgage rate for a $100,000 loan?", "2026-09-01", ["6.375%"], ["7.13%", "6.125%"]),
    ("What was the 15-year fixed mortgage rate?", "2026-05-12", ["5.625%"], ["6.75%"]),
    ("What was the 15-year fixed mortgage rate?", "2026-06-20", ["5.875%"], ["6.75%", "5.625%"]),
    ("What was the APR on a 60-month auto loan for a 2025 vehicle?", "2026-06-01", ["5.19%"], ["5.39%", "5.34%"]),
    ("What was the APR on an 84-month auto loan for a 2024 vehicle?", "2026-07-01", ["5.39%"], ["5.59%", "5.54%"]),
    ("What was the APY on the 25-month certificate special?", "2026-05-20", ["3.60%"], []),
]
# the same date written only in the question (as_of not passed)
IN_TEXT = [
    ("What was the 12-month certificate APY in May 2026?", ["2.90%"], ["3.40%"]),
    ("What was the 30-year mortgage rate for a $100,000 loan as of May 12, 2026?", ["5.875%"], ["7.13%"]),
    ("What did 1st Rate Checking pay on $10,000 in May 2026?", ["3.00%"], ["2.50%"]),
    ("What was the 17-month certificate special APY in June 2026?", ["3.85%"], ["4.10%"]),
    ("What was the APR on a 60-month auto loan for a 2025 car in June 2026?", ["5.19%"], ["5.39%"]),
]
# current values of facts that changed (older value = trap), and refusals
CURRENT = [
    ("How many branch offices does Dupaco have today?", ["22"], ["24 branch", "23 branch"]),
    ("What is the maximum hardship grant from the Dupaco Foundation?", ["$3,500"], ["$2,000"]),
    ("What's the minimum cash back redemption on the Rewards Visa?", ["$25.00"], ["$50.00"]),
    ("What is the 10-month certificate special APY?", ["3.90%"], ["3.80%"]),
    ("What does the 17-month jumbo certificate special pay?", ["4.20%"], ["4.05%", "3.95%"]),
    ("What's the APR on a 72-month auto loan for a 2026 vehicle?", ["5.49%"], ["5.29%"]),
    ("What is the 20-year fixed mortgage rate?", ["7.13%"], ["6.250%", "6.375%"]),
    ("What is the HELOC rate?", ["6.25%"], []),
    ("What's the APY on a $500,000 High-Yield Savings balance?", ["2.25%"], []),
]
# questions about the change itself: the current value first, then the previous one, labelled as past
CHANGED = [
    ("Has the 10-month jumbo certificate special rate changed?", ["4.00%", "3.90%"], []),
    ("What was the previous 12-month certificate rate?", ["2.90%"], []),
    ("Did the 30-year fixed mortgage rate for a $100,000 loan go up recently?", ["7.13%", "6.375%"], []),
    ("Has the Bright Savings APY changed?", ["2.25%"], []),
]
REFUSALS = [
    "What is the rate on a 10/1 ARM?", "What's the APY on a 9-month certificate?", "What is the rate on a 60-month jumbo certificate?",
    "What's the rate on a land loan?", "What is the VA mortgage rate?", "What is the rate on an FHA loan?",
    "What are the lobby hours at the Springfield branch?", "What is the interest rate on a reverse mortgage?",
]


def main():
    public = [json.loads(l) for l in (ROOT / "eval/public_eval.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for p in public:
        out.append(dict(p, group=p["id"]))
        for k, q in enumerate(REWORDS[p["id"]] + REWORDS2[p["id"]], 1):
            out.append(dict(p, id=f"{p['id']}-r{k}", question=q, group=p["id"], expected_sources=p["expected_sources"]))
    for k, (q, as_of, must, must_not) in enumerate(AS_OF, 1):
        out.append({"id": f"asof-{k:02d}", "question": q, "as_of": as_of, "expected_answer": " / ".join(must),
                    "must_include": must, "must_not_include": must_not, "category": "temporal_as_of", "weight": 2.0})
    for k, (q, must, must_not) in enumerate(IN_TEXT, 1):
        out.append({"id": f"intext-{k:02d}", "question": q, "as_of": None, "expected_answer": " / ".join(must),
                    "must_include": must, "must_not_include": must_not, "category": "temporal_as_of", "weight": 2.0})
    for k, (q, must, must_not) in enumerate(CURRENT, 1):
        out.append({"id": f"now-{k:02d}", "question": q, "as_of": None, "expected_answer": " / ".join(must),
                    "must_include": must, "must_not_include": must_not, "category": "stale_trap", "weight": 2.0})
    for k, (q, must, must_not) in enumerate(CHANGED, 1):
        out.append({"id": f"changed-{k:02d}", "question": q, "as_of": None, "expected_answer": " / ".join(must),
                    "must_include": must, "must_not_include": must_not, "category": "temporal_as_of", "weight": 2.0})
    for k, q in enumerate(REFUSALS, 1):
        out.append({"id": f"refuse-{k:02d}", "question": q, "as_of": None, "expected_answer": "Not published; decline.",
                    "must_include": [], "must_not_include": [], "category": REFUSE, "weight": 2.0})
    path = ROOT / "tests/sim_eval.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in out) + "\n", encoding="utf-8")
    print(f"wrote {len(out)} questions to {path}")


if __name__ == "__main__":
    main()
