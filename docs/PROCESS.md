# How I used agents to solve this assessment, and the choices I made

I didn't hand the assessment to one AI session and wait. I organised several agents into roles that check each
other, and I made the decisions they could not make well themselves: what "current" means, when to say "I don't
know", whose tests to trust, what to merge, what to reject and when to stop. This file describes that work. The
system itself is described in [../solution/NOTES.md](../solution/NOTES.md), and the measured results in
[REPORT.md](REPORT.md).

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

- I ran two independent lines instead of one long session. Their disagreements showed what each lacked.
- Builders were checked by separate reviewers, and a reviewer was scheduled to watch the other line.
- I had test authors write banks with blind halves that no solver saw.
- I carried findings between the lines, decided what to absorb, and decided when the evidence justified merging
  code.
- I rejected agents' gains that came with a new wrong claim, and closed both lines when the remaining gains were
  small.

**Time, tokens and models.**

| | line 1: this repository | line 2: knowledge-main |
|---|---|---|
| models and tools | Claude Opus 5.5 in Claude Code (builder, test-author and fresh-set subagents) | 6.1 Sol, in TRAE CLI sessions |
| calendar time | 2026-10-16 (first read) and 2026-10-18 → 10-23 | in parallel; its repository holds 73 commits from 10-22 to 10-23, after earlier rounds in separate workspaces |
| agent working time | about 15.5 hours of active session time (gaps over 15 minutes not counted) | not recorded here |
| tokens | about 1.7 M output tokens; about 660 M tokens processed in total, almost all of it cached context re-read on each step (650 M cache reads, 10 M cache writes). The two author subagents account for about 54 M and 44 M of that total | not recorded here |
| commits | 47 | 73 |

The line-1 figures are summed from the local Claude Code session logs. Line 2 ran on another machine, and its
usage isn't available here.

## 1. The set-up

```
                                   me: roles, rules, policy decisions, merges, stop
                                  /                                                  \
   line 1 (this repository): one builder agent            line 2 (knowledge-main): a control plane over
   working in explained stages, stopping at each           six solver sessions I selected, frozen and
   judgment call for my decision                           reviewed stage by stage
            |                                                          |
            +--- code-review sessions (read-only) ---------------------+--- per-stage reviewers; a reviewer
            |                                                          |    scheduled every 30 minutes
            +--- independent test authors (no access to any code) -----+--- test authors legacy509, A, B, C
            |                                                          |
            +------------------ the same scorer, snapshots and banks for every candidate ------------------+
```

| role | agents | the rule I set for it |
|---|---|---|
| solvers | one builder here; six solver sessions in knowledge-main (bootstrap, main, parent, three parallel candidates) | each works in its own workspace; a candidate is frozen (copied and hashed) before it is evaluated; nobody edits another's workspace |
| reviewers | a separate code-review session per round here; independent stage reviewers and a scheduled reviewer there | a reviewer never writes the code it reviews, and reads it without changing it |
| test authors | an independent author here; four authors there; a fresh-set author at the end | questions and gold come from the snapshots only; blind halves are never shown to a solver |
| outside research | knowledge-main's study of 12 public implementations, and transfer cases from other public corpora | read as evidence; no outside code imported |
| me | | decide policy; choose between agents' outputs; carry findings between the two lines; decide merges and the end |

Why two lines: one long session drifts towards its own blind spots and grades itself with its own tests. Two
independent lines measured on the same banks show where each one is weak.

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
| 10-22 | the second repository's code | merge it, or ignore it | first absorb only its method (blind holdouts, mechanism suites, paired controls, rejecting gains with new wrong claims), not its code | avoid importing its tuning to its own bank before measuring it |
| 10-22 | the six solver sessions | six candidate builds | one session's conflict engine, another's answer engine, a third as the behaviour anchor; two candidates rejected after holdout and overfit review | combine strengths; never pick a candidate by its own report |
| 10-22 | stages that raised the score | e.g. formatting stages raising a replay to 0.977 through unsafe aliases | rejected | a higher score with a new wrong claim is not a gain |
| 10-22/23 | overfitting | keep tuning on development banks | a defence: paired controls in words no bank uses, blind banks as a final gate only, a study of what transfers | item-driven fixes were found to carry only 3% to 33% of their gain to blind banks |
| 10-23 | merging after all | — | once same-bank evidence showed where the other system was stronger, merge its runtime unchanged, admitting its handlers by measured evidence | take what it measurably does better, keep what this system does better |
| 10-23 | final evidence | stop at the existing banks | commission a fresh question set, register the comparison before any run, and allow each version one run | every existing bank had been looked at by someone |
| 10-23 | ties and dates before the first snapshot | the builder's earlier default (answer from the earliest copy, with a note) against the other repository's tests (decline) | decline both | the scoring credits "I don't know" when the site doesn't say; declining measured better on a blind bank (+0.056) |
| 10-23 | the other line's last steps | harness v2a, v2b and a final candidate | v2a rejected after an independent path review, v2b approved; the final candidate rejected after failing its developer gate (public 0.969 → 0.930); no further lanes | the gate decides, not the effort spent |
| 10-23 | when to stop | keep iterating | close both lines, stop the scheduled reviewer, write the final report | the remaining gains were small and the evidence budget was spent |

Things I kept for myself throughout: every policy decision above, every merge, the handling of the data (a
private repository, nothing redistributed), and when blind data could be used.

## 3. Several agents solving independently

- **Line 1** built the system in stages: page cleaning, typed rate rows, rate answers, sentence search, conflicts.
  It stopped at each judgment call; the decisions in §2 came from those stops. Public score: 0.13 → 0.957 → 0.969.
- **Line 2** started from an early copy of line 1's first solution. It ran six solver sessions as a tournament,
  with 816 full responses adjudicated by hand, then a third round of 27 recorded stages, most of them rejected.
  It selected runtime `2d6b8d6e`.
- **Disagreement was the useful output.** On the same banks, each line was stronger on the banks its own process
  tuned on. Line 2's typed handlers gave complete multi-part answers on its page families; line 1's generic rules
  kept working on synthetic sites (0.55–0.76 against 0.18–0.23). That told me what to take from each.

## 4. Reviewers that watch progress and prompt

- **Code reviews in line 1.** Two rounds by separate sessions found 8 and then 7 defects the builder's own checks
  had missed. Every finding became a fix plus a regression test, run against the previous commit to show it
  fails there.
- **Stage reviews in line 2.** A stage was adopted only if no score gate fell *and* no new wrong claim appeared.
- **A scheduled reviewer.** A cron job every 30 minutes observed line 2's maintainer session read-only. It
  re-measured public solutions under the same protocol and published concrete recommendations, for example:
  route routing-number and HELOC questions by the field asked, keep APY and opening minimums as separate columns,
  complete the logical paragraph.
- **Me as the relay.** I carried findings between the two lines ("the other side has updated, take a look"). The
  lines learned from each other without either editing the other's workspace.

## 5. Agents that write questions and look for similar material

- **Independent authors.** Here, 226 development and 176 holdout questions from an author session with no access
  to the code. There, legacy509 (333 / 176, with synthetic sites covering prompt injection, expired offers and
  removed pages), A (100 / 60), B (30 / 42) and C (36 / 36). About 1,400 items in all, each split into a
  development half and a blind half.
- **A fresh set at the end.** 172 questions with conflict gold, written after both systems were nearly final.
- **Outside material.** Line 2 pinned 12 public implementations of the same assessment and compared them in 39
  suites; public scores ranged from 0.33 to 0.969. It also built 32 new cases: 12 from the assignment's own
  sources and 20 from other public corpora (statistics tables, privacy policies, temporal clauses). They exposed
  a completeness gap: true snippets that don't finish the asked relation.
- **Mechanism suites.** Invented pages, one rule each (future-effective tables, ties, removed pages, source
  order). Several run here (`tests/knowledge_main/`).

## 6. Rounds of iteration

| phase | line 1 (this repository) | line 2 (knowledge-main) |
|---|---|---|
| build | staged build with my decisions at each stop; public 0.957 | baseline from that copy; review found four P1 defects |
| first review | 8 findings fixed; public 0.969, the file's ceiling without its judge | six-solver tournament, hand adjudication |
| independent tests | the independent author's banks; blind holdout 0.64 → 0.75 | 27 stages, most rejected; `2d6b8d6e` selected |
| absorb and merge | its method, then its runtime as a specialist; blind C-confirm 0.35 → 0.47 | new cases, 12 public implementations, harness v2a (rejected) and v2b (approved) |
| final | fresh set; second review (7 findings); its broad modules merged, weighed by coverage | last candidate rejected; `2d6b8d6e` final |

Every commit that changed the solution was later re-scored on every bank (ITERATIONS.md §1).

## 7. Overfitting, and how each problem was handled

| problem | how it showed | what was done |
|---|---|---|
| fixes driven by one failing item | they kept 3% to 33% of their development gain on blind banks; rules derived from the scoring rule kept 82% or more | prefer rules derived from the scoring rule. Every rule learned from an item gets **paired controls**, in words no bank uses: one equivalent form, one minimally changed form. The first run caught four rules that only worked in the bank's phrasing |
| templated banks | legacy-dev rose 0.812 → 0.855 from one question pattern repeated over products; its holdout stayed equal | count a templated gain once; trust the blind half |
| using blind banks to debug | once, blind aggregates were used to find a regression by reverting changes one at a time | a stricter gate: blind banks only as a final check, reject a change if any blind bank drops more than one item, never bisect on blind |
| a system judged on its own bank | line 2 scores 0.979 on its tuning bank and much less elsewhere | compare systems only on banks neither tuned on; label every bank by who tuned on it |
| score gains with new wrong claims | replay scores rose through unsafe aliases | rejected |
| spending a blind set by looking twice | each look lets choices fit it | pre-registration, and `tests/fresh_once.py`: it logs a START line before importing a version and refuses a second run of the same source hash |
| a merge judged on biased banks | the fresh set preferred more of line 2's modules (0.836); restricting them on development banks cost about two of 172 questions (0.828) | recorded as a finding (GENERALIZATION §9). The run had been declared descriptive beforehand, so nothing was rolled back |
| the builder's tests share the builder's blind spots | 240 checks passed while the second review found 7 combination bugs | separate reviewers; regression tests proven to fail on the old code |

## 8. Defects that remain

- **Complete multi-part answers.** C confirmation is 0.57 here against 0.78 for line 2. Line 2's own new cases
  show the same gap from its side: none of its answers to the 12 new cases from the assignment's sources was
  complete.
- **Lexical matching.** No embeddings; a question worded far from the page can miss.
- **Conflict recall.** F1 is 0.57 on development gold and the fresh set, but 0.16 on the holdout's gold.
- **One blind bank never moved** (author A's confirmation). Its weak spots are unknown, by the blind rule.
- **The last refinement** of the merge was measured only on banks this system had been tuned on. No unused
  neutral set remains to measure it.

## 9. What I would keep doing

- Separate the roles, and enforce the separation with tools, not intentions.
- Run independent solvers; their disagreements locate the mechanisms worth having.
- Keep policy decisions with a person, write them down, measure them, and keep each one as a switch.
- Reject a score gain that adds a wrong claim, and record rejected iterations as carefully as adopted ones.
- Judge on data nobody tuned on, and write the comparison down before running it.
