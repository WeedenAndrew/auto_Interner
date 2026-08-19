# Phase 2 traceability

**Gate result after the Git snapshot extension (2026-08-06):** formatting passed, lint
passed, strict source and test typing passed, and 216 tests passed with 91.4% combined
line/branch coverage on Python 3.12. The default suite made no live network, browser,
model, or résumé call.

| Requirement | Implementation | Automated evidence |
|---|---|---|
| Public-only HTTP(S) URLs | `PublicUrlPolicy` | `NF-SEC-001` through `NF-SEC-005` |
| Address-pinned connections | `PinnedHttpTransport` | transport address and header tests |
| Redirect revalidation | `SafeHttpClient` | `F-FET-010`, private redirect test |
| Timeout and status classification | `SafeHttpClient` | transport and HTTP-status tests |
| Response-size limits | `PinnedHttpTransport` | declared and actual size-limit tests |
| Remote snapshot parsing | `RemoteSnapshotLoader` | source contract tests |
| Versioned Git snapshot cache | `GitSnapshotLoader` | Git source contract/security tests |
| Git protocol and redirect controls | `SubprocessGitRunner` | subprocess boundary test |
| Static readable-text extraction | `StaticFirstPostingFetcher` | `F-FET-001`, `F-FET-011`, `F-FET-012` |
| JS-shell detection and fallback | `is_usable_posting_text` | `F-FET-002` through `F-FET-004` |
| Browser success and cleanup | `SeleniumBrowserFetcher` | `F-FET-006`, `F-FET-009` |
| Cross-run fetch retries | pipeline plus `StateStore` | `F-FET-007`, `F-FET-008` integration |
| Independent shared-URL outcomes | listing-scoped `FetchResult` | `F-FET-013` |
| Live source diagnostics | `auto-interner source-check` | CLI component tests |

## Dated live smoke evidence

On 2026-08-06, the configured Summer 2027 snapshot returned 14,770 accepted records,
1,559 active records, zero schema anomalies, and 11,029,264 bytes. A single active
posting then succeeded through the static adapter with 8,471 normalized characters.
These values demonstrate that the boundaries worked at that time; they are not fixed
test expectations.

The Git transport independently resolved commit
`62cd7898b4ed884c057bd3586655dab34d3cb67c`, read the same 11,029,264-byte blob, and
reported SHA-256
`61641611cc982b0e2b43c7deb93842dd206ed24788fcbcba43dfd2ff96047b3a`. It reported the
commit as changed and did not create a processed marker during the diagnostic.

## Demonstrated limits

- Default tests use fake DNS, transport, browser, and posting data.
- Selenium session construction and cleanup are tested with compatible fakes; a live
  Selenium/Chromium session was not launched by this gate.
- Browser navigation validates the starting and final URL, but full process and network
  isolation remains Phase 7 work. Browser fallback should not be enabled routinely
  before that phase.
- HTTP source retrieval validates data in memory. Git source retrieval stores a private
  bare object cache and reports change status without advancing the processed marker.
