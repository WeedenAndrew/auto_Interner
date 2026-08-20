# Auto Interner implementation roadmap

Work advances one phase at a time. A phase is complete only when its stated behavior
and matching tests pass; planned items remain labeled as planned.

## Efficient route

| Phase | Smallest useful deliverable | Release gate | Status |
|---|---|---|---|
| 0 | Package, settings, logging, quality tools | `F-CFG-*`, format, lint, type, tests | Complete: 24 tests, 90.3% coverage |
| 1 | Offline listing-to-decision vertical slice | `F-SRC-*`, `F-SCN-*`, `F-L0-*`, `F-L1-*`, initial `F-STA-*` | Complete: 118 tests total, 94.9% coverage |
| 2 | Validated source plus static/browser fetch | `F-FET-*`, SSRF, redirect, timeout, size, cleanup | Complete: 193 tests total, 93.7% coverage |
| 3 | Safe company/role paths and six-month dedupe | `F-DED-*`, `F-PTH-*`, cycle isolation | Complete: 260 tests total, 92.3% coverage |
| 4 | Anthropic adapter and strict Tier 2 schema | `F-L2-*`, injection tests, zero default live calls | Complete: strict adapter and offline adversarial tests |
| 5 | PII separation, rewrite validator, DOCX patching | `F-RWR-*`, `F-DOC-*`, privacy and visual checks | Complete: fictional DOCX opens cleanly in Word |
| 6 | Single-writer orchestration, state, lock, CLI | `F-ORC-*`, `F-CLI-*`, fault injection, reconciliation | Complete: full offline gate |
| 7 | Arm64 image and Pi operations | container, arm64, restart, bind mount, resource, soak | Implementation complete; target gates pending |
| 8 | Recruiter-facing proof | offline demo, worked example, claim audit | In progress: worked example shipped |
| 9 | Cost-tiered screening and graded rewrites | Tier 0 eligibility, Tier 2 verdict cache, rewrite grader, bounded retry | Complete: [phase-9 traceability](traceability/phase-9.md) |

## Automatic submission is out of scope

Not a numbered phase, and not a gap. Automatic application submission violates
the terms of service of most application portals, and auto-submitted
applications get flagged as spam — worse than not applying at all.

The expensive, error-prone work is finding, screening, and tailoring, and that
is what this automates. Submission is three minutes of human review per
application, and keeping a human at that step is correct design.

The project was complete at Phase 7 plus recruiter-facing proof. Phase 9 was
added afterwards and out of order: running against the live snapshot showed the
pipeline was correct but wasteful, and that the rewrite gate was strict without
being discerning. It introduced no configuration and no dependencies, so every
Phase 7 deployment document remains accurate.


After Phase 2, the source transport was extended with a hardened shallow Git cache and
an unchanged-commit fast path. That extension passed a separate 216-test gate before
Phase 3 began and did not change the phase numbering.

The sequence puts pure, deterministic rules first. Network, browser, model, and DOCX
complexity are introduced only after the local decision core is testable. That keeps
failures narrow and avoids debugging several external boundaries at once.

## Phase-by-phase working loop

For every phase:

1. Select the exact case IDs in scope and create only the interfaces they require.
2. Add fictional fixtures and failing tests before production behavior.
3. Implement one vertical behavior at a time with injected clocks and adapters.
4. Run format, lint, static typing, the focused cases, then the full offline suite.
5. Review privacy, path, state, and false-disqualification risks before advancing.
6. Update README claims and the decision log to match demonstrated behavior.

## Engineering progression

Each phase should leave public, reviewable evidence instead of relying on planned
claims:

| Phase | Engineering evidence |
|---|---|
| 0-1 | packaging, strict typing, traceable tests, and pure domain models |
| 2-3 | SSRF defenses, redirect validation, path containment, and property tests |
| 4 | strict structured outputs, prompt-injection resistance, and fake model clients |
| 5 | OOXML preservation, PII minimization, and truthfulness invariants |
| 6-7 | atomic commits, locks, observability, arm64 operations, and recovery drills |
| 8 | reproducible demo, architecture narrative, evaluation results, and known limits |

Public documentation must claim only behavior that can be demonstrated from the
repository at that revision.

## Completed Phase 1 slices

Phase 1 contains:

1. `Listing`, `ScreeningEvidence`, `ScreeningDecision`, and `PipelineOutcome` models.
2. Strict fixture snapshot parsing with duplicate-ID anomaly reporting.
3. Pure `batched()` and unseen-listing selection functions.
4. Read-only seen-ID loading plus a single-writer terminal commit boundary.
5. Conservative Tier 0 location classification with a zero-false-disqualification set.
6. Data-driven Tier 1 patterns with a positive and negative case per rule.
7. An offline demo that uses fake posting text and proves a second run skips only
   terminal outcomes.

The main early risk is not performance; it is accidentally making a false
disqualification permanent. Unknown locations and ambiguous language must pass forward.

## Completed Phase 2 slices

Phase 2 contains:

1. Bounded live snapshot retrieval with schema parsing and integrity metadata.
2. Public-address URL validation before every connection and redirect.
3. Pinned-address HTTP and HTTPS connections with hostname-aware TLS validation.
4. Static HTML/text extraction with encoding, timeout, media, and size controls.
5. Optional Selenium fallback with injected sessions and guaranteed cleanup.
6. Posting-fetch integration with the existing cross-run retry and manual-review state.
7. A live `source-check` command that reports counts and integrity metadata without
   exposing listing bodies.

## Completed Phase 3 slices

Phase 3 contains:

1. Unicode-normalized, Windows-safe company and role components with bounded unique
   suffixes for long values.
2. Write-free output planning plus explicit lazy directory preparation and collision
   refusal.
3. Order-invariant normalized-role comparison without v1 stemming.
4. Current-company/current-cycle lookup with safe malformed-file anomaly reporting.
5. A strict six-calendar-month boundary with end-of-month clamping.
6. A terminal `dedupe_skipped` outcome accepted by the single state owner.

## Completed Phase 4 slices

Phase 4 contains:

1. A provider-neutral structured-model protocol with deterministic fake support.
2. A bounded Anthropic Messages adapter that calls a fixed endpoint and forces one
   named strict client tool.
3. An exact three-category Tier 2 schema with no extra or missing fields.
4. A conservative confidence policy: low confidence never auto-disqualifies.
5. Prompt-injection containment that serializes the posting as untrusted JSON data.
6. Pipeline integration after Tier 1 with retry and manual-review classification.

The full scheduled runtime still waits for Phase 6, where the established modules are
sequenced under one lock and state owner.

## Completed Phase 5 slices

Phase 5 contains:

1. Stable DOCX section and paragraph extraction with the contact block excluded from
   the model payload.
2. Redaction and rewrite refusal for body contact data and hyperlink paragraphs.
3. An exact structured rewrite schema and local truthfulness validation for sections,
   numeric claims, technologies, proficiency, and contact information.
4. In-place paragraph patching and section-block movement on a copy of the source DOCX.
5. Page-geometry, contact, section-order, replacement, CRC, and reopen validation before
   publication.
6. Metadata, custom-property, revision-ID, and ZIP-timestamp scrubbing.
7. Collision-safe hard-link publication plus write-free shadow behavior.
8. A clearly fictional one-page fixture and repeatable generated-output builder.

The generated fixture was opened and visually checked in Microsoft Word after automated
reopen checks. This caught and blocked an early namespace-serialization defect before
the phase was accepted.

## Completed Phase 6 slices

Phase 6 contains:

1. One application pipeline ordering location, fetch, deterministic screening,
   semantic screening, dedupe, validated rewrite, and DOCX publication.
2. A portable nonblocking process lock covering source acquisition through the final
   state and source-version checkpoint.
3. Recovery-aware terminal commits that do not duplicate a decision after a crash
   between the decision log and seen-ID append.
4. Cross-file reconciliation proving every seen ID has a terminal decision before a
   source version can be marked processed.
5. Persisted run summaries, durations, heartbeats, status counts, and a privacy-safe
   manual-review backlog command.
6. Immediate serialized daemon scheduling that waits only after the prior run returns.
7. A full fictional fixture command supporting both write-free shadow validation and
   a real company/role/date DOCX output.

Shadow outcomes deliberately remain nonterminal and do not advance the Git processed
marker. This makes a dry run repeatable and prevents validation from consuming work.

## Phase 7 implementation ready for target validation

Phase 7 now contains:

1. A Python 3.12 multi-architecture image with Git, Chromium, chromedriver, Tini, and a
   fixed non-root application identity.
2. A hardened Compose worker with no ports, a read-only root, dropped capabilities,
   SSD-configurable bind mounts, resource limits, health checks, restart policy, and
   bounded Docker logs.
3. Offline fixture and browser-smoke services that run with networking disabled.
4. Browser fallback composition through explicit container paths and configuration.
5. Graceful daemon handling for `SIGINT` and `SIGTERM`.
6. x86_64 container CI and a manual self-hosted arm64 validation workflow.
7. An Ubuntu Server 24.04 LTS runbook covering SSD setup, base résumé placement,
   backups, recovery, upgrades, and a twelve-cycle shadow soak.

The phase remains open until the new Raspberry Pi server passes its arm64 build/browser
smoke, restart and rebuild persistence drills, resource measurements, and 24-hour soak.
