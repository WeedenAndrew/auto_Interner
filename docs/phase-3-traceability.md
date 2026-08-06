# Phase 3 traceability

**Gate result (2026-08-06):** formatting passed, lint passed, strict source and test
typing passed, and 260 tests passed with 92.3% combined line/branch coverage on Python
3.12. The path and dedupe modules reached 99% and 98% coverage respectively. The default
suite made no live network, browser, model, or résumé call; filesystem cases stayed
inside pytest-managed temporary roots.

| Requirement | Implementation | Automated evidence |
|---|---|---|
| Normal portable output path | `OutputPathPlanner.plan` | `F-PTH-001`, `F-PTH-002` |
| Traversal and absolute-text containment | `safe_path_component`, containment guard | `F-PTH-003`, `F-PTH-004` |
| Windows and Unicode path safety | component normalization | `F-PTH-005` through `F-PTH-007` |
| Stable fallback and bounded uniqueness | component fallback and digest suffix | `F-PTH-008`, `F-PTH-009` |
| Lazy directory creation | `OutputPathPlanner.prepare` | `F-PTH-010` |
| Collision refusal | `OutputCollisionError` | `F-PTH-011` |
| Same company and role within cutoff | `RoleDeduplicator` | `F-DED-001` |
| Older, distinct-role, and distinct-company pass | `RoleDeduplicator` | `F-DED-002` through `F-DED-004` |
| Noise, order, punctuation, and case | `normalize_role` | `F-DED-005` through `F-DED-007` |
| No v1 stemming | token-set equality | `F-DED-008` |
| Recruiting-cycle isolation | cycle-scoped company lookup | `F-DED-009`, `NF-DAT-008` |
| Exact calendar-month cutoff | `six_calendar_month_cutoff` | `F-DED-010` |
| Malformed-file safety and observability | `DedupeAnomaly` and warning | `F-DED-011` |
| Order-invariance property | sorted token-set key | `F-DED-012` |
| Terminal state compatibility | `PipelineStatus.DEDUPE_SKIPPED` | dedupe/state integration test |

## Demonstrated limits

- Phase 3 produces path plans and duplicate decisions; it does not generate a DOCX.
- The default offline pipeline is not yet reordered around the future semantic stage.
  Phase 6 will sequence fetch, screening, dedupe, artifact creation, and terminal commit.
- Filename dates have day rather than time precision. A match exactly on the documented
  cutoff date proceeds conservatively.
- `engineer` and `engineering` remain different role tokens in v1.
- Tests write only fictional placeholders inside pytest-managed temporary directories.
