# Results: scores, question banks, performance, what went well and what didn't

The details behind the short [README](../README.md). How the agents were organised is in [PROCESS.md](PROCESS.md),
and how the system decides what is current in [../solution/NOTES.md](../solution/NOTES.md).

## 1. Scores

| layer | result |
|---|---|
| organizer public set, 40 questions | **0.969** total, which is the most this file allows without its LLM judge (`dup-005` has no `must_include`). Consistency 1.0, speed 1.0, 0 stale traps |
| organizer self-test, 5 questions + 1 conflict | 1.0 |
| fresh blind set, 172 questions, written last and run once per version | **0.828** total (accuracy 0.875, consistency 0.886, conflict F1 0.57). The tournament line's runtime alone scores 0.775 |
| our stand-in for the hidden set, 330 questions | 0.963 total (written by us, so optimistic) |
| eleven agent-written banks, development / blind half | see §2 |

Accuracy on the blind halves, which were never opened, from the first solution to now:

| blind bank | first solution | now |
|---|---:|---:|
| our independent author's holdout (176) | 0.642 | **0.785** |
| legacy509 holdout (176) | 0.189 | **0.628** |
| author C confirmation (36) | 0.266 | **0.569** |
| author A confirmation (60) | 0.502 | 0.584 |
| author B confirmation (42) | 0.170 | 0.300 |

## 2. Question banks used

| bank | written by | development / blind | what it tests |
|---|---|---:|---|
| organizer public, self-test | the kit | 40; 5 + 1 conflict | contract, basic facts, repeats |
| stand-in set | this repository | 330 | every public question reworded six ways, `as_of`, changed facts, refusals |
| ours | an independent author session with no access to the code | 226 / 176 | answers quoted from the snapshots; 23 conflict gold entries |
| km226 | tournament line | 226 | its tuning bank, with a 16-topic conflict proxy |
| legacy509 | tournament line, round-1 author | 333 / 176 | original corpus plus synthetic sites: prompt injection, expired offers, removed pages, published-vs-fetched dates |
| A | tournament line, round-2 author | 100 / 60 | qualifiers, thresholds, dated multi-part questions |
| B | tournament line, round-2 author | 30 / 42 | source conditions, negative mutations |
| C | tournament line, round-3 author | 36 / 36 | complete multi-part answers within one fact family |
| fresh set | a new author session at the end | 172 + conflict gold, all blind | the final claim; comparison registered before any run |
| mechanism suites | tournament line | 35 custody + 73 diagnostic | one rule each on invented pages |
| `tests/run_checks.py` | this repository | 254 | paraphrases, paired controls, review cases, synthetic snapshots, mutations, determinism |

The blind halves were run for aggregate scores only; nobody opened their questions, gold or answers. The fresh set
was enforced by `tests/fresh_once.py`, which logs each run and refuses a second run of the same code.

Development / blind accuracy now:

| ours | km226 | legacy509 | A | B | C |
|---|---|---|---|---|---|
| 0.874 / 0.785 | 0.744 / – | 0.865 / 0.628 | 0.817 / 0.584 | 0.542 / 0.300 | 0.941 / 0.569 |

## 3. How it performs on this problem

The scores below are by kind of question, on development banks and the stand-in set. Blind banks are reported only
as totals.

| kind of question | result | what made the difference |
|---|---|---|
| tiers and qualifiers (term, balance, model year, jumbo, business) | 0.97–0.99 on ours and legacy; 1.0 public | typed rate rows; only the asked tier |
| stale-value traps (a calculator or blog still shows the old rate) | 0 hits on public; 0.96–0.98 on ours and the stand-in set | effective dates, then page trust; never listing extra numbers |
| `as_of` questions | 1.0 public, 1.0 legacy, 0.85 ours | snapshot views; dates read from the question |
| refusals ("I don't know") | 1.0 on ours and public | decline only when the site doesn't say; no numbers in a refusal |
| prompt injection in page text (22 synthetic scenarios) | 1.0 | page text is data; rules never execute it |
| current value of text facts (counts, programs, statements) | 0.65 ours, 0.77 legacy | the weakest area: lexical matching misses far wordings |
| entity attribution (whose number is it) | 0.69 ours | text near the right number but about another entity |
| derived values (a figure computed from the page) | 0.19 legacy | the system doesn't compute, only quotes |
| negative mutations (a question that is false by one detail) | 0.38 B | a yes/no guard was tried and removed (it declined correct answers) |
| some synthetic snapshot policies | expired promo 0.05; published-vs-fetched 0.15; removed pages 0.48 | partly a policy choice: a page missing from one snapshot is carried forward, by the owner's decision |

## 4. What went well

- **Saying less.** Answering only the asked metric and tier lifted the blind legacy holdout from 0.18 to 0.55 in
  one change. This follows directly from how the scoring zeroes stale or extra values.
- **Typed rate rows with effective dates.** Tiers, qualifiers and stale traps are near-perfect, and every rate
  answer can be traced to a table, a date and a page.
- **Generalisation that was measured, not assumed.** Blind gains are real (ours-holdout +0.14, legacy-holdout
  +0.44, C-confirm +0.30). Rules derived from the scoring rule kept 82% or more of their development gain on blind
  banks.
- **Robustness.** Synthetic sites, prompt injection and odd dates don't break it. No exceptions across about
  1,400 bank items. The same question always gets the same answer.
- **Combining the two lines by evidence.** The tournament line's runtime was merged handler by handler. The merged
  system beat that runtime alone on a set neither had seen (0.819 against 0.775 before the final step).
- **Discipline.** Blind banks were used once, as a final gate. The fresh-set comparison was registered in advance,
  and rejected iterations are recorded alongside adopted ones ([ITERATIONS.md](ITERATIONS.md)).

## 5. What didn't go well

- **Complete multi-part answers.** C confirmation is 0.57 here against 0.78 for the tournament line's runtime alone. Text facts
  worded far from the page still miss, because matching is lexical (no embeddings).
- **The last refinement.** Restricting the merged runtime's broad modules was tuned on banks this system had already
  fitted, and it cost about two of 172 fresh questions (0.836 → 0.828). The lesson recorded: judge a merge on data
  neither system was tuned on.
- **Item-driven fixes transferred poorly** (3% to 33% of their development gain). One session used blind
  aggregates to locate a regression, which is why the stricter gate was adopted afterwards.
- **Conflict recall** is low on unseen gold: F1 0.16 on the holdout's conflicts, against 0.57 on development and
  the fresh set. Branch-status and policy-text contradictions aren't detected.
- **Bugs that only reviewers found.** 240 of the builder's own checks passed, yet the last review found seven
  combination bugs. All seven are fixed, with tests proven to fail on the old code; more surely remain.
- **One blind bank never moved.** A confirmation stayed at 0.58. Its weak spots are unknown, by the blind rule.
