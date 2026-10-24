# Report: a temporal knowledge system for the Dupaco site, and what two independent builds of it taught

This report merges three earlier write-ups: the independent-test results, the study of the companion repository,
and the bank results. It is written for reviewers of this assessment. How I organised the agents and the decisions I made are in
[PROCESS.md](PROCESS.md). Iteration details are in
[ITERATIONS.md](ITERATIONS.md), the process in [METHODOLOGY.md](METHODOLOGY.md), the overfitting study in
[GENERALIZATION.md](GENERALIZATION.md), and the system's rules in [../solution/NOTES.md](../solution/NOTES.md).

## 1. Summary

- **This system:** standard-library Python, no model, no network. It merges the companion's final runtime
  unchanged: eight specialist handlers replace its answer, and the companion's broad modules compete with it on
  how much of the question each answer covers (§6).
  - Public 0.969, which is the file's ceiling without its LLM judge, with 0 stale-trap hits.
  - Harness self-test 1.0.
  - Answer p95 0.08 s; ingest 18 s; 28 conflicts listed.
- **Independent banks.** Eleven agent-written question banks from four authors and two processes, about 1,400
  items. Accuracy now, against the first solution:

  | bank | first solution → now |
  |---|---|
  | our own independent holdout (blind) | 0.642 → **0.785** |
  | legacy holdout (blind) | 0.189 → **0.628** |
  | C confirmation (blind) | 0.266 → **0.569** |
  | B confirmation (blind) | 0.170 → **0.300** |
  | A confirmation (blind) | 0.502 → **0.584** |
  | development banks | gains of +0.10 (A) to +0.53 (C) each |

- **A fresh blind set, written last** (172 questions, pre-registered, one run per version; §5.3).
  - The merged system scored 0.819 total, against 0.751 at the start of the session and 0.775 for the companion
    alone.
  - Adding the companion's broad modules raised it to 0.836. The final version, refined afterwards on dev banks
    only, scored 0.828: about two questions below that.
- **Against the companion system** on the same banks with the same harness, each system is stronger on the banks
  its own process tuned on.
  - The fairest blind comparison is a mixed picture. Before the merge, we led on our own holdout (0.750 against
    0.686) and it led clearly on C confirmation (0.778 against 0.349).
  - The gaps pointed at specific mechanisms (§5). Taking its winning mechanisms and handlers closed part of the
    C gap: our C confirmation is now 0.569.
- **The companion repository closed on 2026-10-23** with its runtime `2d6b8d6e` still selected. Its last
  candidate failed its own developer gate and lowered public to 0.930, so it was rejected (§6.1).
- **Method.** The most valuable things taken from the companion repository were process:
  - independent test authors with blind holdouts;
  - mechanism suites on made-up data;
  - an anti-overfit gate with paired controls;
  - rejecting changes that raise one score while adding a wrong claim.

  After that came a merge chosen by out-of-sample evidence, handler by handler. Scorer-derived rules and
  evidence-chosen merges carried 82% or more of their dev gain over to the blind banks; fixes driven by single
  items carried 3% to 33% ([GENERALIZATION.md](GENERALIZATION.md)).

## 2. The task and how it is scored

The system ingests five dated snapshots of dupaco.com (May 12 to September 28, 2026) and answers
`answer(question, as_of)` with the value current on that date. It also lists `conflicts()` where the site
contradicts itself.

The organizer's score has four parts:

| part | weight | how it works |
|---|---:|---|
| Accuracy | 55% | **Any** old or wrong value zeroes a question, even when the right value is present, so listing every number doesn't pay. The right source earns extra. "I don't know" scores only when the site doesn't say. |
| Conflicts | 15% | 0.7 × F1 + 0.3 × right winner |
| Consistency | 15% | rewordings and repeats give the same answer; multiplied by accuracy |
| Speed | 15% | full marks at p95 ≤ 2 s; multiplied by accuracy |

The hidden set consists of reworded public questions, `as_of` questions, and facts that changed between
snapshots. Everything below is judged against these rules: an extra or stale number costs more than a missing
detail.

## 3. The two systems

**This system** (`solution/`, 10 modules and about 3,500 lines of its own, plus the merged companion runtime in
`solution/companion/`):

1. It cleans each page.
2. It keeps every snapshot as a view of the site on its date.
3. Rate tables become typed rows: product, qualifiers, tier, term, model years, metrics, minimums and the
   "effective as of" date. Rate questions are answered from those rows only. The newest effective date wins, then
   page trust, then the product's own page over an embedded copy. A table not yet in effect waits, and a true tie
   is declined rather than given an invented winner.
4. Everything else is answered from the sentences that hold the fact, filtered by the shape of the value asked for
   (time, money, phone, date, address, link, count). It then covers every asked part from the same section.
5. Conflicts come from the same rows and from boilerplate repeated across pages.

The answer policy is minimal: only the asked metric, tier, product and date. Refusals contain no numbers.

**The companion system** (selected runtime `2d6b8d6e…`, 14 modules, about 5,200 lines) uses typed handlers per
domain: deposits, loans, services, facts, a conflict engine and evidence objects with raw source spans. It has a
narrow fee fallback, explicit request parsing (requested and negated metrics, dates, compound requests), and deep
copies of ingested pages.

It was selected from about thirty recorded candidates by independent review: a stage is adopted only if no gate
falls *and* no new wrong claim appears. Its gates were public 0.9690, selftest 1.0 and disclosed-development Total
0.9704.

## 4. How the systems were evaluated

| layer | what it shows | limit |
|---|---|---|
| organizer public 40, selftest 5 + 1 | contract, basic facts, repeats, latency | public compatibility, not hidden accuracy |
| our stand-in set, 330 questions | rewordings, `as_of`, changed facts | written by us, so it overlaps our own blind spots |
| our independent author: dev 226 / holdout 176 | a session that never saw the code; answers quoted from the snapshots | one author |
| companion banks: km226, legacy509, A, B, C | four more authors, synthetic scenarios (prompt injection, expired offers, removed pages) | the companion selected on them, so they're not neutral between the two systems |
| mechanism suites on made-up banks | one rule each, independent of Dupaco's wording | narrow by design |
| paired controls, mutations, determinism | a rule must survive rewording and minimal changes | written by the coder |
| fresh blind set (2026-10-23) | a new author session, after both systems were nearly final; pre-registered variants, one run each | one author, 172 questions |

The rules for using these layers:

- **Blind discipline.** Holdout and confirmation banks run for aggregates only. Their questions, answers and
  per-item outputs were never opened.
- **Anti-overfit gate**, from the companion repository:
  - Every rule learned from a bank item gets paired controls in words no bank uses. An equivalent form must keep
    the answer, and a minimally changed form must change it.
  - Blind banks are a final gate, not a tuning signal.
  - A change is rejected if a blind bank drops by more than one item. Changes within noise are judged on whether
    the rule is general.
- **Earlier exception.** During one session, blind aggregates were used to locate a regression by reverting
  changes one at a time. This adapted the system to them, which is why the gate above was adopted. ITERATIONS.md
  marks where this happened.

## 5. Results

### 5.1 This system over time

From the first solution to now: public 0.957 → 0.969; ours-dev 0.614 → 0.874; ours-holdout 0.642 → 0.785;
legacy-holdout 0.189 → 0.628; C-confirm 0.266 → 0.569. The full per-commit table is in ITERATIONS.md §1.

Three lessons:

1. **Saying less was the largest gain.** Answering only the asked metric and tier lifted legacy-holdout from 0.18
   to 0.55. This matches the scoring rule: a correct answer that also prints the dividend rate next to the asked
   APY, or the neighbouring tier, is zeroed by the trap list.
2. **Development gains transfer partly, and unevenly.**

   | pair | dev gain | blind gain | carried over |
   |---|---:|---:|---:|
   | ours-dev → ours-holdout | +0.21 | +0.11 | about half |
   | C-dev → C-confirm | +0.43 | +0.08 | a fifth |
   | A-dev → A-confirm | none | none | the confirmation bank never moved |

3. **Single-bank tuning hid regressions elsewhere.** Two early commits lowered C-confirm by 0.07 before the bank
   existed. Measuring every change on every bank is what exposed it.

### 5.2 The same banks, both systems

Both were run with the unchanged harness, the same snapshots and the same synthetic scenario snapshots.

| bank (items) | who tuned on it | this system | companion `2d6b8d6e` |
|---|---|---:|---:|
| ours-dev (226) | us | **0.874** | 0.678 (2 errors) |
| ours-holdout (176), blind for both | nobody | **0.785** | 0.686 |
| km226 (226) | companion | 0.744 | **0.979** (2 errors) |
| legacy-dev (333) | companion | **0.865** | 0.652 |
| legacy-holdout (176) | companion, round 1 | 0.628 | **0.769** |
| A-dev (100) | companion; us since its release | **0.817** | 0.410 |
| A-confirm (60) | companion, round 2 | **0.584** | 0.516 |
| B-dev (30) | companion; us since its release | **0.542** | 0.268 |
| B-confirm (42) | companion, round 2 | **0.300** | 0.141 |
| C-dev (36) | companion; us since its release | **0.941** | 0.850 |
| C-confirm (36), not shown to its solver | neither directly | 0.569 | **0.778** |

"This system" includes the merged companion handlers. Before the merge (`2500e91`) it scored C-dev 0.840 and
C-confirm 0.369.

The split between original-corpus and synthetic items:

| bank | this system: original / synthetic | companion: original / synthetic |
|---|---|---|
| legacy-dev | 0.895 / 0.760 | 0.771 / **0.234** |
| legacy-holdout | 0.650 / 0.554 | **0.951** / 0.179 |
| A-dev | 0.797 / 0.848 | 0.480 / 0.304 |
| A-confirm | 0.604 / 0.545 | 0.391 / **0.766** |

The companion's synthetic scores are low because its handlers are tuned to Dupaco's layouts. Ours hold up
because the rules are written against generic page shapes.

How to read the comparison:

- **ours-holdout** is the cleanest comparison among the banks: neither process tuned on it. We lead by 0.10.
- **C-confirm** is the most informative gap. Its questions are new neighbours of the C-dev fact families. The
  companion handles them with typed handlers per family, which bind a request to complete multi-part answers: two
  offer clocks, a product's tier plus its top tier, start and resume links, every eligibility route. Our C-dev
  gains came from general rules that only partly reach those neighbours. Merging its handlers (§6) took our
  C-confirm from 0.369 to 0.569 in two steps. The rest of the gap is in multi-part answers its broad modules give
  completely and ours give partly, where the coverage comparison still prefers ours.
- **The companion's synthetic weakness** is just as informative. Its legacy synthetic accuracy is 0.18–0.23,
  because its handlers assume Dupaco's layouts; ours stays at 0.55–0.76 on the same scenarios.
- **Errors.** The companion raised 4 exceptions across our dev and km226. We had none: every answer path is
  wrapped, and an unexpected error is a refusal with no numbers.

### 5.3 A fresh blind set, written last

On 2026-10-23 a new author session, which saw neither system, wrote a question set with conflict gold from the
snapshots. Four variants and a decision rule were fixed in advance
([FRESH-PREREGISTRATION.md](FRESH-PREREGISTRATION.md)). `tests/fresh_once.py` let each source hash run once and
kept only aggregates. This is the companion repository's one-shot heldback rule.

| variant | accuracy | total | consistency | conflict F1 |
|---|---:|---:|---:|---:|
| A: this system at the start of the session | 0.803 | 0.751 | 0.829 | 0.48 |
| B: this system with the eight specialists | 0.869 | 0.819 | 0.886 | 0.57 |
| C: the companion runtime alone | 0.823 | 0.775 | 0.914 | 0.51 |
| D: B, with every companion handler module | **0.888** | **0.836** | 0.900 | 0.57 |
| E: final version (post hoc, see below) | 0.875 | 0.828 | 0.886 | 0.57 |

What it answers:

- **The session's work generalised** (B against A: +0.07 total) to questions written after it.
- **On a set neither system tuned on, the merged system leads the companion alone** (0.819 against 0.775).
  The companion is the more consistent of the two (0.914).
- **More of the companion helped** (D against B), so by the rule fixed in advance D replaced B.

D was then refined on dev banks and paired controls only (§6). E, the final version, was allowed one descriptive
run by an amendment written before it ran. Its result decides nothing, and the comparison with D is post hoc:

- **E is 0.012 below D in accuracy**, about two of 172 questions. Its conflict winners improved (resolution
  accuracy 0.79 → 0.86, from the review fix that keeps each folded variant's own winner), so the total is 0.009
  below D.
- **The likely reason is the judges used for the refinement.** It was chosen on dev banks this system had been
  tuned on, where an answer from another system looks worse than it is, because ours fit those banks. On the
  neutral fresh set, more of the companion was better. The refinement also fixed real faults (FAQ questions
  answered with a rate table; nine broken controls), which the fresh set may not contain.
- **Lesson:** a merge between two systems should be judged on banks neither was tuned on. This is the companion
  repository's rule for candidates, applied here to a merge.

### 5.4 Outside context

The companion repository measured twelve public implementations of this assessment with the same scorer, in 39
suites. Their public scores ranged from 0.33 to 0.969. Only one other, besides the companion's runtime, reached
0.969, which is also this system's score. No configuration beat the companion runtime on public, selftest and an
author-published 94-question set together. This repository didn't read or run those implementations; the numbers
are the companion repository's measurements.

## 6. What was taken from the companion repository, and what wasn't

**Absorbed:**

- **Process.**
  - Independent test authors; blind holdouts, aggregates only.
  - Mechanism suites on invented data. Its program-status, source-planner and Parent45e1 custody suites run here
    (`tests/knowledge_main/`).
  - Mutation tests.
  - The anti-overfit gate: paired controls, and blind banks as a final gate only.
  - Rejecting a change that adds a wrong claim even when its score rises.
  - Recording rejected iterations.
- **Answer rules.**
  - Only the requested metric.
  - Future-effective tables wait.
  - True ties invent no winner.
  - History answers for two or more named days, with every download in between for "how did it change".
  - One heading-owned section answers all parts of a question.
  - The product's own page beats an embedded copy.
  - Invalid dates are declined.
  - Private account state is declined.
  - Unannounced cycles are unknown.
  - Each observation of a page is cited separately.

**Merged as code** (the owner allowed it on 2026-10-23; both repositories are the owner's).

`solution/companion/` holds its final selected submission (`2d6b8d6e`), byte-identical to the companion
repository's `submission/` at its close. `solution/kb_companion.py` ingests every snapshot into it as well. Its
answer is considered only when this system would answer from text, not from its rate tables. Then:

- **Its eight named specialists replace our answer.** Each beat this system on the dev banks outside the
  companion's own tuning bank: membership routes and application links, mobile wallets, contact routes, the
  privacy policy's correction procedure, card offers, the list of credit cards, rates the site doesn't publish,
  and homebuyer grants.
- **Its broad handler modules are weighed against our answer.** The fresh blind set (§5.3) showed them worth
  adding. On their own, though, they answer any question about a product with what they know of the product:
  the HSA rate table for "how many authorized users may be designated?". So they answer only open answer kinds,
  never through its facts module or the general part of its services module. And their answer wins only when it
  holds at least as many of the question's specific, non-product words as ours, ties going to them. This is a light
  form of the companion repository's own conclusion that a matched trigger, a number or `confident=True` is not
  proof that an answer is complete.
- **Its generic search and its guards are never used.** Any error inside it disables it, and our answer stands.

Effect, with blind banks run once at each step:

| bank | before the merge `2500e91` | eight specialists `ce21637` | before the last step `2980092` | broad modules, weighed `28e3d69` |
|---|---:|---:|---:|---:|
| C-confirm | 0.369 | 0.468 | 0.478 | **0.569** |
| ours-holdout | 0.750 | 0.757 | 0.765 | **0.785** |
| legacy-holdout | 0.570 | 0.577 | 0.576 | **0.628** |
| B-confirm | 0.237 | 0.251 | 0.300 | 0.300 |
| A-confirm | 0.498 | 0.498 | 0.584 | 0.584 |

Between the second and third columns, the changes were this system's own (for A-confirm, keeping the pages'
FAQs). The last step also includes the owner's 2026-10-23 policy decisions and the review fixes (§7). Declining a
date before the first download was measured alone earlier, at +0.056 on C-confirm. The review fixes alone left
every blind bank equal.

**Not taken, with the reason:**

- **Its facts module, the general part of its services module, and its broad modules on typed questions** (phone,
  hours, address, branch, date or status, amount). They broke nine paired controls and measured worse than ours.
- **Its credit-score guard**, which declines "what score do I need to qualify" questions. It declined an
  answerable question on our dev bank.
- **Its strict request-evidence audit as a target.** We fail it on answer form (section-title prefixes, notes),
  not on values. Satisfying it would mean rewriting every answer template without a measured accuracy benefit.
- **Its last candidate**, a typed request → claim → completion layer for routing and HELOC (StageA `309afc`). The
  companion repository rejected it on 2026-10-23: its developer gate failed (61 of 90 controls passed) and public
  fell from 0.969 to 0.930 (§6.1).

### 6.1 The companion repository at its close

- **Final selection: `2d6b8d6e`, unchanged since the merge here.** Its last two days added process, not runtime
  changes.
- **Anti-overfit harness.** Version v2a was rejected over path-safety defects found by an independent review.
  Version v2b was approved after a second review.
- **Its last candidate**, StageA `309afc`, ran once through the v2b developer gate. It failed with 29 of 90
  controls (28 of them card controls outside its scope), so its heldback set was never opened. Its original
  scores fell too (public 0.969 → 0.930, disclosed development 0.970 → 0.964). It was archived without a patch or
  a second attempt.
- **Ideas mapped to this system** (from its `OTHER-CANDIDATE-IDEAS.md`, a study of twelve public implementations):

  | idea | here |
  |---|---|
  | resolve the requested fields before background text | `RateQuery` holds the asked metrics, terms, amounts, years, exclusions and date role; only the asked metric and tier are printed. A formal per-slot completion certificate isn't built; `asked_covered` is a lighter check, used where two answers compete |
  | typed table-column ownership | `RateRow` keeps metrics, tier, term, model years and minimums apart. A column is filled in from another page only when every shared number agrees and that table is in effect. Minimum to open is never minimum to earn |
  | separate source occurrences from shared content | every citation is (URL, snapshot that really held that version); combined answers deduplicate by both |
  | heading-owned blocks for multi-part answers | the asked parts are covered from the same section only; a page's sidebar is cut only up to the next heading |
  | reuse parsing across snapshots | not done: ingest takes 18 s, well inside the limit |
  | a model as proposal-only, with deterministic validation | no model is used at all |

## 7. Limitations and open decisions

- **Matching is lexical.** A question worded far from the page ("what range follows" for "ongoing rate") can
  miss. A yes/no guard that declined when the answer didn't cover the question cost seven correct dev answers, so
  it was removed. Yes/no questions about a condition the page doesn't state can still get a confident answer.
- **C-type neighbours.** Complete multi-part answers remain the largest measured gap (C-confirm 0.57 against
  0.78).
- **A-confirm** didn't respond to any change. Its weak spots are unknown, by the blind rule.
- **Conflicts.** F1 is 0.57 on our dev conflict gold and on the fresh set, but 0.16 on the holdout's. Kinds such
  as branch-status and policy-text contradictions aren't detected.
- **The owner's decisions.**
  1. A true tie is declined (2026-10-23; `KB_TIE=both` shows both values with a note). No bank changes.
  2. A date before the first download is declined (2026-10-23, replacing the 2026-10-20 rule of answering from the
     earliest copy with a note; `KB_BEFORE_FIRST=earliest` restores it). Declining measured better: blind
     C-confirm +0.056, km226 +0.020.
  3. Complete-replacement snapshots: a page missing from a download is carried forward here (owner's decision,
     2026-10-20). Some synthetic scenarios treat it as removed.
- **The code review of 2026-10-23** found seven issues the 240 checks didn't cover, all of them combinations: an
  excluded product, two products in one question, a promo column from a table not yet in effect, a date written
  in the question not reaching the companion, two balances, unrelated conflicts merged on equal numbers, and
  history answers citing only the current download. All seven are fixed. Each has a regression test that fails
  on the previous commit and passes now, beside a minimally changed counterpart that passes on both. More such
  combinations surely remain; the lesson is that checks written by the coder share the coder's blind spots.
- **Data.** The snapshots are for this assessment only. The repository tracks the kit's zips and assignment PDF.
  They must not be pushed anywhere public, and the owner decides whether they stay tracked.

## 8. Reproducing

```
python tests/scoreboard.py --label now          # checks, public, selftest, stand-in, our dev (add --holdout for aggregates)
python tests/run_checks.py                      # paraphrases, controls, review cases, synthetic, mutations, determinism
python tests/banks.py --blind                   # every bank; blind ones as aggregates only
python tests/banks.py --blind --submission <other solution folder> --results <dir>   # another system, same banks
python tests/knowledge_main/run.py              # the companion repository's mechanism suites
python tests/fresh_once.py --label X --submission solution   # the fresh blind set: once per source hash, refused after
```

The banks live in the companion repository (`test-banks/local-authoring`) and in
`Desktop/hackathon-independent-eval` for our own author. Per-question outputs of blind banks go to a temporary
folder that nothing reads.
