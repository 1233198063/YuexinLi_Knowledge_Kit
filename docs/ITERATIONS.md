# Iteration ledger

The owner ran two lines of agents on the same assessment:

- **the staged line** (this repository): one builder agent, one rule-based solution iterated commit by commit,
  with the owner deciding at every judgment call;
- **the tournament line**: a control plane in which separate sessions wrote question banks, built competing
  solutions and reviewed every candidate. Its selected runtime is called "the companion" here.

This file records both iteration routes and every test layer each one used. [REPORT.md](REPORT.md) compares the
two systems, and [METHODOLOGY.md](METHODOLOGY.md) describes the process that came out of them.

## 1. This repository

### How to read the score table

Every commit that changed `solution/` was exported and scored again afterwards, with the unchanged organizer
harness, on the public file and on every agent-written question bank (`tests/banks.py --submission`). The banks
didn't all exist when the early commits were written. Scoring those commits afterwards shows effects that nobody
could see at the time.

The columns show accuracy (the harness `qa_score`). The banks are described in §3:

- **Dev** banks may be read question by question.
- **Blind** banks (holdouts, confirmations) were only ever run for aggregates. Nobody looked at their questions or
  answers.

| commit | public | ours-dev | km226 | legacy-dev | A-dev | B-dev | C-dev | ours-holdout | legacy-holdout | A-confirm | B-confirm | C-confirm |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `601b96c` first solution | 0.957 | 0.614 | 0.399 | 0.474 | 0.721 | 0.122 | 0.407 | 0.642 | 0.189 | 0.502 | 0.170 | 0.266 |
| `718dc24` code-review fixes | 0.969 | 0.679 | 0.413 | 0.481 | 0.678 | 0.193 | 0.458 | 0.665 | 0.191 | 0.508 | 0.185 | 0.270 |
| `921fb15` decline unlisted fees | 0.969 | 0.678 | 0.408 | 0.468 | 0.681 | 0.193 | 0.458 | 0.667 | 0.184 | 0.500 | 0.185 | **0.215** |
| `740de90` end of day 1 | 0.969 | 0.678 | 0.408 | 0.468 | 0.681 | 0.193 | 0.458 | 0.679 | 0.184 | 0.500 | 0.185 | 0.215 |
| `27b435a` independent-dev fixes | 0.969 | 0.756 | 0.417 | 0.462 | **0.641** | 0.207 | 0.482 | 0.705 | 0.186 | 0.500 | 0.185 | **0.199** |
| `4d79bb6` decline the unpublished | 0.969 | 0.790 | 0.407 | 0.434 | 0.685 | 0.179 | 0.482 | 0.703 | 0.184 | 0.472 | 0.178 | 0.261 |
| `3e30fa4` branch hours, abbreviations | 0.969 | 0.800 | 0.410 | 0.437 | 0.685 | 0.174 | 0.482 | 0.711 | 0.184 | 0.472 | 0.171 | 0.261 |
| `e13b455` future-effective, ties | 0.969 | 0.800 | 0.410 | 0.434 | 0.685 | 0.174 | 0.482 | 0.711 | 0.184 | 0.472 | 0.171 | 0.261 |
| `4aebe69` **asked metric and tier only** | 0.969 | 0.809 | 0.447 | **0.711** | 0.695 | 0.230 | 0.510 | 0.723 | **0.550** | 0.472 | 0.198 | 0.265 |
| `de7c4f2` words, misspellings, determinism | 0.969 | 0.809 | 0.473 | 0.714 | 0.695 | 0.230 | 0.502 | 0.723 | 0.550 | 0.472 | 0.198 | 0.265 |
| `239d78c` typed keys, named products | 0.969 | 0.816 | 0.550 | 0.767 | 0.724 | 0.241 | 0.632 | 0.751 | 0.557 | 0.494 | 0.198 | 0.284 |
| `00f6859` each named day | 0.969 | 0.816 | 0.573 | 0.771 | 0.724 | 0.241 | 0.738 | 0.754 | 0.557 | 0.494 | 0.198 | 0.284 |
| `2effed2` **cover every asked part** | 0.969 | 0.827 | 0.594 | 0.775 | 0.741 | 0.274 | 0.824 | 0.754 | 0.566 | 0.498 | 0.244 | **0.349** |
| `7753542` paired controls | 0.969 | 0.827 | 0.594 | 0.775 | 0.741 | 0.274 | 0.824 | 0.754 | 0.566 | 0.498 | 0.244 | 0.349 |
| `d3b3c6f` custody-suite fixes | 0.969 | 0.827 | 0.595 | 0.775 | 0.741 | 0.274 | 0.840 | 0.750 | 0.570 | 0.498 | 0.237 | 0.349 |
| `2500e91` its winning mechanisms, reimplemented | 0.969 | 0.828 | 0.619 | 0.792 | 0.741 | 0.274 | 0.840 | 0.750 | 0.570 | 0.498 | 0.237 | 0.369 |
| `f43a470` **companion merged as a specialist** | 0.969 | 0.838 | 0.668 | 0.795 | 0.741 | 0.274 | 0.901 | 0.757 | 0.577 | 0.498 | 0.237 | 0.436 |
| `ce21637` three more specialist handlers | 0.969 | 0.856 | 0.673 | 0.800 | 0.741 | 0.274 | 0.909 | 0.757 | 0.577 | 0.498 | 0.251 | 0.468 |
| `e957c52` named features, eyebrow headings | 0.969 | 0.859 | 0.675 | 0.800 | 0.819 | 0.368 | 0.925 | 0.757 | 0.576 | 0.506 | 0.284 | 0.478 |
| `7cdf25d` **pages' FAQs kept** | 0.969 | 0.867 | 0.675 | 0.800 | 0.817 | 0.537 | 0.941 | 0.761 | 0.577 | 0.580 | 0.300 | 0.478 |
| `196c068` every snapshot, newest band, rate sheet | 0.969 | 0.867 | 0.700 | 0.800 | 0.817 | 0.537 | 0.941 | 0.761 | 0.577 | 0.580 | 0.300 | 0.478 |
| `0f89a2d` places, zero tiers, wrapped lines | 0.969 | 0.874 | 0.700 | 0.800 | 0.817 | 0.537 | 0.941 | 0.765 | 0.576 | 0.584 | 0.300 | 0.478 |
| `0f16e25` the asked metric next to "High-Yield" | 0.969 | 0.874 | 0.700 | 0.812 | 0.817 | 0.537 | 0.941 | 0.765 | 0.576 | 0.584 | 0.300 | 0.478 |
| `2980092` minimum to open, exclusions | 0.969 | 0.874 | 0.701 | 0.855 | 0.817 | 0.537 | 0.941 | 0.765 | 0.576 | 0.584 | 0.300 | 0.478 |
| `28e3d69` **broad companion modules, weighed; review fixes** (final) | 0.969 | 0.874 | 0.744 | 0.865 | 0.817 | 0.542 | 0.941 | **0.785** | **0.628** | 0.584 | 0.300 | **0.569** |

Commits that only touched tests or docs are left out, as are runs with identical scores (`b17b9fe`, `bdd8e5b`,
`51ddee3`, `51bbd72`, `f576948`). Raw outputs are kept outside the repository: they contain snapshot text.

What the table shows:

- **The biggest single gain came from saying less.** `4aebe69` answers only the asked metric (APY, not the
  dividend rate printed beside it), only the asked tier, and only the asked product. legacy-dev rose from 0.434 to
  0.711 and the blind legacy-holdout from 0.184 to 0.550. The organizer's rule is that any old or wrong value
  zeroes a question, and listing neighbouring numbers kept hitting those traps.
- **Some regressions stayed hidden at the time.** `921fb15` and `27b435a` lowered C-confirm (0.270 → 0.199), and
  `27b435a` lowered A-dev too. Neither bank existed yet. This is why every change is now measured on every bank.
- **A-confirm barely moved** (0.502 → 0.498). It is the one blind bank our changes didn't lift. Its synthetic part
  improved (0.545) while its original-corpus part didn't.
- **C transferred poorly, until the merge.** By `d3b3c6f`, C-dev had risen from 0.407 to 0.840 but C-confirm only
  from 0.266 to 0.349. Merging the companion's handlers for C's page families took C-confirm to 0.468.
- **Across all commits** the dev and blind changes correlate at r = 0.88, and 63% of the summed dev gain reached
  the blind banks. Scorer-derived rules and evidence-chosen merges transferred almost fully; fixes driven by
  single items transferred little. See [GENERALIZATION.md](GENERALIZATION.md).

### The iterations

Each entry gives what triggered the change, the mechanism, the evidence, and the decision. All decisions are
general rules: there is no code keyed to a question id, URL or expected value.

**Day 1 (2026-10-21). From the kit to a rule-based system: public 0.957 → 0.969.**

- `601b96c` First solution. It cleans pages, keeps every snapshot as a view of the site on that day, turns rate
  tables into rows, finds sentences for everything else and detects conflicts.
- `718dc24` An external code review found misread tiers, APR shown as APY, unlisted loan kinds answered with plain
  mortgage rows, and missing refusals. Each finding was fixed and pinned as a REVIEW case in
  `tests/run_checks.py`. Paraphrase sets A (tuned) and B (written fresh, 27/30 on its first run) were added.
- `b17b9fe`, `921fb15`, `bdd8e5b`, `51ddee3`, `51bbd72`, `740de90`:
  - strict one-line rate statements, which take the harness self-test to 1.0;
  - unlisted fees and products that only a stale page still shows are declined;
  - the newest wording of reworded boilerplate wins;
  - "has it changed?" works for text facts too;
  - loose `as_of` formats are accepted, and an answer never crashes;
  - rates are compared as numbers in conflicts.

**Day 2 morning. An independent test author.**

- A separate session that never saw the code wrote 226 development questions and a 176-question holdout, each
  answer quoted from the snapshots.
- `27b435a`, `4d79bb6`, `3e30fa4`, `f576948` were generic fixes for the dev failures: decline what the site doesn't
  publish, whole multi-word names, branch hours from opening releases, abbreviations, reworded boilerplate
  conflicts.
- Dev rose from 0.678 to 0.800 and the holdout from 0.679 to 0.711. `b1f04db` reported in NOTES that about a
  quarter of the dev gain carried over to the holdout.

**Day 2 afternoon. Scoreboard, mechanism suites, mutations.**

- `3f4ac39` added `tests/scoreboard.py`, which runs every layer in one command. It also copied the tournament
  line's mechanism suites (program status, source planner) into `tests/knowledge_main/`.
- `e13b455` came from the tournament line's source-order findings. A table that takes effect after the
  download date waits until that date, and equally dated, equally trusted pages that disagree produce no invented
  winner. The commit added `MUTATIONS`: one rule and one changed input per test.

**Day 2 evening. The tournament line published its banks.**

- `tests/banks.py` was added. It runs every bank with the organizer harness, with each synthetic item on its own
  scenario snapshots, and blind banks run for aggregates only.
- `4aebe69` came from the dominant failure on the banks: over-listing. Answers now give only the asked metric,
  tier and product. Qualifiers named inside "not / except / other than" are ruled out. Compound questions with
  different kinds of parts are split.
- `de7c4f2` added amounts and years written in words ("seven grand", "'26 car") and misspelled product names. It
  also made answers deterministic: tie-breakers on every sort and rounded float sums. The bug it fixed was an
  answer that changed between runs because of set order; the `DETERMINISM` layer was added with it.

**Day 2 night (2026-10-22/23). Bank-driven fixes under an anti-overfit gate.**

- `239d78c` began with a C-dev regression traced to a normalisation side effect: "four-card" became "four card",
  and "four" was read as an unknown card kind.
  - **Rejected and reverted inside this commit:** a "present-key" rule, which picked a typed answer's key word only
    from words that some typed text contains. It cost about 0.05 on C-confirm because it answered things the site
    doesn't say. In its place, keys skip words about the archive ("shown", "snapshot", "crawl") and the question's
    numbers and months.
  - Also in this commit: a named product beats a bare family word; "personal and business cards" lists both; a
    balance's tier plus the top tier's threshold; "was X listed" against "does Dupaco offer X"; payment-channel
    fees.
- `00f6859` absorbed the tournament line's history answers. A question naming two or more days side by side
  is answered as the site stood on each day. "Regular and jumbo" shows both. "Minimum" counts as an extreme only
  next to a rate word.
- `2effed2` cover every asked part. Absorbed from the tournament line's finding that one heading-owned block
  should answer all of a multi-part question.
  - A text answer that leaves asked words uncovered adds up to two sentences holding them, from its own section,
    or from another section of the same page only when a sentence holds two missing parts.
  - A rate question that also asks timing ("posting window", "expiry") adds the offer's own sentence.
  - C-confirm rose from 0.284 to 0.349 and B-confirm from 0.198 to 0.244.
  - **Rejected inside this commit:** three tightenings. A table row would answer alone; amount and rate words would
    never count as asked; covering sentences could not be table rows. Each one cost a blind bank about one item,
    so only the narrowest fix was kept: function words such as "not" never count as asked.
- `7753542` added **paired controls**, after the tournament line's anti-overfit gate. Each rule learned from
  a bank item gets questions in words no bank uses: an equivalent form must keep the answer, and a minimally
  changed form (another actor, qualifier, day or polarity) must change it. The first run exposed four rules bound to
  a bank's wording. They were made general, and every bank score stayed the same.
- `d3b3c6f` absorbed the tournament line's Parent45e1 custody suites: 35 synthetic tests on made-up banks.
  13 passed on arrival and 30 pass now. The general fixes they exposed:
  - effective dates in more wordings;
  - a product's own page beats a copy of its table embedded on another page;
  - a table not yet in effect leaves that day's rate unknown;
  - impossible dates are declined;
  - per-clause dates;
  - every download between two months for "how did it change";
  - unannounced cycles are unknown;
  - private account state is declined;
  - day-N against first-M-days windows;
  - headings without blank lines.

  **Rejected:** a yes/no coverage guard. It declined seven correctly answered dev questions whose wording differs
  from the page's.
- `5cf624a` kept the tournament line's request-evidence developer controls as a diagnostic (0/90 here,
  22/90 for its own runtime).

**Day 3 (2026-10-23). Absorbing what the companion does better, then merging it.**

The owner asked to absorb what the companion does well, then allowed merging its code (both lines are the
owner's work). Analysis first, on the dev banks only:

- Per question, a "best of both" answer would add 0.06 to 0.15 per bank. That is the room there is.
- A naive merge (use its answer whenever ours declines) went up on some banks and down on others: it answers
  confidently where our refusal is right.
- Per route, the companion wins every kind of question on km226, its own tuning bank, and loses most kinds
  elsewhere. So the merge had to be chosen per handler, by evidence outside km226.

The commits:

- `2500e91` reimplemented its winning mechanisms as general rules:
  - comparisons answer both sides (several model years, purchase and refinance, the shortest and longest terms,
    two terms compared);
  - "which tier ..., and what is its APY" is one rate question;
  - a named product kind ("student loan") restricts text answers, when the site titles a product that way;
  - "paying it off early" also means prepayment;
  - private account state in more wordings.

  Not taken: its credit-score guard, which declined an answerable question. Answer formats tuned to the bank
  authors were not taken either, because the organizer's tokens are plain numbers. Fourteen paired controls; the
  first run caught two more wording-bound rules.
- `f43a470` **merged it.** `solution/companion/` holds its submission unchanged, and `kb_companion.py` uses its
  answer only for text questions, and only when one of five services handlers answered: join routes, wallets,
  contact routes, policy corrections, offers. A guard keeps "museum-membership benefit" out of the join handler.
- `ce21637` added three loans handlers on the same evidence: the card list, unpublished rates, homebuyer grants.
  Its mortgage, installment, card-fee and student handlers were mixed or worse, and stay out.
- `eb0a5ca` made the two owner policies switchable and measured them. Declining a date before the first download:
  C-confirm +0.056, km226 +0.020. Declining a true tie: no change. Defaults kept until the owner decides.
  Also added `docs/GENERALIZATION.md`.
- `5f7e3f6` conflicts: a variant changed in its base product's table update joins that conflict (36 → 28 entries,
  no gold conflict lost). Conflict F1: ours-dev .48 → .57, km226 .15 → .18, blind holdout .089 → .108.
- `e957c52` came from A-dev and B-dev failures:
  - a multi-word name ("Positive Pay") restricts open questions to sections naming it as a phrase;
  - an eyebrow heading ("##### POSITIVE PAY" above "## Stop Fraud Before It Starts") stays in the heading path;
  - a capitalised verb starting a later sentence is not a name;
  - "where can I find X online" asks for a link;
  - the private-account guard fires only for lookups, not how-to questions.

  A-confirm moved for the first time (.498 → .506).
- `7cdf25d` **the biggest data fix.** The cleaner cut every page at its "Handpicked for You" block, and product
  pages put their FAQ after it, so the savings, cash-management and other FAQs were never indexed. Now only the
  block goes. With them:
  - entities escaped twice are decoded;
  - "non-members" indexes as both "nonmembers" and "members";
  - "a price of nothing" counts only for the thing asked;
  - counts in words are read;
  - "conflict of interest" is not a rate.

  Blind A-confirm .506 → .580, B-confirm .284 → .300. A second ranking rule (any section titled with a named phrase
  wins) was measured on the dev banks and dropped.
- `196c068` came from km226's temporal items:
  - "across all five snapshots" answers each download;
  - "most recent" is not "most";
  - "the newest model-year band" keeps that band;
  - "was X listed in the rates table" reads the rate sheet itself;
  - tier wording ("capped at $100,000", "eligible balance band") is not a condition;
  - "60- and 84-month" are two terms and "48 through 84 months" is a range.

  km226 .675 → .700 (traps 6 → 4); every blind bank equal. The first version of the rate-sheet rule also applied
  to link questions and cost the stand-in set three source credits; it was narrowed to presence questions.
- `0f89a2d`:
  - a state only qualifies a place ("Galena, Illinois" is written "Galena, IL"). This was a regression since the
    first solution, found by reading an old commit's answer;
  - a zero-paying tier says where earning starts;
  - hard-wrapped lines continue their sentence;
  - smallest/largest redemption limits.

  Two broader versions were measured and narrowed: "amount" as a money word, and "earned" for "earned income".
- `0f16e25`: "High-Yield Savings" names a product, so its "yield" doesn't ask for the APY; "exclude" and "omit" rule
  metrics out. legacy-dev traps 20 → 15.
- `2980092`:
  - "the minimum to open" answers the table's Min. to Open column;
  - product names come from what is asked, not from what is excluded;
  - a named personal loan beats the mortgage word "conventional".

  legacy-dev .812 → .855, while its blind holdout stayed equal. The dev gain came from templated items, one
  question pattern repeated for several products. See GENERALIZATION §1.
- **Fresh blind set** (2026-10-23, §3). A new author session wrote a set neither system had seen. Four variants
  were pre-registered and each was run once ([FRESH-PREREGISTRATION.md](FRESH-PREREGISTRATION.md)). By the rule
  fixed in advance, D (every companion handler module) replaced B (the eight evidence-chosen handlers).
- `28e3d69` **the companion's broad modules, weighed; the review fixes**:
  - *Refining D without the fresh set.* D's broad modules broke nine paired controls (routing FAQ, hours, branch
    status, cashier's check, museum, LPL). They now answer only open answer kinds, and never through the
    companion's facts module or the general part of its services module.
  - *Its broad modules answered FAQ questions with a product's rate table.* B-dev fell .537 → .477 with the first
    refinement alone. Examples: the HSA's authorized-user rules, the IRA contribution cap, a loan's example monthly
    payment, a HELOC's qualifying score, an account's initial deposit. An absolute coverage threshold fixed B-dev
    but cut correct enumeration answers on km226 ("list every loan category"), because a list of names doesn't
    repeat the question's words. The rule kept has no threshold. When only a broad module answered, this system
    answers too, and the answer holding more of the question's specific non-product words wins, ties going to the
    companion. This follows the tournament line's own finding that "a trigger match, a number or confident
    is not a completion proof".
  - *Owner's decisions of 2026-10-23.* A true tie and a date before the first download are both declined.
  - *The seven issues of the 2026-10-23 code review*, each with a regression test that fails on the previous
    commit and passes now, beside a minimally changed counterpart that passes on both:
    1. an excluded product ("..., not Bright Savings") decided the product;
    2. two products in one question were merged, and one's term was read as the other's;
    3. a promo column was filled in from a table not yet in effect;
    4. the companion got the explicit `as_of` but not a date written in the question;
    5. of two balances, only the first got its tier;
    6. two unrelated products that swapped the same two numbers were merged into one conflict, and a folded
       variant lost its own resolution;
    7. a "has it changed?" answer cited only the current download.

  Dev: B-dev .537 → .542, legacy-dev .855 → .865, km226 .701 → .744; ours-dev, A-dev and C-dev equal. Blind, run
  once: ours-holdout .765 → .785, legacy-holdout .576 → .628, C-confirm .478 → .569, A and B confirmation equal.
  The fix commits alone left every blind bank equal (two gate runs, before and after them). On the fresh set the
  final version scored .828 total, against D's .836 (one descriptive run, decided nothing; REPORT §5.3).

### Decisions left to the owner

The owner decided both policies where the tournament line's tests expected the other choice, on 2026-10-23:

1. **A true tie.** Two equally trusted pages, dated the same day, print different numbers. The answer declines:
   the site doesn't say which is current, and showing both prints a wrong value (`KB_TIE=both` restores both
   values with a note).
2. **A date before the first download.** Declined: no copy of the website from then exists. This replaces the
   2026-10-20 decision to answer from the earliest copy with a note (`KB_BEFORE_FIRST=earliest` restores it).

A third difference concerns snapshots that are complete replacements (a page missing from one means it was
removed). This system carries a missing page forward, by the owner's decision of 2026-10-20.

## 2. The tournament line's route

Its runtime identity is the hash of its 14 runtime modules. Its gates were public 0.9690, selftest 1.0000 and
disclosed-development Total 0.9704 (226 questions plus a 16-topic conflict proxy, Accuracy 0.9938). Every stage
was frozen with source and test hashes, reviewed by a session that didn't write it, and adopted only if no gate
fell.

**Round 1: baseline.**

- A first author wrote `legacy509`: 333 development and 176 holdout items, with synthetic scenarios including
  prompt injection, expired promotions and full-snapshot removal.
- The baseline review found four P1 defects.

**Round 2: tournament.**

- Six solver sessions built competing solutions. Authors A (163 items) and B (74 items, with a corrected v2) wrote
  independent banks.
- 816 full responses were adjudicated by hand.
- The selected "Parent" runtime got a narrow fee fallback (borrow an unconditional base fee from the previous
  complete snapshot) and conflict percentage display normalisation.

**Round 3: hardening, 27 recorded stages.** Most were rejected even when the replay score rose:

| track | result | decision |
|---|---|---|
| program status iterations 1, 2; programme `0c76`, `0d00`, `fa016` | regressions to 0.9524 / 0.9512 / 0.9579, and .9704 → .9555 | rejected: closing a trigger isn't complete identity or time handling |
| source planner 1, 2a, 2b | 0.9068 → 0.9117, below the floor | rejected |
| format 1 (`4fc4`) and 2 (`a7a64`) | replay 0.9770 and 0.9715, with semantic P1/P2 findings | rejected despite the gain: unsafe aliases can earn lexical credit |
| safe formatter `fe64` | 0.9704 enabled, base and disabled | not selected: safe, but no gain |
| ownership `30d89` | input-ownership defect closed, no score change | adopted, later superseded |
| narrative `a720` | owner-approved, central gain not shown | pending, not adopted |
| Bootstrap, Main, Parent, Original 1–3 follow-ups | Parent reconciled 23/4/9 on author C dev36 (reference 14/5/17) | Parent chosen as the behaviour anchor |
| Parent ownership graft `2d6b8d6e` | 0.9704 unchanged, 20/20 independent mutation controls | **selected** |
| conflict owner `3314`, `4c8603` | 0.9507 with two traps; 0.9643 | rejected |
| deposit opening `ad1`, `30942dcb` | floors held; five, then two, P1 root causes | rejected |

Author C wrote 75 items (36 dev, 36 confirmation, 3 quarantined), with 102 author controls and 14 independent
controls. The selected runtime's confirmation review was 15 accepted, 1 rejected and 20 incomplete. Against the
previous runtime it was a net complete-correct change of zero.

**Follow-up: new cases, closure plan.**

- A 32-case admitted bank: 12 OA-source cases and 20 cross-domain transfer cases.
  - The selected runtime completed 0 of the 12 OA cases. The reason was a completeness gap (true snippets that
    don't finish the asked relations), not wrong values.
  - Its gold isn't published, so it isn't used here.
- A field-routing pilot (`a703`) and a closure (`5037`) were rejected, each with new P1s.
- **Request-to-evidence closure plan.** Every requested slot must become a source-conditioned claim and then a
  rendered clause, and the whole answer is audited at the end.
- **Anti-overfit gate.** Controls mutate actor, temporal role, polarity, qualifier, expression and clause order,
  each with equivalent and minimally non-equivalent forms. Developer-visible tests are kept apart from
  reviewer-held neighbours. A failure on the held set rejects that exact source hash, and it isn't patched against
  the same set.
- Pre-code control freezes:
  - request-evidence: 90 developer and 90 held controls (22/90 for its runtime);
  - source occurrences: 9/14;
  - typed optional fields: 14/38.

**Close (2026-10-23).**

- **Its anti-overfit harness went through two versions.** v2a was rejected after an independent path review
  (integrity defects in how state and paths were handled). v2b was approved after a second review, and StageA was
  reopened under a candidate-specific v2b gate.
- **StageA `309afc`, the only implementation under v2b,** added a typed request → claim → render → completion
  module for routing and HELOC and left the 13 other modules byte-identical. Its single developer run failed:
  61/90 controls passed and 29 failed, 28 of them card groups outside its scope. Under the gate's rule, a failure
  rejects the hash and the heldback set is never read. Independently, public fell from 0.9690 to 0.9302 and the
  disclosed development Total from 0.9704 to 0.9641. It was archived without a patch or a second hash.
- **The final selection stays `2d6b8d6e`** (package `bde84baf…`). Its periodic reviewer was stopped and the
  superseded round-1 archive was published.
- **Relevance here.** The merged copy in `solution/companion/` is byte-identical to that final selection.
  Nothing in the close changed runtime code, so there was nothing new to merge. The rejected candidate's lesson
  matches this repository's: a typed completion layer must not cost entity attribution elsewhere.

## 3. Test layers, and where each one runs here

| layer | origin | here | result now |
|---|---|---|---|
| organizer public 40 | kit | `harness/run_eval.py`, `tests/scoreboard.py` | 0.969 (the most the file allows without its LLM judge) |
| organizer selftest 5 + 1 conflict | kit | scoreboard | 1.0 |
| stand-in hidden set, 330 questions | this repo (`tests/build_sim_eval.py`) | scoreboard | 0.9628 total |
| paraphrases A 29 / B 30 | this repo | `tests/run_checks.py` | 59/59 |
| review cases 33 | external code reviews | run_checks | 33/33 |
| synthetic snapshots 4, mutations 19 (8 from the 2026-10-23 review) | this repo | run_checks | 23/23 |
| paired controls 80 | this repo, after the companion's gate | run_checks | 80/80 |
| determinism across two hash seeds | this repo | run_checks | 59/59 |
| ours-dev 226 / ours-holdout 176 | our independent test author | `tests/banks.py` | 0.874 / 0.785 (holdout blind) |
| km226 + 16-topic conflict proxy | companion | banks | 0.744 |
| legacy509 dev 333 / holdout 176 | companion, round 1 | banks | 0.865 / 0.628 (blind) |
| A dev 100 / confirm 60 | companion, round 2 | banks | 0.817 / 0.584 (blind) |
| B dev 30 / confirm 42 | companion, round 2 | banks | 0.542 / 0.300 (blind) |
| C dev 36 / confirm 36 | companion, round 3 | banks | 0.941 / 0.569 (blind) |
| fresh blind set 172 + conflict gold | a new author session, 2026-10-23 | `tests/fresh_once.py`, one run per version | 0.828 total (variant D 0.836, companion alone 0.775) |
| program status 48, source planner 25 | companion, round 3 | `tests/knowledge_main/run.py` | 8/48, 11/14 applicable (diagnostic) |
| Parent45e1 custody 35 | companion, round 3 | knowledge_main/run.py | 33/35 (both policies now decline by the owner's decision) |
| request-evidence developer controls 90 | companion, follow-up | by hand (see MANIFEST) | 0/90 (diagnostic of answer form) |
| fee 19, percent display 7, narrative 16 | companion | not applicable | they unit-test that runtime's own modules |
| provenance 14, typed fields 38 | companion | not copied | they read that runtime's internals |
| every reviewer-held set | companion | never read or run | its own protocol; our blind banks play that role |
| new 32-case bank | companion | not used | its gold isn't published |
