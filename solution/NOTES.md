# NOTES: a Dupaco knowledge system that knows what's true *now*

## Requirements

- Python 3.9+, **standard library only**. No API keys, no network calls, no LLM.
- Ingesting the 5 snapshots takes about 12 s. Answers take about 0.1 s at p95.

## Pipeline

| Step | File | What it does |
|---|---|---|
| 1 | `kb_pages.py` | Cleans each page. It strips inline image data, pop-ups, the country-code dropdown, sidebars of *other* articles and stat counters that never rendered ("# 0 Branches"). Classifies the page kind (rate sheet, product, document, news, landing, blog, calculator, listing, expired) and reads a news or blog post's publish date. Identical page versions are stored once, and each snapshot is a *view* of the site on that day. |
| 2a | `kb_chunks.py` | Cuts pages into paragraphs that remember their heading path, and those paragraphs into sentences. |
| 2b | `kb_rates.py` | Turns every rate-table row into a record: product (family, name, qualifiers such as jumbo, business, refinance, Roth), tier (term, balance or loan amount, model years), the numbers (dividend rate, APY, rate, APR), the minimum to open or to earn, and the **"Rates are effective as of" date** under the table. |
| 2c | `kb_rate_qa.py` | Answers rate questions from those records, never from raw text. |
| 3 | `kb_search.py` | Answers everything else by finding the sentence that holds the fact. |
| 7 | `kb_conflicts.py` | Lists the places where the site contradicts itself. |

## What counts as "current", in priority order

1. **Rate tables: the newest "effective as of" date wins.** A table with no date counts as the oldest.
2. **Then page trust:** rate sheet (1.0) > product page (0.9) > PDF document (0.7) > news (0.55) > campaign landing page (0.45) > blog (0.4) > calculator (0.3) > tag/listing page (0.1).
3. **Facts that only appear in news: the newest publish date wins.** A statement the site repeats on 3+ pages (press-release boilerplate) beats a one-off mention, and its newest copy answers. For example, "22 branch office locations" from the newest releases beats an old executive bio on /about that says "18 branches".
4. **Expired pages ("This Offer Has Expired") are never used.**
5. **Products compete as whole tables.** If the newest table no longer lists a tier, an older page that still lists it does not get to answer.
6. **Statistics labelled with a year are history, not contradictions.** The answer gives the newest year and the earlier years: "256 employees used VTO in 2024 (294 in 2023)".
7. **A page missing from a later download is still on the site.** Its newest earlier version stays in that day's view.

## Tiers are not conflicts

- Term, balance or loan-amount tier, and model year are different facts. Model-year ranges sharing at least two years are the same tier, so "2023-26" and "2024-27" both cover a 2025 car.
- Refinance and business products are shown only when asked. In "list everything" questions, business products appear under "Also", and business versions with identical rates collapse into one line.
- Jumbo and introductory rates are shown after the main rows.
- A question about a specific balance ("$250,000 mortgage") gets the narrowest tier that contains it.
- **Minimums are part of the fact.** A certificate row is shown with its minimum ("4.10% APY (minimum to earn $1,000.00)"). A balance below every matching row's minimum still gets the rate, but the answer starts by saying the amount doesn't qualify: "$500 is below the minimum to earn $1,000.00 ...".
- **Rate, APY and APR are different numbers.** "Does it pay 4.06% APY?" is checked against APYs only: "No: 4.06% is the dividend rate ..., not its APY; its APY is 4.10%." A range ("15.50% – 21.00% APR") counts if it contains the number.

## "As of" questions

- The answer comes from the latest snapshot taken on or before the date.
- A date written only in the question ("... as of May 2026?", "in June 2026", "on May 12, 2026") is used the same way when no `as_of` is passed. A month means its last day.
- A question about the change itself ("Has the 10-month jumbo rate changed?", "What was the previous 12-month rate?") gets the current rate, then "Before that (the website as of August 27, 2026): ...", taken from the newest earlier download whose numbers differ. Ordinary questions never show old numbers.
- For a date **before the first download (2026-05-12)**, the system still answers from the earliest copy, but:
  - News published after that date is ignored.
  - A plain note follows. For rates: "these rates took effect by X, before the date you asked about, so they applied then too", or "these rates took effect after that date, so I don't know what applied then".
- "Is X still open?" compares the closing date with the date asked. "Is X closed?" asks the opposite, so the same facts answer "Yes". A "when" question gets the date without a yes or no.

## When the system says "I don't know"

Only when the site truly does not know:

1. a name in the question appears nowhere on the site, or
2. the question asks for a specific kind of value (hours, address, phone number, date, count, link, amount, rate) and no text **about that subject** contains one. Subjects can be names, capitalised acronyms (also matched when spelled out: "VTO" = "Volunteer Time Off") or product kinds ("construction loan"). A rate must be printed like a rate ("6.25%", "5% APR"), so "adjust up to 2%" does not count, or
3. the question names a year, the site gives that figure year by year, but not for that year. "How many employees used VTO in 2022?" is declined instead of being answered with 2024's number.

A loan kind the rate tables don't list ("construction loan", "land mortgage", "FHA" or "VA mortgage") is never answered with the plain mortgage rows. The question goes to rule 2, so it is answered only if some text about that kind prints a rate.

Otherwise the system answers with what the site says. Refusals contain no numbers.

## How answers are built

- **Rates:** only the tiers asked for, plus the effective date and sources (the winning page first, then other pages printing the same numbers). `conflict_note` names the pages that still show out-of-date values.
- **Sources name the download that really contained the page.** A page carried forward from an earlier download (rule 7) is cited with that earlier download's id, so every source can be looked up.
- **Text answers cite every page that states the fact:** the answering page first, then other pages printing the same key values (the routing number, an amount, a time, a link), most trusted first, then site pages the answer itself links to.
- **Everything else:** sentences are scored on their own words (full weight), their section title (full weight), and their page title and neighbouring sentences (half weight). The search:
  - ignores question words that carry no topic ("now", "currently", "said", "about") and the words that only name the answer shape ("link", "url", "number of");
  - drops sentences without the needed answer shape, and halves calls to action ("For more information, visit ...");
  - picks the page by the rules above;
  - inside that page, picks the sentence holding the most and rarest question words;
  - answers with that sentence plus one or two after it, or its whole bullet list — never the whole page, because every extra sentence is a chance to repeat an old number.
- **Defined terms are expanded:** "[charter area](map.jpg)" gets the county list the site gives elsewhere.
- **Hours with no branch named:** the site gives hours per branch, so the answer lists the distinct schedules and asks which branch.

## conflicts()

- **Rates:** one conflict per precise fact (product + term + tier) that was printed with different numbers, either on two pages at once (a stale page still live, e.g. /homebuying-guidance 6.037% APR vs /rates 7.29% APR) or in different downloads (10-month jumbo certificate 3.90% → 4.00%).
  - Each value is tagged *current* or *outdated*, with its pages, effective date and snapshots.
  - The resolution follows the rules above, and the reason names the deciding date and the pages still showing old numbers.
  - The current table is chosen for the whole product, as answers do. If it no longer lists a term, every value for that term is outdated and the conflict has no resolution, matching the "I don't know" answer.
  - The same change printed on twin products (personal, business, Roth, Traditional) is merged into one conflict.
- **Text:** boilerplate repeated on 3+ pages whose numbers changed (branches 24 → 23 → 22; counties 108 → 112 → 118), one conflict per statement, plus running counts ("fourth" → "fifth time Forbes recognized Dupaco"). One-off yearly figures describe different years and are left out.
- **Page changes:** an undated page (product page, PDF) that changed a dollar figure between downloads: hardship grants "up to $2,000" → "$3,500" (two pages, one conflict), Rewards Visa minimum cash-back redemption $50.00 → $25.00. Calculators, rate-bearing paragraphs (payment examples) and sentences used twice on one page with different figures are skipped.
- The list is ordered most specific first. It has 36 conflicts on the provided snapshots.

## Known limitations

- Matching is lexical, with no embeddings, so unusual wording can miss. A few hand-written vocabularies (product families, member-word synonyms such as "become a member" = "join") are tuned to this site.
- Rates written as one strict "label metric: value" line ("6-month certificate APY: 3.50%") are parsed like a table row; a line saying the offer ended is skipped. Looser prose with a % is never turned into a rate record (the Dupaco pages have no such lines; the harness self-test does, and scores 1.0 including its conflict).
- Branch hours exist only in old branch-opening press releases.

## Results

On `eval/public_eval.jsonl`:

- **0.969**, with 0 stale-trap hits, consistency 1.0 and speed 1.0 (p95 under 0.1 s). Every question that names expected sources gets the source credit.
- The only miss is `dup-005`, which has no `must_include` and can't be scored without the LLM judge, so 0.969 is the most this file allows without it. (The answer does read back every certificate rate, as its reference answer asks.)
- The public file has no conflict gold, so this score doesn't measure `conflicts()`. Every paraphrase group in it has a single question, so its consistency score only tests asking the same question twice.

On `tests/sim_eval.jsonl`, a stand-in for the hidden set built by `tests/build_sim_eval.py` (284 questions, same format and scorer):

- every public question with five rewordings (plain and messy: lower case, abbreviations, chatty context) in its group;
- "as of" questions on rate-sheet rows that changed, expected values read off /rates in each download, with the date passed as `as_of` or written only in the question;
- current values of facts that changed, questions about the change itself, and extra refusals.
- **0.962** (accuracy 0.966, consistency 0.942). The three misses are open questions with no answer shape ("What has Forbes said about Dupaco?", "Does Dupaco support mobile wallets?", "VTO usage last year?").

`python tests/run_checks.py` covers what the public eval doesn't:

- **59 reworded questions** on the public topics. Set B (30) was written fresh and passed 27/30 on its first run; the three misses were then fixed, so it is no longer an untouched test.
- **21 review cases**: rate vs APY vs APR, minimums, loan kinds the tables don't list, yes/no polarity, missing years and source snapshot ids.
- **Synthetic snapshots** for cases the real data doesn't have: a term dropped from the newest table, a fee that changed.

## Developer tool

```
python solution/inspect_kb.py rates /rates                         # rate records parsed from a page
python solution/inspect_kb.py chunks contact                       # paragraphs and sentences of a page
python solution/inspect_kb.py ask "30 year mortgage rate" 2026-05-31   # answer + sources + conflict note
python solution/inspect_kb.py history /rates                       # how a page changed across snapshots
python tests/run_checks.py                                         # paraphrases, review cases, synthetic snapshots
python tests/build_sim_eval.py && python harness/run_eval.py --submission solution --eval tests/sim_eval.jsonl --out results/sim
python tests/show_misses.py results/sim tests/sim_eval.jsonl       # the questions a run got wrong
```
