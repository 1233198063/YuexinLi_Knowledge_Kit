# A Dupaco knowledge system that knows what's true *now*

The system answers members' questions from five dated snapshots of a credit union's website. Each answer gives
the value current on the date asked, the right tier and a source. When the site doesn't say, the answer is "I
don't know". The system also lists where the site contradicts itself.

## 1. How I used agents to build it

I didn't hand the task to one AI session. I organised agents (Claude Opus 5.5 and 6.1 Sol) into roles that check
each other, and I kept the decisions for myself.

| role | what the agents did | what I did |
|---|---|---|
| solvers | **Staged line:** one builder worked in explained stages and stopped at every judgment call. **Tournament line:** six solver sessions competed over three rounds; the 27 hardening stages of round 3 were mostly rejected | decided each judgment call; picked what to combine from the tournament; merged its best runtime into the staged line, handler by handler, by measured evidence |
| reviewers | separate sessions reviewed every round of code (8, then 7 defects the builder had missed); a reviewer scheduled every 30 minutes watched the tournament line | required a fix plus a regression test for every finding; carried findings between the two lines |
| test authors | sessions that never saw any code wrote about 1,400 questions with blind halves; a fresh set of 172 came last | used blind halves only as a final gate; had the fresh-set comparison written down before it ran |

The decisions I kept:

- **What "current" means.** Newest effective date first, then page trust, and an expired offer never answers.
- **When to say "I don't know".** Only when the site truly doesn't say. True ties and dates before the first
  snapshot are declined.
- **Whose tests to trust.** Independent authors, not the builder's own stand-in set: that set showed 0.96 while
  the independent bank showed 0.75.
- **What to merge.** First only the tournament line's method, then its runtime, once same-bank evidence showed
  where it was stronger.
- **What to reject.** Any score gain that came with a new wrong claim, and any rule that only worked in one bank's
  wording.
- **When to stop.** Both lines closed when the remaining gains were small.

The staged line ran from 2026-10-18 to 10-23: about 15.5 hours of active agent sessions and about 1.7 M output
tokens. The tournament line ran in parallel. Every decision, with the options and the reasons, and the tournament
line round by round, are in [docs/PROCESS.md](docs/PROCESS.md).

## 2. Performance

```
python harness/run_eval.py --submission solution --eval eval/public_eval.jsonl
```

From a fresh clone this scores **0.969**, with 0 stale-trap hits and 0 errors; ingest takes 18 s and answers 0.08 s
at p95.

| | score |
|---|---|
| public set, 40 questions | **0.969**, the most this file allows without its LLM judge |
| fresh blind set, 172 questions written last, one run per version | **0.828** total (the best tournament runtime alone: 0.775) |
| blind holdouts (never opened), first solution → now | ours 0.642 → **0.785**; legacy509 0.189 → **0.628**; author C 0.266 → **0.569** |

**Went well:** tiers, stale-value traps, `as_of` questions and refusals are near-perfect, and the blind gains are
real. The system is robust to synthetic sites and prompt injection.

**Didn't:** complete multi-part answers (author C's blind set: 0.57, against 0.78 for the best tournament runtime
alone), wording far from the page (matching is lexical), and conflict recall on unseen gold (F1 0.16).

All scores, the question banks and performance by kind of question are in [docs/RESULTS.md](docs/RESULTS.md).

## 3. Approach

The scorer zeroes a question for any stale or extra value. So the system says only what was asked, and "I don't
know" when the site doesn't say. It uses the standard library only, with no API keys and no network.

1. Each snapshot is kept as a dated view of the site. An `as_of` question uses the newest snapshot on or before
   that date.
2. Rate tables become typed rows (product, term, tier, APY / APR, minimums, effective date). Rate questions are
   answered only from these rows: the newest effective date wins, then page trust (rate sheet > product page >
   PDF > news > blog > calculator). A table not yet in effect waits.
3. Other facts come from the sentence or section that holds them, filtered by the kind of value asked for.
4. Conflicts come from the same rows and from boilerplate whose numbers changed. Each names its winner and why.
5. The tournament line's best runtime is merged unchanged as a specialist for the text questions it answers
   better.

Details: [solution/NOTES.md](solution/NOTES.md). Full report and per-commit ledger:
[docs/REPORT.md](docs/REPORT.md), [docs/ITERATIONS.md](docs/ITERATIONS.md).

`harness/`, `eval/`, `starter/` and `snapshots_zip/` are the kit as provided, unchanged
([kit README](docs/KIT-README.md)). The snapshots are a real credit union's website, shared for this assessment
only. This repository is private, and the data is not redistributed.
