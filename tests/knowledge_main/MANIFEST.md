# Test suites from the companion repository (knowledge-main)

Copied unchanged from `github.com/yushengzheng421-cmd/knowledge` (same owner) at the commit in `SOURCE_COMMIT`.
Run against this solution with `python tests/knowledge_main/run.py [-v]`.

| Suite (copied) | From | Earlier versions of the same family | How it runs here |
| --- | --- | --- | --- |
| program_status/test_program_status.py (22) | archive/2026-10-22/round3-program-status-new-cycle/tests | iteration1, iteration2 | behaviour through build/ingest/answer |
| program_status/test_qualified_programs.py (23) | same | - | behaviour |
| program_status/test_program_notice_variants.py (3) | same | iteration2 | behaviour |
| source_planner/test_iteration2b_frozen.py (25) | archive/2026-10-22/round3-source-planner-iteration2b/tests | iteration1 (reconstructed), 2a | behaviour, via adapter/ (accepts its build flags); 11 tests use its internal request_planner module: not applicable |
| fee/test_fee_mechanism.py (19) | experiments/round2-fee-compatibility/iteration3-review/tests | fee iteration1, 2 (rejected) | not applicable: compares its fee lane with its Parent runtime |
| percent_display/test_percent_display.py (7) | experiments/round2-fee-compatibility/iteration4-display-review/tests | - | not applicable: unit tests of its module |
| narrative/test_mechanism.py (16) | archive/2026-10-22/narrative-rejected/tests | - | not applicable: unit tests of its adapter |
| parent_custody/limited_mechanism_controls.py (13) | rounds/2026-10-22-round3/test-custody/parent-45e1/tests (commit 5a139a8) | - | behaviour; suites/submission/solution.py points ROOT/'submission' at this solution |
| parent_custody/source_order_controls.py (3) | same | - | behaviour |
| parent_custody/temporal_controls.py (19) | same | - | behaviour |

The question banks (the 226-question disclosed development suite with its 16-topic conflict proxy, legacy509,
round-2 authors A and B, round-3 author C) are now published there too; `tests/banks.py` scores them with the
organizer harness (holdout and confirmation banks: aggregates only).

The Parent45e1 custody suites are synthetic, product-agnostic controls (made-up banks "summit.example",
"ice.example") for the mechanisms the other runtime selected on: balance tier plus top tier, both-snapshot
history, two offer clocks, API date precedence, per-clause dates, invalid dates, future-effective tables, source
order and ties, unannounced cycles, private account state. 30 of 35 pass here (13 before they were added). The
five that don't: two policy differences (a true tie and a date before the first download are declined there,
answered with a note here), one wording requirement ("product-specific"), one semantic gap ("what range
follows" vs "ongoing rate"), and a yes/no question whose condition the page doesn't state - the coverage guard
that declined it also declined seven correctly answered dev-bank yes/no questions, so it was removed.

The program-status and source-planner suites were written as specifications before the other runtime's
repairs; that runtime rejected every attempted repair of program status because each one lowered its
core score. They are diagnostics here too: a change is not accepted for passing more of them if it
lowers the public, stand-in, independent dev or holdout scores.
