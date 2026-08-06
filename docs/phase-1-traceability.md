# Phase 1 traceability

**Gate result (2026-08-05):** formatting passed, lint passed, strict source typing
passed, and 118 tests passed with 94.9% combined line/branch coverage on Python 3.12.
The default suite made no network, browser, model, or résumé call.

| Requirement | Implementation | Automated evidence |
|---|---|---|
| Typed listing and outcome records | `src/auto_interner/models.py` | source and pipeline tests |
| Strict local snapshot parsing | `src/auto_interner/source.py` | `F-SRC-001` through `F-SRC-007`, `F-SRC-009` |
| Duplicate-ID anomaly reporting | `parse_snapshot_payload` | `F-SRC-004` |
| Windowed unseen-ID scanning | `src/auto_interner/scanner.py` | `F-SCN-001` through `F-SCN-008`, reorder case |
| Conservative US location rules | `src/auto_interner/screening/location.py` | `F-L0-001` through `F-L0-010` |
| Data-driven text rules | `src/auto_interner/screening/keywords.py` | positive and negative case for every rule |
| Replaceable posting boundary | `PostingFetcher` protocol | fake-fetch integration tests |
| Decision-before-seen commit order | `src/auto_interner/state_store.py` | `F-STA-003` through `F-STA-006` |
| Retry and manual-review transitions | `StateStore.record_retry` | `F-STA-007`, `F-STA-008` |
| End-to-end offline command | `auto-interner demo` | CLI component and pipeline integration tests |
| Second run skips terminal IDs only | `OfflinePipeline.run` | repeated-run integration and CLI tests |

## Demonstrated limits

- Input is local JSON; live source retrieval is not implemented.
- Posting acquisition uses a bundled fake; static HTTP and browser adapters are not
  implemented.
- Tier 0 and Tier 1 are implemented. Semantic screening is not implemented.
- A screening pass remains nonterminal until later dedupe, rewrite, and document stages
  exist.
- No model or résumé processing occurs in the Phase 1 path.
