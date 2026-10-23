# NOTES: a Dupaco knowledge system that knows what's true *now*

## Requirements

- Python 3.9+ (tested on 3.11), **standard library only**. No API keys, no network calls, no LLM.
- `answer()` accepts `as_of` as an ISO date or datetime, "2026-05", "May 2026" or "05/31/2026"; an unreadable date means the latest download. An unexpected error is answered with "I don't know" instead of crashing.
- Ingesting the 5 snapshots takes about 18 s, including the merged companion runtime. Answers take 0.09 s at p95
  (0.1 s max) on the public file.
- An impossible date ("2035-02-31", "February 30, 2035") is declined instead of silently answering from the latest download.

## Pipeline

| Step | File | What it does |
|---|---|---|
| 1 | `kb_pages.py` | Cleans each page. It strips inline image data, pop-ups, the country-code dropdown, sidebars of *other* articles and stat counters that never rendered ("# 0 Branches"). Classifies the page kind (rate sheet, product, document, news, landing, blog, calculator, listing, expired) and reads a news or blog post's publish date. Identical page versions are stored once, and each snapshot is a *view* of the site on that day. |
| 2a | `kb_chunks.py` | Cuts pages into paragraphs that remember their heading path, and those paragraphs into sentences. |
| 2b | `kb_rates.py` | Turns every rate-table row into a record: product (family, name, qualifiers such as jumbo, business, refinance, Roth), tier (term, balance or loan amount, model years), the numbers (dividend rate, APY, rate, APR), the minimum to open or to earn, and the **"Rates are effective as of" date** under the table. |
| 2c | `kb_rate_qa.py` | Answers rate questions from those records, never from raw text. |
| 3 | `kb_search.py` | Answers everything else by finding the sentence that holds the fact. |
| 7 | `kb_conflicts.py` | Lists the places where the site contradicts itself. |
| 8 | `kb_companion.py` + `companion/` | The owner's second build of this assessment, merged unchanged. It answers only text questions that one of its eight specialist handlers takes: membership routes and links, mobile wallets, contact routes, the privacy policy's correction procedure, card offers, the card list, rates the site doesn't publish, homebuyer grants. Each was measured better than this system on dev banks outside the companion's own tuning bank. Any error in it disables it. |

## What counts as "current", in priority order

1. **Rate tables: the newest "effective as of" date wins.** A table with no date counts as the oldest. A table that takes effect after the download date waits; if it is the only one, that day's rate is unknown. The date is read in any common wording ("Rates are effective as of 09/01/2026", "Effective January 8, 2036"), for one-line rate statements from the line nearest them.
2. **Then page trust:** rate sheet (1.0) > product page (0.9) > PDF document (0.7) > news (0.55) > campaign landing page (0.45) > blog (0.4) > calculator (0.3) > tag/listing page (0.1). **Then the product's own page** over a copy of its table embedded in another product's page (the auto table on the checking page). Equally dated, equally trusted pages that still disagree get no invented winner: both values are shown with a note, and the conflict has no resolution.
3. **Facts that only appear in news: the newest publish date wins.** A statement the site repeats on 3+ pages (press-release boilerplate) beats a one-off mention, and its newest copy answers. For example, "22 branch office locations" from the newest releases beats an old executive bio on /about that says "18 branches". Boilerplate also gets reworded over the years; when a reworded repeated statement about the same thing has newer copies, the newer wording wins ("membership totals more than 141,000 with assets exceeding $2.6 billion" → "has grown to more than 179,000 with assets exceeding $3.6 billion").
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

## Only what was asked, but all of it

- **The asked metric only.** "What APY ...?" gets the APY, not the dividend rate printed beside it; "rate and APR" gets both. Metrics, qualifiers and products named after "not / except / other than / keeping ... separate" are left out.
- **The asked tier and product only.** "Personal and business cards", "regular and jumbo specials", "each balance tier and the top tier's threshold" list exactly those. A named product beats a bare family word ("money-market yields were given for Share Savings" is about Share Savings).
- **Every asked part.** A question with several parts is split when the parts want different kinds of answer (a rate and a date). A text answer that leaves asked words uncovered adds up to two sentences that hold them, from its own section; another section of the same page only for a sentence holding two missing parts (a neighbouring branch or product is never borrowed). A rate question that also asks timing or conditions ("the posting window", "the expiry") adds the offer's own sentence.
- **"Was X listed?"** is answered "No. It was not listed ... Listed then: ..."; "does Dupaco offer X?" is declined when no table lists it (a table without it doesn't prove there is none).
- "A transfer posts on day 38: does it qualify?" against "during the first 37 days" starts with "No."

## "As of" questions

- The answer comes from the latest snapshot taken on or before the date.
- A date written only in the question ("... as of May 2026?", "in June 2026", "on May 12, 2026") is used the same way when no `as_of` is passed. A month means its last day.
- A question about the change itself ("Has the 10-month jumbo rate changed?", "What was the previous 12-month rate?") gets the current rate, then "Before that (the website as of August 27, 2026): ...", taken from the newest earlier download whose numbers differ. The same works for other facts ("Has the hardship grant amount changed?" → $3,500, before that $2,000), triggered only by "changed", "previously", "used to", "increased" and the like, so "How do I change my address?" is not affected. Ordinary questions never show old numbers.
- For a date **before the first download (2026-05-12)**, the system still answers from the earliest copy, but:
  - News published after that date is ignored.
  - A plain note follows. For rates: "these rates took effect by X, before the date you asked about, so they applied then too", or "these rates took effect after that date, so I don't know what applied then".
- **Several days named side by side** ("the 60-month APR at the August 27 and September 28 crawls") are each answered as the site stood that day, labelled, equal answers said once; "how did it change from January to May" also gets every download in between. Parts of a question with their own dates ("As of January 10 ...; and as of May 10 ...") use their own dates when no `as_of` is passed. Dates are read in most wordings ("10 March 2035", "Mar. 10", "mid-March", "the August-27 snapshot"); a slash date is a table's own date, not a day to answer.
- "Is X still open?" compares the closing date with the date asked. "Is X closed?" asks the opposite, so the same facts answer "Yes". A "when" question gets the date without a yes or no.

## When the system says "I don't know"

Only when the site truly does not know:

1. a name in the question appears nowhere on the site, or
2. the question asks for a specific kind of value (hours, address, phone number, date, count, link, amount, rate) and no text **about that subject** contains one. Subjects can be names, capitalised acronyms (also matched when spelled out: "VTO" = "Volunteer Time Off") or product kinds ("construction loan"). A rate must be printed like a rate ("6.25%", "5% APR"), so "adjust up to 2%" does not count, or
3. the question names a year, the site gives that figure year by year, but not for that year. "How many employees used VTO in 2022?" is declined instead of being answered with 2024's number.

A loan kind the rate tables don't list ("construction loan", "land mortgage", "FHA" or "VA mortgage") is never answered with the plain mortgage rows. The question goes to rule 2, so it is answered only if some text about that kind prints a rate.

A product the question names in capitals is answered only from rows of that product in the current tables. "Mortgage Rate Relief Program" was on /rates until June 2026; now only the never-updated /homebuying-guidance page lists it, so the latest answer is "the current rate tables no longer list it" (rule 5), while an "as of June 1, 2026" question gets 5.125%.

A fee must be the fee asked about: the answer sentence has to mention the question's most specific word ("lost debit card REPLACEMENT", "CASHIER'S check"). The site lists neither of those two fees, so both are declined instead of being answered with some other debit-card fee.

Also declined: the asker's own account state ("has my identity been verified?", "what is my balance?"); whether something is open now when the page says the next cycle "will be announced"; a rate whose only table had not taken effect yet.

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
- The list is ordered most specific first. It has 36 conflicts on the provided snapshots. Rates are compared as numbers, so "20.5%" and "20.50%" are the same value, not a conflict.

## Known limitations

- Matching is lexical, with no embeddings, so unusual wording can miss. A few hand-written vocabularies (product families, member-word synonyms such as "become a member" = "join") are tuned to this site.
- Rates written as one strict "label metric: value" line ("6-month certificate APY: 3.50%") are parsed like a table row; a line saying the offer ended is skipped. Looser prose with a % is never turned into a rate record (the Dupaco pages have no such lines; the harness self-test does, and scores 1.0 including its conflict).
- Branch hours exist only in old branch-opening press releases.

## Results

| layer | score |
|---|---|
| `eval/public_eval.jsonl` | **0.969** total, 0 stale-trap hits, consistency 1.0, speed 1.0. The only miss, `dup-005`, has no `must_include` and can't be scored without the LLM judge, so 0.969 is the most this file allows. |
| harness self-test (5 questions + 1 conflict) | 1.0 |
| `tests/sim_eval.jsonl`, our 330-question stand-in for the hidden set | 0.9628 total (accuracy 0.969, consistency 0.963) |
| `tests/run_checks.py` | 221/221 |

The stand-in set holds every public question with six rewordings, "as of" questions on rate rows that changed, current values of changed facts, change questions and refusals.

`tests/run_checks.py` covers:

| suite | count |
|---|---|
| paraphrases (set A tuned on; set B written fresh) | 59 |
| paired controls: each rule learned from a bank, in words no bank uses, in an equivalent and a minimally changed form | 55 |
| review cases | 33 |
| synthetic snapshots | 4 |
| mutations (one rule, one changed input) | 11 |
| determinism across two hash seeds | 59 |

On **eleven agent-written banks** from four authors (about 1,400 items; organizer harness unchanged; holdout and confirmation banks run for aggregates only and never opened):

| bank | dev | blind |
|---|---:|---:|
| our independent author (226 / 176) | 0.867 | 0.761 |
| companion repository, km226 | 0.675 | - |
| legacy509 (333 / 176) | 0.800 | 0.577 |
| author A (100 / 60) | 0.817 | 0.580 |
| author B (30 / 42) | 0.537 | 0.300 |
| author C (36 / 36) | 0.941 | 0.478 |

The companion repository's Parent45e1 mechanism suites (35 tests on made-up banks) pass 31. The four misses:

- two policy differences, both kept here by the owner's decision: a true tie, and a date before the first
  download. Both are switches, `KB_TIE=decline` and `KB_BEFORE_FIRST=decline`; with both on, 33 pass;
- one wording requirement;
- one semantic gap.

How these numbers moved commit by commit, what was tried and rejected, a same-bank comparison with the companion system, the method, and what transfers to unseen questions are in `docs/ITERATIONS.md`, `docs/REPORT.md`, `docs/METHODOLOGY.md` and `docs/GENERALIZATION.md`.

## Developer tool

```
python solution/inspect_kb.py rates /rates                         # rate records parsed from a page
python solution/inspect_kb.py chunks contact                       # paragraphs and sentences of a page
python solution/inspect_kb.py ask "30 year mortgage rate" 2026-05-31   # answer + sources + conflict note
python solution/inspect_kb.py history /rates                       # how a page changed across snapshots
python tests/run_checks.py                                         # paraphrases, controls, review cases, synthetic, mutations, determinism
python tests/banks.py --blind                                      # every agent-written bank (blind ones: aggregates only)
python tests/scoreboard.py --label now                             # every layer in one table
python tests/build_sim_eval.py && python harness/run_eval.py --submission solution --eval tests/sim_eval.jsonl --out results/sim
python tests/show_misses.py results/sim tests/sim_eval.jsonl       # the questions a run got wrong
```
