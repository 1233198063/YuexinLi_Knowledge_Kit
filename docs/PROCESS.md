# How I used agents to solve this assessment, and the choices I made

I didn't hand the assessment to one AI session and wait. I organised several agents into roles that check each
other, and I made the decisions they could not make well themselves: what "current" means, when to say "I don't
know", whose tests to trust, what to merge, what to reject and when to stop. The system itself is described in
[../solution/NOTES.md](../solution/NOTES.md), and the measured results in [REPORT.md](REPORT.md).

Models used: Claude Opus 5.5 and 6.1 Sol.

## 0. In brief: my part

**How I approached the problem.**

- I read the assignment and the scorer first and fixed the objective: maximise the organizer's total, where
  accuracy is 55% and any stale or extra value zeroes a question. Everything else followed from that rule.
  Answers should say less, decline when the site doesn't say, and never be judged by the builder's own tests.
- I decided what "current" means for this site before any tuning, as written rules (§2).

**How I optimised.**

- I set the order of work by the scoring pillars: accuracy first, because it also multiplies consistency and
  speed.
- I required every change to be measured on every bank, development and blind, with the same scorer.
- I chose independent evidence over self-reports. I replaced the builder's optimistic stand-in set (0.96) with
  banks written by authors who never saw the code (0.75 at the time).
- When gains stopped transferring to blind banks, I asked for an overfitting defence instead of more tuning.
- When every existing bank had been looked at, I commissioned a fresh set and had the comparison written down
  before it ran.

**How I orchestrated agents to strengthen the result.**

- I ran two independent lines of agents instead of one long session. Their disagreements showed what each
  lacked.
- Builders were checked by separate reviewers, and a reviewer was scheduled to watch the tournament line.
- I had test authors write banks with blind halves that no solver saw.
- I carried findings between the lines and decided what to absorb, and when the evidence justified merging code.
- I rejected agents' gains that came with a new wrong claim, and closed both lines when the remaining gains were
  small.

**Time and tokens.** In total the agents ran for about 24 hours of execution and used about 800 M tokens, between
2026-10-18 and 10-23.

## 1. The set-up

```
                                 me: roles, rules, policy decisions, merges, stop
                                /                                                \
   staged line: one builder agent working in             tournament line: a control plane over six solver
   explained stages, stopping at each judgment            sessions I selected; candidates frozen and
   call for my decision                                   reviewed stage by stage
            |                                                          |
            +--- code-review sessions (read-only) ---------------------+--- per-stage reviewers; a reviewer
            |                                                          |    scheduled every 30 minutes
            +--- independent test authors (no access to any code) -----+--- test authors legacy509, A, B, C
            |                                                          |
            +------------------ the same scorer, snapshots and banks for every candidate ------------------+
```

| role | agents | the rule I set for it |
|---|---|---|
| solvers | the staged line's builder; the tournament line's six solver sessions (bootstrap, main, parent, three parallel candidates) | each works in its own workspace; a candidate is frozen (copied and hashed) before it is evaluated; nobody edits another's workspace |
| reviewers | a separate code-review session per round on the staged line; independent stage reviewers and a scheduled reviewer on the tournament line | a reviewer never writes the code it reviews, and reads it without changing it |
| test authors | an independent author for the staged line; four authors for the tournament line; a fresh-set author at the end | questions and gold come from the snapshots only; blind halves are never shown to a solver |
| outside material | transfer cases from other public corpora | read as test material only |
| me | | decide policy; choose between agents' outputs; carry findings between the lines; decide merges and the end |

Why two lines: one long session drifts towards its own blind spots and grades itself with its own tests. Two
independent lines measured on the same banks show where each one is weak.

### 1.1 How the agents talked to each other

Most of the work happened in hand-offs between agents, through files each role wrote and the next one read. A
review report, a question bank, a frozen candidate or a verdict is the message. I set what each hand-off must
contain and who may read it.

| hand-off | what is handed over | rule |
|---|---|---|
| question authors → solvers | the development half of each bank: questions, gold answers, sources quoted from the snapshots, a validator | authors never see any code; solvers never see a blind half |
| harness → solvers | per-question results on development halves; aggregate scores only on blind halves | a change that drops any blind bank by more than one item is rejected |
| reviewers → solvers | a report per round: each defect with severity (P1/P2), file and line, a real question that reproduces it, a minimally changed control, and a suggested fix order; sometimes a probe script on made-up snapshots | every finding becomes a fix plus a regression test that fails on the previous commit |
| solvers → stage reviewers | a frozen candidate: copied source, source hash, test hashes | nobody evaluates a live workspace |
| stage reviewers → tournament maintainer | APPROVE or REJECT for that exact hash, with P0/P1/P2 findings | a rejected hash is archived; it is never patched against the same held set |
| scheduled reviewer → tournament maintainer | every 30 minutes: re-measured scores under the same protocol and concrete recommendations | read-only; it never edits what it watches |
| staged line ↔ tournament line | the first solution one way; methods, test suites and finally the selected runtime the other way | taken only when evidence on the same banks supports it |

**How the reviewer coordinated the solvers.** The coordinating reviewer did three things:

- it disclosed part of the questions to the solvers and kept the rest hidden, so the rest only ever produced a
  score;
- it gave each solver a different hint about where to improve: consistency, conflicts, dates, multi-part
  answers, narrative completeness, evidence and uncertainty;
- it pulled the results together on one protocol, kept the parts that held up and rejected the rest (§4).

**Loop 1: reviewer → solver on the staged line.** The second review reported seven defects. Each came with the
question that reproduces it and a control that shows the boundary.

- An excluded product decided the product. "..., not Bright Savings?" returned Bright Savings' 2.25%; without
  that phrase the answer was right.
- Two products in one question were merged, and the auto loan's 60-month term was read as a certificate term.
- A promo column was filled in from a table not yet in effect. This one came with a probe script on made-up
  snapshots.

The solver fixed each defect and added it as a paired control or a mutation test. It ran the new tests on the
previous commit, where all eight failed, before committing.

**Loop 2: stage reviewer → solver on the tournament line.** The first formatting stage raised the replay score to
0.977. The stage reviewer found 4 P1 and 1 P2: aliases that earned literal credit by changing meaning. The stage
was rejected. The next stage narrowed the aliases and scored 0.972, and the review still found 2 P1 and 1 P2. Each
later cycle closed one gap and the reviewer found the next. The sixth was safe but brought no gain, so none was
selected.

**Loop 3: scheduled reviewer → maintainer → gate.** The scheduled reviewer recommended answering routing-number
and HELOC questions by the field asked. The maintainer built that as the
last candidate. The v2b gate failed it (61 of 90 controls), and public fell from 0.969 to 0.930. It was rejected
without a patch, and its held set was never opened.

**Loop 4: question authors → solvers, with a held-back half.** The independent author handed over 226 development
questions; the solver read every miss among them. The 176 holdout questions went only to the harness, which
returned a total. The fresh-set author's 172 questions went to a runner that logs each version and refuses a
second run.

## 2. My decisions, and the trade-offs behind them

| when | decision point | options the agents put in front of me | what I chose | why |
|---|---|---|---|---|
| 10-18 | what "current" means | several rule sets proposed by the builder | newest "effective as of" date first; then page trust (rate sheet > product page > PDF > news > landing > blog > calculator); news-only facts by newest publish date; expired pages never; an undated table counts as oldest | rules a reviewer can check, written before tuning |
| 10-18/19 | old statements on many pages | newest page wins / most-repeated wins | a statement repeated on 3+ pages beats a one-off mention, and its newest copy answers; year-labelled figures are history, not conflicts | old bios and press releases otherwise beat the boilerplate |
| 10-19 | conflict granularity | one conflict per product, or per precise fact | per precise fact (product + term + tier) | matches how answers are judged; merging tiers measured only +0.03 |
| 10-19 | when to say "I don't know" | refuse readily, or only when the site truly doesn't say | only when the site doesn't say | a refusal on an answerable question scores zero as well |
| 10-20 | a page missing from a later snapshot | treat it as removed, or carry it forward | carry it forward | crawls are partial; some synthetic tests expect the other choice, recorded as a known difference |
| 10-21 | three review findings | for each, a conservative and a generous option | a balance below the minimum still gets the rate, with "below the minimum" said first; a named year with no figure is declined; loan kinds missing from the tables are never answered from mortgage rows | no wrong number in any of the three |
| 10-22 | which judge to trust | the builder's own 330-question stand-in set (0.96) | an independent author with no access to the code, with a blind holdout | the stand-in set was over-optimistic: the independent development bank scored 0.75 at the time |
| 10-22 | the tournament line's code | merge it, or ignore it | first absorb only its method (blind holdouts, mechanism suites, paired controls, rejecting gains with new wrong claims), not its code | avoid importing its tuning to its own bank before measuring it |
| 10-22 | the six solver sessions | six candidate builds | one session's conflict engine, another's answer engine, a third as the behaviour anchor; two candidates rejected after holdout and overfit review | combine strengths; never pick a candidate by its own report |
| 10-22 | stages that raised the score | e.g. formatting stages raising a replay to 0.977 through unsafe aliases | rejected | a higher score with a new wrong claim is not a gain |
| 10-22/23 | overfitting | keep tuning on development banks | a defence: paired controls in words no bank uses, blind banks as a final gate only, a study of what transfers | item-driven fixes were found to carry only 3% to 33% of their gain to blind banks |
| 10-23 | merging after all | — | once same-bank evidence showed where the tournament line was stronger, merge its runtime unchanged into the staged line, admitting its handlers by measured evidence | take what it measurably does better, keep what the staged line does better |
| 10-23 | final evidence | stop at the existing banks | commission a fresh question set, register the comparison before any run, and allow each version one run | every existing bank had been looked at by someone |
| 10-23 | ties and dates before the first snapshot | the builder's earlier default (answer from the earliest copy, with a note) against the tournament line's tests (decline) | decline both | the scoring credits "I don't know" when the site doesn't say; declining measured better on a blind bank (+0.056) |
| 10-23 | the tournament line's last steps | harness v2a, v2b and a final candidate | v2a rejected after an independent path review, v2b approved; the final candidate rejected after failing its developer gate (public 0.969 → 0.930); no further lanes | the gate decides, not the effort spent |
| 10-23 | when to stop | keep iterating | close both lines, stop the scheduled reviewer, write the final report | the remaining gains were small and the evidence budget was spent |

Things I kept for myself throughout: every policy decision above, every merge, the handling of the data (a
private repository, nothing redistributed), and when blind data could be used.

## 3. Several agents solving independently

- **The staged line** built the system in stages: page cleaning, typed rate rows, rate answers, sentence search,
  conflicts. It stopped at each judgment call, and the decisions in §2 came from those stops. Public score: 0.13
  → 0.957 → 0.969.
- **The tournament line** started from an early copy of the staged line's first solution and iterated in rounds
  (§4). It selected runtime `2d6b8d6e`.
- **Disagreement was the useful output.** Measured on the same banks, each line was stronger on the banks its own
  process tuned on.
  - The tournament line's typed handlers gave complete multi-part answers on its page families.
  - The staged line's generic rules kept working on synthetic sites (0.55–0.76 against 0.18–0.23).
  - That told me what to take from each.

## 4. The tournament line, round by round

Every stage was frozen with source and test hashes and reviewed by a session that didn't write it. It was adopted
only if no score gate fell (public 0.969, self-test 1.0, a 226-question development total of 0.970) *and* no new
wrong claim appeared.

**Round 1: baseline.**

- Its first test author wrote legacy509: 333 development and 176 holdout questions. They come with synthetic
  sites for prompt injection, expired promotions and pages removed from a full snapshot.
- A review of the baseline found four P1 defects.

**Round 2: tournament.**

- Six solver sessions built competing versions in separate workspaces. Authors A and B wrote independent banks.
- 816 full responses were adjudicated by hand.
- The strongest parts were combined: the main session's conflict engine, a parallel candidate's verified answer
  engine, and the "Parent" modular runtime as the behaviour anchor. Two candidates were rejected after holdout and
  overfit review.
- The selected runtime gained a narrow fee fallback and normalised percentage display in conflicts.

**Round 3: hardening, 27 recorded stages, most of them rejected.** The scores are the 226-question development
total, where the baseline is 0.9704.

| track | what each attempt tried | result | decision |
|---|---|---|---|
| program status, 2 iterations + programme cycles `0c76`, `0d00`, cycle 3 | status windows and dates, then complete source assertions and request dates | 0.9524, 0.9512, 0.9579 (two with a stale trap); cycle 3 closed an old trigger but lost real coverage | all rejected: closing one trigger isn't complete identity or time handling |
| source planner 1, 2a, 2b | find the source first, then answer | 0.9068 → 0.9117 → 0.9117, below the floor | all rejected |
| input ownership `30d89` | stop a caller's later changes from separating text from its source | 0.9704, unchanged | adopted, later superseded |
| formatter, six cycles (`4fc4`, `a7a64`, `0e`, `98be`, `d7`, `fe64`) | earn the scorer's literal-format credit (ranges, labels) without changing meaning | the first two scored 0.977 and 0.972, but added wrong meanings (4 P1 + 1 P2, then 2 P1 + 1 P2); the next three each closed one gap and left another; `fe64` was safe | first five rejected; `fe64` not selected: safe, but no gain |
| narrative `a720` | section, entity and request facets for multi-part answers | 0.9704, unchanged | approved within bounds by me, but its central gain wasn't shown, so not adopted |
| six parallel follow-ups (Bootstrap, Main, Parent, Original 1–3) | each session fixed its own root causes: API time limits, conflict root causes, time and metric pairs, compound slots, entity protection, row-local purposes | on author C's 36 development questions, judged as complete answers, Parent reached 23 accepted / 4 rejected / 9 incomplete, against 14 / 5 / 17 for the reference | Parent chosen as the base |
| deposit opening `ad1`, `30942dcb` | opening and earning minimums as separate slots | floors held, but five and then two P1 root causes | rejected; no third attempt |
| conflict source audit + two entity experiments (`3314`, `4c8603`) | keep another organisation's figures out of conflicts | 0.9507 with two stale traps; 0.9643 | rejected |
| Parent + ownership graft `2d6b8d6e` | only the input-ownership fix, grafted onto Parent | 0.9704 unchanged; public 0.969; self-test 1.0; 20/20 independent mutation controls; no new P0–P2 | **selected** (2026-10-22, inside a fixed delivery window) |

- Author C wrote 75 questions (36 development, 36 confirmation, 3 quarantined) with 116 controls.
- **The honest check on the selection.** On C's 36 confirmation questions, judged as complete answers, the
  selected runtime scored 15 accepted / 1 rejected / 20 incomplete. The previous runtime scored 15 / 0 / 21. The net
  change in complete correct answers was zero, with one more wrong claim. The development gain (23 against 14) did
  not carry over to the confirmation half, and it was recorded that way rather than claimed as a gain.

**Follow-up: new cases and a stricter gate.**

- **New cases.** 32 new cases: 12 from the assignment's own sources and 20 transfer cases from other public
  corpora (statistics tables, privacy-policy text, temporal clauses). The selected runtime completed none of the
  12 assignment cases. Its values weren't wrong; its answers left the asked relation unfinished.
- **Two candidates rejected.**
  - A field-routing pilot (`a703`) improved two questions and kept all 271 original answers. It was still
    rejected for three new P1 defects: an unresolved card product, a negated APR intent, and a third-party payroll
    provider borrowing the credit union's phone number.
  - The single closure attempt (`5037`) lost both of the pilot's gains and added a new P1. No second closure was
    allowed.
- **A stricter gate.** Controls were frozen before any code: 90 developer and 90 held request-evidence controls,
  plus source-occurrence and typed-field controls. An anti-overfit harness ran each candidate once against the
  held set. Its first version (v2a) was rejected after an independent review found path-safety defects; the
  second (v2b) was approved.
- **A scheduled reviewer.** Every 30 minutes it re-measured the scores under the same protocol and published
  recommendations.

**Close (2026-10-23).**

- The only candidate under v2b was a typed request → claim → completion layer for routing and HELOC questions. It
  failed its developer gate: 61 of 90 controls passed. Its held set was therefore never opened.
- Its original scores fell too: public 0.969 → 0.930.
- It was archived without a patch or a second attempt, and `2d6b8d6e` stayed final.
- The scheduled reviewer was stopped.

**Into the staged line.** `2d6b8d6e` was merged unchanged as a specialist. First came eight handlers chosen on
development banks the tournament line hadn't tuned on: C confirmation rose from 0.369 to 0.468. Its broad modules
followed after the fresh set, weighed against the staged line's answer by how much of the question each covers.

## 5. Reviewers that watch progress and prompt

- **Code reviews on the staged line.** Two rounds by separate sessions found 8 and then 7 defects the builder's own
  checks had missed. Examples: an excluded product deciding the product; two products in one question; a promo
  column taken from a table not yet in effect. Every finding became a fix plus a regression test, run against the
  previous commit to show it fails there.
- **Stage reviews on the tournament line.** A stage was adopted only if no gate fell and no new wrong claim
  appeared (§4).
- **The scheduled reviewer.** It observed the tournament line's maintainer session read-only and published
  concrete recommendations. Examples: route routing-number and HELOC questions by the field asked; keep APY and
  opening minimums as separate columns; complete the logical paragraph.
- **Me as the relay.** I carried findings between the lines ("the other side has updated, take a look"). The lines
  learned from each other without either editing the other's workspace.

## 6. Test-writing agents, each with a different purpose

None of them saw the solvers' code. I decided which agent wrote which kind of test and what each solver could
see. The reviewer sat between them and the solvers:

- **Large-scale authors → reviewer.** Broad banks were checked before any solver saw them: sources, gold answers
  and ambiguous items. Faulty items went back to the author for correction (author B's bank came back as a
  corrected v2) or were set aside (3 of author C's). Then the bank was sealed by hash and split into a disclosed
  and a hidden part.
- **Reviewer → defect-targeted authors.** A weakness the reviewer found became a brief for new controls, written
  before any fix: for example, 90 developer and 90 held controls for answers that were true but left the asked
  relation unfinished, plus source-occurrence and typed-field controls. The held half stayed with the reviewer
  to judge the fix once.
- **Reviewer's own controls.** The reviewer added its own beside the authors' (14 beside author C's 102). Once
  more questions stopped adding information, it moved the effort from bigger banks to targeted controls and
  mutations.

| agent | what it produced | purpose |
|---|---|---|
| independent authors | ours: 226 development + 176 holdout. legacy509: 333 + 176. A: 100 + 60. B: 30 + 42. C: 36 + 36. About 1,400 questions in all, quoted from the snapshots, with conflict gold where it applied | measure accuracy without the solvers' bias; every bank has a hidden half that only ever produces a score |
| targeted authors | banks aimed at one known trap each. Stale pages and calculators; tiers and thresholds; dates and future announcements; negations and source conditions (B); complete multi-part answers within one fact family (C). Synthetic sites with 22 prompt-injection scenarios, expired promotions, removed pages and published-vs-fetched dates (legacy509) | probe one weakness at a time, including situations the real snapshots don't contain |
| web-search agents | similar material from outside: 32 new cases, 12 from the assignment's own sources and 20 transferred from other public corpora (statistics tables, privacy-policy text, temporal clauses) | test whether the mechanisms transfer beyond this site and this wording |
| generalisation agents | rewordings of every public question (330-question stand-in set, two paraphrase sets); paired controls in words no bank uses, an equivalent and a minimally changed form for each learned rule (80); mutations of one input at a time, written by reviewer subagents against each frozen candidate; mechanism suites on invented pages with renamed entities | catch rules that only work in one bank's wording; the first run of paired controls caught four |
| adjudicators | judgments of whole answers: 816 tournament responses, and author C's confirmation answers, each judged accepted, rejected or incomplete | judge completeness and wrong claims, which keyword scoring can't see |
| fresh-set author | 172 new questions with conflict gold, written after both lines were nearly final; one run per version, enforced by `tests/fresh_once.py` | one last measurement nobody had tuned on |

## 7. The rounds side by side

| phase | staged line | tournament line |
|---|---|---|
| build | staged build with my decisions at each stop; public 0.957 | baseline from that copy; four P1 defects found |
| first review | 8 findings fixed; public 0.969, the file's ceiling without its judge | six-solver tournament, hand adjudication |
| independent tests | the independent author's banks; blind holdout 0.64 → 0.75 | 27 stages, most rejected; `2d6b8d6e` selected |
| absorb and merge | its method, then its runtime as a specialist; blind C confirmation 0.35 → 0.47 | new cases, harness v2a rejected and v2b approved |
| final | fresh set; second review (7 findings); its broad modules merged, weighed by coverage | last candidate rejected; `2d6b8d6e` final |

Every commit that changed the solution was later re-scored on every bank (ITERATIONS.md §1).

## 8. Overfitting, and how each problem was handled

| problem | how it showed | what was done |
|---|---|---|
| fixes driven by one failing item | they kept 3% to 33% of their development gain on blind banks; rules derived from the scoring rule kept 82% or more | prefer rules derived from the scoring rule. Every rule learned from an item gets **paired controls**, in words no bank uses: one equivalent form, one minimally changed form. The first run caught four rules that only worked in the bank's phrasing |
| templated banks | legacy-dev rose 0.812 → 0.855 from one question pattern repeated over products; its holdout stayed equal | count a templated gain once; trust the blind half |
| using blind banks to debug | once, blind aggregates were used to find a regression by reverting changes one at a time | a stricter gate: blind banks only as a final check, reject a change if any blind bank drops more than one item, never bisect on blind |
| a system judged on its own bank | the tournament line's runtime scores 0.979 on its tuning bank and much less elsewhere | compare systems only on banks neither tuned on; label every bank by who tuned on it |
| score gains with new wrong claims | replay scores rose through unsafe aliases | rejected |
| spending a blind set by looking twice | each look lets choices fit it | pre-registration, and `tests/fresh_once.py`: it logs a START line before importing a version and refuses a second run of the same source hash |
| a merge judged on biased banks | the fresh set preferred more of the tournament line's modules (0.836); restricting them on development banks cost about two of 172 questions (0.828) | recorded as a finding (GENERALIZATION §9). The run had been declared descriptive beforehand, so nothing was rolled back |
| the builder's tests share the builder's blind spots | 240 checks passed while the second review found 7 combination bugs | separate reviewers; regression tests proven to fail on the old code |

## 9. Defects that remain

- **Complete multi-part answers.** C confirmation is 0.57 here against 0.78 for the tournament line's runtime on
  its own. That runtime shows the same gap from its side: none of its answers to the 12 new assignment cases was
  complete.
- **Lexical matching.** No embeddings; a question worded far from the page can miss.
- **Conflict recall.** F1 is 0.57 on development gold and the fresh set, but 0.16 on the holdout's gold.
- **One blind bank never moved** (author A's confirmation). Its weak spots are unknown, by the blind rule.
- **The last refinement** of the merge was measured only on banks the staged line had been tuned on. No unused
  neutral set remains to measure it.

## 10. What I would keep doing

- Separate the roles, and enforce the separation with tools, not intentions.
- Run independent solvers; their disagreements locate the mechanisms worth having.
- Keep policy decisions with a person, write them down, measure them, and keep each one as a switch.
- Reject a score gain that adds a wrong claim, and record rejected iterations as carefully as adopted ones.
- Judge on data nobody tuned on, and write the comparison down before running it.
