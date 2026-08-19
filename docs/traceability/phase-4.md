# Phase 4 traceability

Phase 4 establishes semantic screening without making a model call part of the default
test or demo path. Every case uses fictional posting excerpts and local fakes.

| Contract | Implementation | Evidence |
|---|---|---|
| `F-L2-001` exact valid response | `parse_semantic_assessment` | `test_f_l2_001_exact_schema_is_accepted` |
| `F-L2-002`–`006` malformed response rejection | exact keys, types, confidence, and evidence bounds | parameterized invalid-payload tests |
| `F-L2-007`–`009` hard-disqualifier policy | `screen_posting_semantically` | category/confidence policy tests |
| `F-L2-010` low-confidence safety | explicit medium/high threshold | low-confidence parameterized test |
| `F-L2-011` clear posting pass | no terminal decision | all-clear test |
| `F-L2-012` prompt injection | system boundary plus JSON serialization | adversarial posting test |
| `F-L2-013` data minimization | posting-only request | request-content test |
| `F-L2-014` multi-category evidence | evidence tuple preserves every hard category | combined-category test |
| Provider contract | fixed endpoint, strict forced tool, bounded response | `test_model_client.py` |
| Pipeline order and recovery | Tier 2 follows Tier 1; failures retry or review | `test_semantic_pipeline.py` |

The release gate is format, lint, strict typing, the complete offline suite, branch
coverage of at least 85%, and a scan proving that no live credentials or private resume
artifacts entered the repository.
