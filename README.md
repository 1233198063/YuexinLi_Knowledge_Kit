# A Dupaco knowledge system that knows what's true *now*

The system answers members' questions from five dated snapshots of a credit union's website. Each answer gives
the value current on the date asked, the right tier and a source. When the site doesn't say, the answer is "I
don't know". The system also lists where the site contradicts itself.

## 1. How I orchestrated the agents

I built it by orchestrating AI agents (Claude Opus 5.5 and 6.1 Sol). I gave each agent a role, set what it may see
and what it must hand over, and kept the decisions. Most of the work then happened in exchanges between agents:

```
                         me: roles, rules, decisions
                                     |
                         reviewer agent (coordinator)
    discloses part of the questions, gives each solver a different hint, pulls their ideas together
                                     |
      +------------------+-----------+-----------+----------------------+
      |                  |                       |                      |
   solver A          solver B       ...      solver F        staged-line builder
  (own hint)        (own hint)              (own hint)     (stops at each judgment call for me)
      |                  |                       |                      |
      +------- reviewer findings back to each solver; fixes come back with a test -------+
                                     |
    test-writing agents: independent, targeted, web-search, generalisation (some disclosed, the rest only scored)
```

- **The reviewer disclosed part of the questions.** Solvers saw a development part and could study every miss in
  it. The rest stayed hidden and only produced a score, so no solver could tune to it.
- **Different solvers got different hints.** Each was pointed at a different weakness: consistency, conflicts,
  dates, multi-part answers, narrative completeness, evidence and uncertainty. They improved the same problem
  from different sides.
- **Findings went back and forth.** A reviewer audited each solver's frozen work and reported every defect with a
  question that reproduces it. The solver fixed it and returned a test proving the fix.
- **The reviewer pulled the ideas together.** It compared the solvers on one protocol, kept the parts that held
  up, and rejected the rest, including changes that raised the score but added a wrong claim.
- **Test-writing agents, each with a different purpose.** None of them saw the solvers' code.

| agent | what it produced | why |
|---|---|---|
| independent authors | about 1,400 questions quoted from the snapshots, in several banks, each split into a disclosed part and a hidden part | measure accuracy without the solvers' bias |
| targeted authors | questions aimed at one known trap each: stale pages, tiers, dates, negations, multi-part answers; synthetic sites with prompt injection, expired offers and removed pages | probe one weakness at a time |
| web-search agents | similar material from outside: 12 public solutions to the same assessment, an author-published 94-question set, and transfer cases from other public corpora (statistics tables, privacy policies, temporal clauses) | test transfer beyond this site and its wording |
| generalisation agents | rewordings of every question; paired controls (an equivalent form and a minimally changed form); mutations of one input at a time; invented pages with renamed entities | catch rules that only work in one wording |
| fresh-set author | 172 new questions at the very end, scored once per version | one last measurement nobody had tuned on |

**One loop, end to end.** A reviewer agent reported that "What is the APY for a regular 6-month certificate, not
Bright Savings?" returned Bright Savings' 2.25%. The report gave the code line and a control without "not Bright
Savings". The builder fixed it, added both questions as paired controls, and showed the new test failing on the
previous commit before committing.

**My part.** I chose the roles and these rules, decided what each round disclosed, and carried findings between
agents. I also made the calls agents shouldn't make alone:

- what "current" means;
- when to say "I don't know";
- whose tests to trust;
- what to merge, and what to reject;
- when to stop.

The staged line took about 15.5 hours of active agent sessions and about 1.7 M output tokens (2026-10-18 to
10-23). The other agents ran in parallel. Details are in [docs/PROCESS.md](docs/PROCESS.md).

## 2. What the agents produced

### Performance

```
python harness/run_eval.py --submission solution --eval eval/public_eval.jsonl
```

From a fresh clone this scores **0.969**, with 0 stale-trap hits and 0 errors; ingest takes 18 s and answers 0.08 s
at p95.

| | score |
|---|---|
| public set, 40 questions | **0.969**, the most this file allows without its LLM judge |
| fresh blind set, 172 questions written last, one run per version | **0.828** total (the best competing solver's runtime alone: 0.775) |
| blind holdouts (never opened), first solution → now | ours 0.642 → **0.785**; legacy509 0.189 → **0.628**; author C 0.266 → **0.569** |

**Went well:** tiers, stale-value traps, `as_of` questions and refusals are near-perfect, and the blind gains are
real. The system is robust to synthetic sites and prompt injection.

**Didn't:** complete multi-part answers (author C's blind set: 0.57, against 0.78 for the best competing solver's
runtime alone), wording far from the page (matching is lexical), and conflict recall on unseen gold (F1 0.16).

All scores, the question banks and performance by kind of question are in [docs/RESULTS.md](docs/RESULTS.md).

### How the system works

The scorer zeroes a question for any stale or extra value. So the system says only what was asked, and "I don't
know" when the site doesn't say. It uses the standard library only, with no API keys and no network.

1. Each snapshot is kept as a dated view of the site. An `as_of` question uses the newest snapshot on or before
   that date.
2. Rate tables become typed rows (product, term, tier, APY / APR, minimums, effective date). Rate questions are
   answered only from these rows: the newest effective date wins, then page trust (rate sheet > product page >
   PDF > news > blog > calculator). A table not yet in effect waits.
3. Other facts come from the sentence or section that holds them, filtered by the kind of value asked for.
4. Conflicts come from the same rows and from boilerplate whose numbers changed. Each names its winner and why.
5. The best competing solver's runtime is merged unchanged into the staged line, as a specialist for the text
   questions it answers better.

Details: [solution/NOTES.md](solution/NOTES.md). Full report and per-commit ledger:
[docs/REPORT.md](docs/REPORT.md), [docs/ITERATIONS.md](docs/ITERATIONS.md).

`harness/`, `eval/`, `starter/` and `snapshots_zip/` are the kit as provided, unchanged
([kit README](docs/KIT-README.md)). The snapshots are a real credit union's website, shared for this assessment
only. This repository is private, and the data is not redistributed.
