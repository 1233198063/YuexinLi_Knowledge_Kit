# NOTES: a Dupaco knowledge system that knows what's true *now*

## Requirements

- Python 3.9+, **standard library only**. No API keys, no network calls, no LLM.
- Ingesting the 5 snapshots takes about 12 s. Answers take about 0.1 s at p95.

## Pipeline

| Step | File | What it does |
|---|---|---|
| 1 | `kb_pages.py` | Cleans each page. It strips inline image data, pop-ups, the country-code dropdown, sidebars of *other* articles and stat counters that never rendered ("# 0 Branches"). Classifies the page kind (rate sheet, product, document, news, landing, blog, calculator, listing, expired) and reads a news or blog post's publish date. Identical page versions are stored once, and each snapshot is a *view* of the site on that day. |
| 2a | `kb_chunks.py` | Cuts pages into paragraphs that remember their heading path, and those paragraphs into sentences. |
| 2b | `kb_rates.py` | Turns every rate-table row into a record: product (family, name, qualifiers such as jumbo, business, refinance, Roth), tier (term, balance or loan amount, model years), the numbers (dividend rate, APY, rate, APR) and the **"Rates are effective as of" date** under the table. |
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

## "As of" questions

- The answer comes from the latest snapshot taken on or before the date.
- For a date **before the first download (2026-05-12)**, the system still answers from the earliest copy, but:
  - News published after that date is ignored.
  - A plain note follows. For rates: "these rates took effect by X, before the date you asked about, so they applied then too", or "these rates took effect after that date, so I don't know what applied then".
- "Is X still open?" compares the closing date with the date asked.

## When the system says "I don't know"

Only when the site truly does not know:

1. a name in the question appears nowhere on the site, or
2. the question asks for a specific kind of value (hours, address, phone number, date, count, link, amount, rate) and no text **about that subject** contains one. Subjects can be names, capitalised acronyms (also matched when spelled out: "VTO" = "Volunteer Time Off") or product kinds ("construction loan"). A rate must be printed like a rate ("6.25%", "5% APR"), so "adjust up to 2%" does not count.

Otherwise the system answers with what the site says. Refusals contain no numbers.

## How answers are built

- **Rates:** only the tiers asked for, plus the effective date and sources (the winning page first, then other pages printing the same numbers). `conflict_note` names the pages that still show out-of-date values.
- **Everything else:** sentences are scored on their own words (full weight), their section title (full weight), and their page title and neighbouring sentences (half weight). The search:
  - drops sentences without the needed answer shape;
  - picks the page by the rules above;
  - inside that page, picks the sentence holding the most and rarest question words;
  - answers with that sentence plus one or two after it, or its whole bullet list — never the whole page, because every extra sentence is a chance to repeat an old number.
- **Defined terms are expanded:** "[charter area](map.jpg)" gets the county list the site gives elsewhere.
- **Hours with no branch named:** the site gives hours per branch, so the answer lists the distinct schedules and asks which branch.

## conflicts()

- **Rates:** one conflict per precise fact (product + term + tier) that was printed with different numbers, either on two pages at once (a stale page still live, e.g. /homebuying-guidance 6.037% APR vs /rates 7.29% APR) or in different downloads (10-month jumbo certificate 3.90% → 4.00%).
  - Each value is tagged *current* or *outdated*, with its pages, effective date and snapshots.
  - The resolution follows the rules above, and the reason names the deciding date and the pages still showing old numbers.
  - The same change printed on twin products (personal, business, Roth, Traditional) is merged into one conflict.
- **Text:** boilerplate repeated on 3+ pages whose numbers changed (branches 24 → 23 → 22; counties 108 → 112 → 118), one conflict per statement, plus running counts ("fourth" → "fifth time Forbes recognized Dupaco"). One-off yearly figures describe different years and are left out.
- The list is ordered most specific first. It has 34 conflicts on the provided snapshots.

## Known limitations

- Matching is lexical, with no embeddings, so unusual wording can miss. A few hand-written vocabularies (product families, member-word synonyms such as "become a member" = "join") are tuned to this site.
- Rates written as prose lines ("APY: 3.50%") are not parsed into rate records; the Dupaco pages contain none.
- Branch hours exist only in old branch-opening press releases.

## Results on `eval/public_eval.jsonl`

- **0.9574**, with 0 stale-trap hits, consistency 1.0 and speed 1.0.
- The only miss is `dup-005`, which has no `must_include` and can't be scored without the LLM judge.
- A fresh set of 30 reworded questions, not tuned on, passed 27/30 on its first run.

## Developer tool

```
python solution/inspect_kb.py rates /rates                         # rate records parsed from a page
python solution/inspect_kb.py chunks contact                       # paragraphs and sentences of a page
python solution/inspect_kb.py ask "30 year mortgage rate" 2026-05-31   # answer + sources + conflict note
python solution/inspect_kb.py history /rates                       # how a page changed across snapshots
```
