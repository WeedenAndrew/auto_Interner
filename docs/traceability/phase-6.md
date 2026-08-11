# Phase 6 traceability

Phase 6 joins the established modules under one non-overlapping runtime. Every default
test uses fictional local data and fake external boundaries; no test reads a private
resume, credential, browser session, GitHub repository, or model service.

| Contract | Implementation | Evidence |
|---|---|---|
| `F-ORC-001` new valid listing | `ApplicationPipeline` through `assemble_resume` | generated company/role/date DOCX test |
| `F-ORC-002`–`004` staged early exits | ordered location, Tier 1, and Tier 2 gates | boundary call-count tests |
| `F-ORC-005` dedupe exit | `RoleDeduplicator` before rewrite | existing-output integration test |
| `F-ORC-006` invalid rewrite | local rewrite policy plus manual review | unsupported-plan integration test |
| `F-ORC-007` assembly failure | retry outcome before terminal commit | injected assembly failure test |
| `F-ORC-008` bounded window | `iter_unseen_windows` under the application pipeline | 100-listing exactly-once test |
| `F-ORC-009`–`011` repeat/add/reorder | terminal seen-ID filtering | repeated-snapshot integration test |
| `F-ORC-012` crash boundary | decision-before-seen commit plus idempotent recovery | `CommitPoint` fault-injection tests |
| `F-ORC-013` shadow run | validated nonterminal `shadow_ready` outcome | no-write/no-checkpoint tests |
| `F-ORC-014`, `NF-DAT-001` summary reconciliation | `RunSummary` and `StateStore.reconcile` | persisted count and mismatch tests |
| `F-CLI-001`–`003` run-once | CLI plus complete fictional coordinator | help, shadow, write, and error tests |
| `F-CLI-004`–`007` daemon | immediate serialized run/wait loop | command dispatch and scheduler-order tests |
| `F-CLI-008` backlog count | `manual-review-count` | configuration-free count test |
| `F-CLI-009` offline demo | bundled fictional fixtures through the shared pipeline | repeated offline CLI tests |
| `NF-REL-003` decision/seen crash | recovery-aware `commit_terminal` | no-duplicate recovery test |
| `NF-REL-011` non-overlap | portable operating-system `RunLock` | active-owner and stale-file tests |
| `NF-DAT-006` seen reconciliation | seen IDs must have terminal decisions | corrupt cross-file state test |
| `NF-OBS-001`, `005`, `007` operability | summaries, heartbeat, backlog command | runtime and CLI tests |

The Git processed-commit marker advances only after all returned outcomes are terminal,
those terminal outcomes exist in the seen set, and persisted state reconciles. A retry,
shadow result, exception, or state mismatch leaves the source version unprocessed so a
later run can safely revisit it.

Since [ADR-018](decisions.md#adr-018-one-pipeline-owns-every-stage) both offline
commands drive the same `ApplicationPipeline`. They differ only in fixture set and in
whether a write is permitted: `demo` uses the bundled multi-listing snapshot and is
always a shadow run, while `run-once --fixture` uses the single full-pipeline listing
and can publish:

```powershell
auto-interner run-once --fixture --data-dir runtime/fixture-data --state-dir runtime/fixture-state
auto-interner run-once --fixture --write --data-dir runtime/fixture-data --state-dir runtime/fixture-state
```

The first command exercises every stage without a final write. The second publishes a
fictional DOCX under `<data>/<year>/<company>/<role>_<MM-DD-YY>.docx` and checkpoints
the fixture source. Repeating the write command becomes an unchanged-source no-op.
