# A Dupaco knowledge system that knows what's true *now*

The system answers members' questions from five dated snapshots of a credit union's website. Each answer gives
the value current on the date asked, the right tier and a source. When the site doesn't say, the answer is "I
don't know". The system also lists where the site contradicts itself.

## 1. How I orchestrated the agents

I built it by orchestrating AI agents (Claude Opus 5.5 and 6.1 Sol). I gave each agent a role, set what it may see
and what it must hand over, and kept the decisions. Two lines ran in parallel. In the staged line, one builder agent
stopped at each judgment call for me. In the other, six solver agents competed. Most of the work happened in
exchanges between agents, with a reviewer agent at the centre.

### The architecture

```
                               me: roles, rules, decisions
                                            |
                              reviewer agent (coordinator)
            briefs every agent, checks what each hands over, decides what is disclosed
                                            |
        +-------------------+---------------+---------------+-----------------------+
        |                   |                               |                       |
  large-scale          defect-targeted                solver agents A-F      staged-line builder
  question authors     question authors               one hint each          stops at each judgment
  broad banks          tests for the defect                                  call for me
                       the reviewer just found
        |                   |                               |                       |
        +---> banks and controls are checked and split by the reviewer:             |
              one part disclosed to the solvers, the rest only ever scored          |
                                            |                                       |
              solvers' frozen work ---> reviewer findings ---> fix + a test that proves it
                                            |
              the reviewer compares the solvers on one protocol and combines what holds up
```

### How the reviewer talks to each kind of agent

- **Large-scale question authors → reviewer.** They wrote broad banks from the snapshots. The reviewer checked each
  bank before any solver saw it: sources, gold answers, ambiguous items. It sent faulty items back for correction
  or set them aside, sealed the bank, and split it into a disclosed part and a hidden part.
- **Reviewer → defect-targeted question authors.** When the reviewer found a weakness in the solvers' answers, it
  briefed these authors on that defect. One example: answers that were true but left the asked relation
  unfinished. They wrote controls for exactly that defect before any fix was coded. One half went to the solver,
  and the reviewer kept the other half to judge the fix once.
- **Reviewer → solvers.**
  - It disclosed only part of the questions; the rest only produced a score, so no solver could tune to it.
  - It gave each solver a different hint on where to improve: consistency, conflicts, dates, multi-part
    answers, narrative completeness, evidence and uncertainty.
- **Solvers ↔ reviewer.** Each solver handed over frozen work. A reviewer audited it and reported every defect with
  a question that reproduces it. The solver returned a fix with a test proving it.
- **Reviewer → me.** It compared the solvers on one protocol and proposed what to keep. It rejected changes that
  raised the score but added a wrong claim. Once more questions stopped adding information, it moved the effort
  from bigger banks to targeted controls and mutations.

### The test-writing agents

None of them saw the solvers' code.

| agent | what it produced | why |
|---|---|---|
| large-scale authors | about 1,400 questions quoted from the snapshots, in several banks, each split into a disclosed and a hidden part | measure accuracy without the solvers' bias |
| defect-targeted authors | controls for the defect just found, written before the fix, with a held half; banks aimed at one known trap each (stale pages, tiers, dates, negations, multi-part answers); synthetic sites with prompt injection, expired offers and removed pages | probe one weakness at a time |
| web-search agents | similar material from outside: transfer cases from other public corpora (statistics tables, privacy policies, temporal clauses), and new cases from the assignment's own sources | test transfer beyond this site and its wording |
| generalisation agents | rewordings of every question; paired controls (an equivalent form and a minimally changed form); mutations of one input at a time; invented pages with renamed entities | catch rules that only work in one wording |
| fresh-set author | 172 new questions at the very end, scored once per version | one last measurement nobody had tuned on |

### One loop, end to end

A reviewer agent reported that "What is the APY for a regular 6-month certificate, not Bright Savings?" returned
Bright Savings' 2.25%. The report gave the code line and a control without "not Bright Savings". The builder fixed
it, added both questions as paired controls, and showed the new test failing on the previous commit before
committing.

### My part

I chose the roles and this architecture, decided what each round disclosed, and carried findings between agents. I
also made the calls agents shouldn't make alone:

- what "current" means;
- when to say "I don't know";
- whose tests to trust;
- what to merge, and what to reject;
- when to stop.

In total the agents ran for about 24 hours and used about 800 M tokens. Details are in
[docs/PROCESS.md](docs/PROCESS.md).

## 2. What the agents produced

### Performance

The supplied website snapshots are not in this repository. To run, copy the kit's `snapshots_zip/` folder into
the repository root, then:

```
python harness/run_eval.py --submission solution --eval eval/public_eval.jsonl
```

From a fresh clone plus the kit's snapshots, this scores **0.969**, with 0 stale-trap hits and 0 errors. Ingest
takes about 20 s, and answers take about 0.1 s at p95.

| | score |
|---|---|
| public set, 40 questions | **0.969**, the most this file allows without its LLM judge |
| fresh blind set, 172 questions written last, one run per version | **0.828** total (the best competing solver's runtime alone: 0.775) |
| blind holdouts (never opened), first solution → now | independent author 0.642 → **0.785**; legacy509 0.189 → **0.628**; author C 0.266 → **0.569** |

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

`harness/`, `eval/` and `starter/` are the kit as provided, unchanged ([kit README](docs/KIT-README.md)). The
snapshots are a real credit union's website, shared for this assessment only. They are not included here, and
their history was removed from the repository; there are no API keys.
