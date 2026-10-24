# Overfitting and generalization: what the evidence from two builds shows

The hidden set is unseen questions about the same five snapshots. "Generalization" here therefore means *new
wordings and new questions about this site*, not other websites. Overfitting means rules that fit the test banks'
wording, or one author's view of the answers, rather than the site and the scoring rules.

The evidence comes from this repository's per-commit scores on eleven agent-written banks (dev banks readable,
blind banks scored for aggregates only), from the companion runtime run on the same banks, and from paired
controls. The data is in [ITERATIONS.md](ITERATIONS.md) and [REPORT.md](REPORT.md).

## 1. Which changes transfer to unseen questions

Every solution commit was scored on the five dev banks and the five blind banks of the same authors (km226 has
no blind partner and is left out here). Across 18 commits with any change:

- The dev and blind changes correlate strongly: **r = 0.88**.
- Summed, **+0.248 on dev became +0.156 on blind**, so about 63% transferred.

The transfer depends on what kind of change it was:

| kind of change | commits | blind gain per unit of dev gain |
|---|---|---:|
| answer-policy rules from the scoring rules: answer only the asked metric and tier; cover every asked part | `13d2310`, `9d92679` | 1.08, 0.82 |
| mechanisms chosen by out-of-sample evidence: the companion's handlers that won outside its own tuning bank; its mechanisms reimplemented | `848491e`, `700c18f`, `62aa9cf` | 1.09, 1.45, 1.12 |
| fixes driven by individual failing dev items | `8d972e9`, `61c14d6`, `f372dea`, `357d758` | 0.17, 0.19, 0.03, 0.33 |
| one rule that hurt blind while dev was flat | `0bf2466` | blind −0.014 |

The lesson: **a rule derived from the scorer or from evidence across authors transfers almost fully. A rule
derived from one failing item mostly fits that item's wording.**

**Templated banks inflate dev gains.** Some authors generate one question pattern for every product. legacy-dev
asks "What is the published minimum to open X, regardless of ...?" for each savings product, and "the APY alone
for the regular N-month certificate, excluding specials and IRAs" for each term. One fix then lifts many items:
`6bb321d` raised legacy-dev by .044 and left its blind holdout equal. A dev gain is evidence of generalization
only when it comes from items that aren't copies of one template.

## 2. A system tuned on its own bank

The companion runtime was selected on its 226-question disclosed bank, km226. There it scores 0.979. On the same
kinds of question written by other authors, it scores much lower:

| route of the question | its own bank | the other authors' dev banks |
|---|---:|---:|
| text questions with a typed answer | 0.968 | 0.26 to 0.54 (C-dev 0.95) |
| open text questions | 0.969 | 0.27 to 0.74 (C-dev 0.93) |
| rate-table questions | 0.992 | 0.74 to 0.86 |

Its handlers are written for this site's pages, and that part transfers: C-confirm, new wordings of C-dev's fact
families, scores 0.778. Its general paths (generic search, fees, branches) don't. Two consequences:

- **Site knowledge is fine, bank-wording knowledge isn't.** Handlers keyed to this site's pages and layouts are
  legitimate for a hidden set on the same site. Triggers keyed to how one author phrased questions are not.
- **Merge by out-of-sample evidence.** This repository merged the companion's code but uses only eight of its
  handlers. Each was measured on every dev bank *except* the companion's tuning bank, and each beat this system
  there. Handlers with evidence only on km226 stayed out. The merge raised every blind bank or left it equal
  (C-confirm .369 → .468), as the table in §1 shows.

## 3. Wording-bound rules: what paired controls catch

Each rule learned from a bank item gets controls in words no bank uses: an equivalent form that must keep the
answer, and a minimally changed form that must change it. Running them found wording-bound rules on their first
run, every time:

| round | rules found bound to the bank's phrasing |
|---|---|
| first | "standard and jumbo" only when adjacent; days only when joined by a bare "and"; "is there a 96-month certificate" not seen as a rate question; "fee by phone" read as a phone-number question |
| second | "stack up against" not seen as a comparison; a synonym rewrite that swallowed the product name ("paying off a student loan early") |

None of these changed a bank score when fixed. That is expected: the bank's own wording already passed. The fix
matters only for the next wording, which is the hidden set's.

## 4. Answer format is not a generalization lever here

The harness matches a pure number ("4.10%", "$2.50") by value, and anything containing other characters as text.
The agent authors wrote many tokens with formats: "15.50%-21.00%", "48-month", "$500,000-$999,999.99". The
organizer's public file uses plain numbers almost exclusively.

Rewriting answers into the bank authors' formats would raise bank scores without making a single answer more
correct for the organizer's set, so it was not done. Bank scores therefore understate this system on such items.

## 5. Synthetic sites: robustness that the score barely sees

On the synthetic scenarios (made-up pages, prompt injection, removed pages, expired offers):

- this system scores 0.55–0.76;
- the companion runtime scores 0.18–0.30.

Generic rules about page shapes carry over to unfamiliar layouts; page-specific handlers don't. Because the hidden
set uses the real snapshots, this mostly protects against surprises (a reworded page, an unusual table) rather than
adding score. The organizer's synthetic self-test is 1.0 for both.

## 6. The test process can overfit too

- **Blind banks are a budget.** Every aggregate read leaks a little information.
  - They were used to choose between versions in one session, by reverting changes one at a time. Since then they
    are only a final gate: a change is rejected only if a blind bank drops by more than one item, and nothing is
    tuned against them.
  - They are no longer pristine. A fresh holdout written after the code freeze is the honest final measure.
- **The tools need integrity.** The companion's reviewer found that its anti-overfit harness could be reset
  (one-shot ledgers inside copyable folders, mutable seals). It paused development to rebuild the harness with
  external attempt records and checks on immutable inputs.
  - Here the blind outputs go to a temporary folder that nothing reads.
  - Per-question blind files are never written to the repository.
- **Tests written before a rule can encode the old behaviour.** The exact-tie mutation used a page that the newer
  "product's own page wins" rule correctly prefers. The test's premise was updated (two equally on-topic pages)
  and a test for the new rule was added; the rule wasn't weakened.

## 7. Rules for generalizing, as practised here

1. **Derive rules from the scorer and the site**, never from one item: minimal answers, complete answers, honest
   refusals, current-value precedence.
2. **Write paired controls before trusting a rule.**
3. **Measure on several authors**, and track each author's dev-to-blind transfer. A gap that keeps widening means
   the rules are fitting the dev wording.
4. **Merge or adopt by out-of-sample evidence**, excluding the bank the other system was tuned on.
5. **Prefer declining to guessing** when the evidence is thin: a wrong value costs more than a missing one. But
   don't decline answerable questions in other words. A yes/no coverage guard that did so was measured and removed.
6. **Keep a final holdout that nobody has looked at**, written after the code freeze, for the last claim.

## 8. Policy choices, measured, then decided by the owner

| switch | default (owner's decision, 2026-10-23) | alternative | effect of the default when it was measured as the alternative |
|---|---|---|---|
| `KB_BEFORE_FIRST` | decline a date before the first download | `earliest`: answer from the earliest copy, with a note (the 2026-10-20 decision) | km226 +0.020, legacy-dev +0.007, blind C-confirm +0.056 (0.468 → 0.524), rest equal; the companion's temporal suite passes 19/19 |
| `KB_TIE` | decline a true tie | `both`: show both values, with a note | no bank changes (the real data has no true ties); the companion's tie control passes |

Three independent authors expected a date before the first download to be declined, and the scoring rule gives
credit to "I don't know" when the site doesn't say. The owner chose to decline in both cases. The switches stay,
so the earlier behaviour can still be measured.

## 9. Judging a merge between two systems

The fresh blind set (REPORT §5.3) gave one more data point, and it cuts against this repository's own habit.

- **Before:** the companion's handlers were admitted one by one, on the dev banks outside the companion's tuning
  bank. Eight passed.
- **The neutral set disagreed.** Every handler module (D) beat the eight (B) on the fresh set: 0.836 against
  0.819 total.
- **The refinement went back towards the dev banks.** D broke nine paired controls, and on B-dev its broad modules
  answered FAQ questions with a product's rate table. Restricting them, and making them compete on coverage, raised
  every dev bank and left the blind banks no lower. On the fresh set it cost about two of 172 questions (0.836 →
  0.828; one descriptive run, decided nothing).

The dev banks are not neutral judges of a merge. This system was tuned on them, so its answers fit them, and any
answer from another system loses ties it might win elsewhere. The companion's own process makes the same point
from its side: km226 scores it 0.979 and every other bank much lower.

Rule taken from this: **a merge is judged on banks neither system was tuned on.** Fixes for faults the coder can
see (a rate table answering an FAQ question, a broken control) are still made, but their size should be measured
there too, not on the banks that already favour one side. Here no unused neutral set remained to measure the
final refinement on; that measurement is the open item.
