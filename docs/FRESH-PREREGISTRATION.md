# Fresh blind set: pre-registered comparison (written before any result was seen)

Set: `Desktop/hackathon-fresh-eval`, outside the repository (independent author session, 2026-10-23). Blind: only the
harness aggregates are read; questions, gold and per-question outputs are never opened.

Each variant is run once, with the unchanged organizer harness, on fresh_final.jsonl with conflicts.json:
- A  this system at the start of the session (de7c4f2)
- B  this system now (c1812e0): the companion merged through the eight evidence-chosen handlers
- C  the companion runtime alone (the tournament line's selected runtime, 2d6b8d6e)
- D  B, but every companion handler module is used for text questions (no evidence filter)

Questions answered: did the session's work generalise to unseen questions (B vs A); how do the two systems
compare on a set neither was tuned on (B vs C); does absorbing more of the companion help (D vs B).
Decision rule fixed in advance: D replaces B only if it is better on total AND not worse on accuracy by more
than one question's weight; otherwise B stays. No further variant is run on this set.

Enforced by `tests/fresh_once.py`: each variant's source hash may run on this set once; a START line goes to
`hackathon-fresh-eval/LEDGER.jsonl` before the solution is imported, a repeat is refused, and only aggregates
are kept (per-question output is written to a temporary folder and deleted). This follows the tournament
line's one-shot heldback rule (its harness v2a, itself rejected on 2026-10-23 for path-safety defects
that matter only against an untrusted process on the same machine).

## Amendment, 2026-10-23 (written after A-D were run, before E is run)

Result of the rule above: D replaced B (.836 against .819 total, accuracy +.019). D was then refined without this
set, on the development banks and the paired controls only:
- the broad companion modules answer only open answer kinds, never its facts module or the general part of its
  services module (they broke nine paired controls);
- they win only when their answer holds at least as much of what was asked as this system's (on B-dev they had
  answered FAQ questions about a product with its rate table: B-dev .537 → .477 with the first refinement alone,
  .542 with this one);
- the seven issues of the 2026-10-23 code review are fixed (product exclusion, multi-product questions, announced
  promo columns, the question's date for every route, two balances, conflict merging, history sources).

One more run is allowed on this set, of the final version only, labelled E. It is descriptive: it shows whether
the refinements held on unseen questions. Its result is reported as it comes and decides nothing - no rollback to
D, no further change, no further variant. The comparison it allows (E vs D) is post hoc and is reported as such.
