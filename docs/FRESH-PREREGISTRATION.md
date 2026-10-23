# Fresh blind set: pre-registered comparison (written before any result was seen)

Set: C:\Users\19257\Desktop\hackathon-fresh-eval (independent author session, 2026-10-23). Blind: only the
harness aggregates are read; questions, gold and per-question outputs are never opened.

Each variant is run once, with the unchanged organizer harness, on fresh_final.jsonl with conflicts.json:
- A  this system at the start of the session (de7c4f2)
- B  this system now (c1812e0): the companion merged through the eight evidence-chosen handlers
- C  the companion runtime alone (knowledge-main submission, 2d6b8d6e)
- D  B, but every companion handler module is used for text questions (no evidence filter)

Questions answered: did the session's work generalise to unseen questions (B vs A); how do the two systems
compare on a set neither was tuned on (B vs C); does absorbing more of the companion help (D vs B).
Decision rule fixed in advance: D replaces B only if it is better on total AND not worse on accuracy by more
than one question's weight; otherwise B stays. No further variant is run on this set.

Enforced by `tests/fresh_once.py`: each variant's source hash may run on this set once; a START line goes to
`hackathon-fresh-eval/LEDGER.jsonl` before the solution is imported, a repeat is refused, and only aggregates
are kept (per-question output is written to a temporary folder and deleted). This follows the companion
repository's one-shot heldback rule (its harness v2a, itself rejected on 2026-10-23 for path-safety defects
that matter only against an untrusted process on the same machine).
