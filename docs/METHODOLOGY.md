# Methodology: how to build a "what is true now" knowledge system, and how to know it works

This is the process that came out of two independent lines of agents on the same assessment (the staged line in
this repository and the tournament line). It's written so it could be followed again on another site or another snapshot set.
The evidence behind each point is in [REPORT.md](REPORT.md) and [ITERATIONS.md](ITERATIONS.md).

## 1. Read the scorer before writing code

The scoring rules decide the design. List what each rule rewards and punishes, and keep the list in view for
every change:

| rule | consequence for the design |
|---|---|
| any old or wrong value zeroes an answer, even next to the right one | answer the narrowest thing asked; never pad with other tiers, metrics or past values |
| "I don't know" scores only when the site doesn't say | decline when no text about the subject holds the asked kind of value, with no numbers in the refusal; but don't decline what the page says in other words |
| the right source earns extra | cite the page that answers first, then the pages that agree |
| conflicts: F1 plus the right winner | detect contradictions from the same structured records the answers use, so both share one notion of "current" |
| consistency and speed are multiplied by accuracy | determinism and latency matter only once answers are right; make them free (fixed tie-breaks, no model calls) |

Find the public set's ceiling: here, one item has no machine-scorable facts, so 0.969 is the maximum. Don't
chase what can't be scored.

## 2. Study the data before the questions

- Diff the snapshots. Find what changed (rate tables, boilerplate counts, closures, grant amounts) and where old
  values survive (stale pages, embedded copies, PDFs, news archives). These survivors are the traps.
- Find how the site dates things: an "effective as of" line under each table, publish dates on news, nothing on
  product pages. That decides the rules for what is current.
- Find the shapes values take: tables, one-line statements, bullets, prose. Find which page kinds hold which
  facts.

## 3. Architecture: structure what can be structured

1. **Snapshots as views.** Keep every download as the site on its date. Identical page versions are stored once.
   An `as_of` question reads the latest view on or before that date.
2. **Rate tables as typed rows**, never answered from raw text. Each row holds product, qualifiers, tier, term,
   model years, every metric, minimums and the effective date. A question is parsed into the same fields
   (family, product, qualifiers, term, amount, metric asked, metrics excluded), and only matching rows answer it.
3. **"Current" as an ordered rule list**:
   1. newest effective date (a table not yet in effect waits);
   2. page trust (rate sheet > product page > PDF > news > landing > blog > calculator);
   3. the product's own page over an embedded copy;
   4. a fixed tie-break.

   A real tie between equally trusted pages invents no winner. Products compete as whole tables, so a tier the
   newest table dropped isn't revived by a stale page.
4. **Text answers by answer shape.** Decide what kind of value is asked (time, amount, phone, date, address, link,
   count, rate). Search sentences that hold that shape *about the asked subject*, pick the page by the rules
   above, and answer with the sentence plus what completes it. Every asked part should be covered from the same
   section.
5. **Conflicts from the same records.** One conflict per precise fact printed with different values, either at
   once or across downloads. Each value is tagged current or outdated, and the winner is decided by the same rules
   as answers.

Keep it deterministic: sort with explicit tie-breakers and round float sums. Two hash seeds must give identical
answers.

## 4. Answer policy

- **Minimal.** Give only the asked metric (APY is not the dividend rate), tier, product and date. A change
  question gets the current value plus the previous one, labelled as the past. An ordinary question never shows
  old numbers.
- **Complete.** Every asked part ("the APY for $12,000 *and* the top tier's threshold", "the APR *and* its
  posting window") must be answered. Look for the missing parts in the same section, never in a neighbouring
  product's section.
- **Honest refusals.** Decline in these cases, with no numbers in the refusal:
  - the subject appears nowhere on the site;
  - no text about it holds the asked kind of value;
  - the asked year isn't given;
  - the only table wasn't in effect yet;
  - the date is impossible;
  - the question is about the asker's own account;
  - the next cycle "will be announced".
- **Robust input.** Accept dates written any way (as_of strings, "10 March 2035", "mid-May", "the August 27 and
  September 28 crawls"), amounts in words ("nineteen hundred dollars", "seven grand"), and misspellings of product
  names. Never crash: an unexpected error becomes a refusal.

## 5. Evaluation in layers

No single test set can be trusted, because each one is someone's view of the questions. Build layers that fail in
different ways:

1. **Organizer files**: the contract, a floor, the public ceiling.
2. **A stand-in hidden set**: every public question reworded, `as_of` questions on rows that changed, changed
   facts, refusals. It is cheap, but it shares your own blind spots.
3. **Independent test authors.**
   - A separate session that never sees the code writes questions with answers quoted from the snapshots.
   - Split each bank into dev, readable question by question, and holdout or confirmation, which runs for
     aggregates only and is never opened.
   - Use several authors: the tournament line's five authors disagreed with each other in useful ways.
4. **Synthetic scenarios**: made-up snapshots for situations the real data lacks, such as a removed page, a
   future-effective table, a true tie, an expired offer, or prompt injection in page text.
5. **Mechanism suites on invented banks**: one rule per test, independent of the real site's wording.
6. **Mutation tests**: one rule, one changed input.
7. **Paired controls**: for every rule, an equivalent rewording that must keep the answer and a minimal change
   (actor, qualifier, day, polarity, clause order) that must change it.
8. **Determinism**: the same answers under different hash seeds.

Run everything with one command, and run another system on the same layers (`tests/banks.py --submission`) to
compare like with like.

## 6. The iteration loop

1. **Trigger.** A failing dev item, a review finding or a mechanism test. Read the failure; find the mechanism,
   not the item.
2. **A general rule.** Write it in terms of page and question shapes. It must not mention a question id, URL or
   expected value.
3. **Paired controls first.** Write the equivalent and the minimally changed form in your own words, and check
   that the rule passes both.
4. **Measure on every layer**: checks, controls, public, stand-in, every dev bank.
5. **Blind gate, once.** Run the blind banks for aggregates.
   - Reject the change if any of them drops by more than one item.
   - Don't bisect on them and don't tune against them.
   - When a blind bank drops within noise, judge the rule on its generality.
6. **Commit** with the trigger, the mechanism, what was rejected and the scores. Record rejected attempts too:
   the dropped and narrowed rules listed in ITERATIONS.md are what make the kept ones believable.

Leave judgment calls to the owner and don't decide them silently. Examples: whether a page missing from a
download still exists; whether a tie shows both values; whether a date before the first download is answered.

## 7. Anti-overfitting rules

- **Never write code keyed to a question, URL or answer.**
- **Prefer saying less** over adding a guess. A wrong value costs more than a missing detail.
- **Track the dev-to-holdout gap for every bank.** Here: ours, about half the dev gain transferred; C, a fifth;
  A, none. A large gap means the rules fit the dev wording, not the mechanism.
- **Rewording tests catch wording-bound rules.** The first run of paired controls found four rules that only
  worked in the bank's phrasing.
- **A rule that improves one bank and hurts another is usually too broad.** Examples here:
  - "accept any key word that some typed text contains" answered unasked things;
  - "decline yes/no answers that don't cover the question" declined correct answers in other words.

  Narrow such a rule, or drop it.
- **Once a blind set has been used to choose between versions, it is partly spent.** Say so, and get a fresh one
  for the final claim. The companion's rule goes further: a held-set failure rejects that exact version, and it
  is never patched against the same set.
- **Pre-register the comparison on a fresh set, and let the tool enforce it.** Here the variants and the decision
  rule were written down before any result (`docs/FRESH-PREREGISTRATION.md`). `tests/fresh_once.py` logs a START
  line before importing a version and refuses a second run of the same source hash. One extra run was added by a
  written amendment before it ran, and it decided nothing.
- **Judge a merge between two systems on banks neither was tuned on.** Banks one side tuned on favour that side's
  answers. Here they favoured restricting the merged system, while the neutral set favoured more of it
  (GENERALIZATION §9).
- **A regression test should fail on the old code.** Each fix from the last code review got a test, and the test
  was run against the previous commit to show it fails there, while a minimally changed counterpart passes on
  both.

## 8. Pitfalls met along the way

- A text-normalisation step ("four-card" → "four card") made a count look like a product kind. Every
  normalisation needs a control for its side effects.
- Python set order made one answer change between runs, until every sort had an explicit tie-breaker.
- A heading without blank lines around it wasn't seen as a heading, and a filter dropped the right sentence.
- `\b` written through a shell heredoc became a backspace character inside regexes. Edit source with a tool that
  doesn't reinterpret escapes, and check for control characters.
- Absolute thresholds on idf break on small corpora. Make them relative to the corpus.
- A bank written before a new rule can encode the old behaviour (the exact-tie mutation used a page that the new
  "own page wins" rule correctly prefers). Update the test's premise; don't weaken the rule.
