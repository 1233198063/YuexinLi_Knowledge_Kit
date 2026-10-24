# A Dupaco knowledge system that knows what's true *now*

The system answers members' questions from five dated snapshots of a credit union's website. Each answer gives
the value current on the date asked, the right tier and a source. When the site doesn't say, the answer is "I
don't know". The system also lists where the site contradicts itself.

I built it by orchestrating AI agents (Claude Opus 5.5 and 6.1 Sol). I designed their roles, made the policy
decisions and chose what to keep.

```
python harness/run_eval.py --submission solution --eval eval/public_eval.jsonl
```

From a fresh clone this scores **0.969**, with 0 stale-trap hits and 0 errors; ingest takes 18 s and answers 0.08 s
at p95. It uses the standard library only, with no API keys and no network. The solution is in
[`solution/`](solution/).

| | score |
|---|---|
| public set, 40 questions | **0.969**, the most this file allows without its LLM judge |
| fresh blind set, 172 questions written last, one run per version | **0.828** total |
| blind holdouts (never opened), first solution → now | ours 0.642 → **0.785**; legacy509 0.189 → **0.628**; author C 0.266 → **0.569** |

## How I did it

1. **I read the scorer first.** A stale or extra value zeroes a question. So the system says only what was
   asked, and says "I don't know" when the site doesn't say. I wrote down what "current" means for this site
   before any tuning.
2. **I ran two independent lines of agents.** In the staged line, a builder stopped at every judgment call for my
   decision. In the tournament line, six solver sessions competed over three rounds. Their disagreements showed
   what each lacked, and I merged the tournament line's best runtime by measured evidence.
3. **No agent judged its own work.** Separate sessions reviewed the code. Test authors who never saw the code
   wrote about 1,400 questions with blind halves. A fresh set came last, with the comparison written down before
   it ran.
4. **I kept the decisions.** I made the policy calls and the merges. I rejected gains that added a wrong claim,
   and I defended against overfitting with paired controls and blind banks used only as a final gate.
5. **The system.** Rate tables become typed rows decided by effective date, then page trust. Other facts come
   from the sentence or section that holds them. Conflicts come from the same rows.

**Went well:** tiers, stale-value traps, `as_of` questions and refusals are near-perfect, and the blind gains are
real. The system is robust to synthetic sites and prompt injection.

**Didn't:** complete multi-part answers (author C's blind set: 0.57, against 0.78 for the best tournament
runtime alone), wording far from the page (matching is lexical), and conflict recall on unseen gold (F1 0.16).

## More

- [docs/PROCESS.md](docs/PROCESS.md): how I used agents; my decisions with the options and reasons; the
  tournament line round by round; overfitting; time and tokens.
- [docs/RESULTS.md](docs/RESULTS.md): all scores, the question banks used, performance by kind of question, what
  went well and what didn't.
- [solution/NOTES.md](solution/NOTES.md): how the system decides what is current.
- [docs/REPORT.md](docs/REPORT.md) and [docs/ITERATIONS.md](docs/ITERATIONS.md): the full report and the
  per-commit ledger.

`harness/`, `eval/`, `starter/` and `snapshots_zip/` are the kit as provided, unchanged
([kit README](docs/KIT-README.md)). The snapshots are a real credit union's website, shared for this assessment
only. This repository is private, and the data is not redistributed.
