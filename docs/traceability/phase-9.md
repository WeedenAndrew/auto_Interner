# Phase 9 traceability

Phase 7 closed the container and operations work and Phase 8 is the
recruiter-facing proof, still in progress. Phase 9 is what was built once the
pipeline had run against the live snapshot rather than against fixtures, and it
landed before Phase 8 finished.

It has one theme: **the pipeline was correct but wasteful, and the rewrite gate
was strict without being discerning.** Nothing here changes what the project
refuses to do. No new configuration keys, no new runtime dependencies, no new
external boundaries.

| Contract | Implementation | Current evidence |
|---|---|---|
| Tier 0 decides everything decidable before a fetch | `screening/eligibility.py`, four rules over `terms`, degrees, category and employer | `tests/unit/test_eligibility.py` |
| Every rule that fires is recorded, not just the first | `screen_listing_eligibility` collects all fired rules into one decision | evidence-tuple assertions in `test_eligibility.py` |
| Unknown never disqualifies | missing, empty or unrecognised values leave the listing eligible | per-rule unknown-passes cases |
| Tier 2 verdicts are reused across listings | `screening/semantic_cache.py`, keyed on SHA-256 of posting text | `tests/unit/test_semantic_cache.py` |
| A cached verdict expires | `MAX_AGE = 7 days`, then re-screened | cache-age tests |
| Drift between a cached and a fresh verdict is recorded | `state_store.record_semantic_drift` | drift path in `test_semantic_cache.py` |
| A rewrite is judged on more than mechanical rules | `rewriting/grading.py`, a grader above the validator | `tests/unit/test_rewrite_loop.py` |
| The validator remains the hard gate | grader never overrides `validate_rewrite`; both must pass | rejection-precedence tests |
| Retry is bounded and shared across both gates | `MAX_ATTEMPTS = 2` counts attempts, not failures per gate | attempt-budget tests |
| Feedback to a retry carries no rewritten text | category-only feedback on the second attempt | feedback-content assertions |

## Why Tier 0 is one stage with two parts

`ScreeningTier` names them separately, `tier_0_eligibility` and
`tier_0_location`, because the evidence log should say which rule fired. They
are one stage because they share the property that defines the tier: both are
answerable from the snapshot alone, so both are free.

Tier 1 costs a fetch. Tier 2 costs a fetch plus a model call. Ordering by cost
is the whole design, and the naming follows it.

## The measurement, and what it is not

Against the live Summer 2027 snapshot on 2026-08-19, the first three
eligibility rules took **1,670 active listings to 339**, with the season rule
alone accounting for 1,100.

That number found a real defect rather than describing an optimisation. The
upstream repository is named for one recruiting cycle but carries every cycle,
and nothing in this project had been reading the `terms` field. Listings from
past seasons were being fetched, screened and in principle applied to.

The employer rule landed after that measurement. The live figure is therefore
lower than 339 and has not been re-measured. Do not quote 339 as current.

## Cost, stated plainly

Tier 2 is the only paid stage. Three things send the same posting text back to
it: a shadow run leaves every outcome nonterminal, so an unchanged snapshot is
re-screened next cycle; a retry later in the pipeline restarts a listing from
the top; and upstream publishes the same posting twice under separate IDs.

Keying the cache on posting content rather than listing ID handles all three,
and is the correct statement anyway, because Tier 2 only ever reads the posting.

## What Phase 8 does not do

- It adds no environment variables. `config.py` and `.env.example` are untouched, so
  every deployment document from Phase 7, including the Pi runbook, remains accurate.
- It does not wire `auto_interner.corpus` into anything. That module is still
  imported by nothing on the live path and is still scheduled to move to Curat0r.
- It does not relax the rewrite validator. The grader sits above it and can only
  reject what the validator already accepted.

## Outstanding

The grader is a model call, so it is subject to the same schema-validation
discipline as Tier 2 and fails closed on a malformed response
(`GradeResponseError`). It has not been exercised against a live provider over a
sustained run; that happens with the Phase 7 soak on the Pi, not before.
