# Temporal, source-grounded knowledge system

Use Python 3.11 and the organizer's unchanged harness. The entrypoint is
`solution.py:build()`. Ingest complete dated snapshots from oldest to newest,
then call `answer(question, as_of=None)` and `conflicts()` through that default
outer API. The package uses the Python standard library and supplied page text;
it needs no external model, network service, or third-party package.

The Parent runtime retains requested rate/yield/APY metric selection, calendar
date normalization, historical snapshot selection, and compound-question
composition that binds requested products, amounts, dates, and supporting
sources. Source input ownership is explicit: each Context copies the supplied
Page object graph, so later caller mutation cannot change its bound source
text, provenance, indexes, or cached observations. A later ingest still creates
a new observation. This ownership guarantee concerns copyable input graphs and
the tested default outer API.

The existing service-fee fallback is narrow. Only after an unsupported Parent
answer with no sources or conflict note may it select an unconditional base-fee
row from the immediately preceding complete snapshot, across one omission and
at most 90 observed days. Current fee evidence blocks historical borrowing.
The packaged Original-1 selector loads lazily; its general answer, ingest,
conflict, and rate-selection behavior is not used by this fallback. Unsupported
or conditional evidence preserves Parent's refusal. Conflict percentage display
normalization is also retained.

Known limits remain. Some current fee table headings, URL forms, and service
names are unsupported, even when a fee is present in the supplied source.
Verification-policy answers require supported explicit condition grammar;
source-step-only wording can remain unanswered. No private verification state,
customer charge, or account balance is inferred. The raw `build_parent()` helper
can expose mutable returned Source aliases; use default `build()` for copied
outer API outputs. An existing 1,000-page generic-search stress case exceeded a
two-second answer budget, and copying large input graphs adds ingest work.
Official-kit measurements do not establish a universal latency guarantee.

This is the unchanged 14-module runtime approved for the bounded source-input
ownership change. Its canonical Python-source SHA256 is
`2d6b8d6e15cbf78a6e6552904f127b6d6e9856ea68db769ca103c61b768d1115`.
The ownership change preserved the measured official score aggregates; it
does not claim a measured score increase or universal policy/fee coverage.
