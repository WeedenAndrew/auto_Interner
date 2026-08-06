# Decision log

## ADR-001: one modular worker for v1

**Decision:** Run scanner, fetcher, screening, dedupe, rewriting, DOCX assembly, and
persistence as modules inside one worker process.

**Why:** One user, a two-hour cadence, a 4 GB Pi, and a single-writer state rule do not
justify three independently deployed services. Module interfaces and fakes preserve
testability without queues or cross-service protocols.

**Alternative considered:** Independently deployed scanner, orchestrator, and rewriter
services. The extra deployment and coordination surface is not justified for v1.

## ADR-002: bind-mounted runtime directories

**Decision:** Map `./runtime/data` and `./runtime/state` to `/app/data` and `/app/state`.

**Why:** Host-visible files are easier for one user to inspect, back up, recover, and
move. The directories remain private and ignored by Git.

**Alternative considered:** Docker-managed named volumes. Bind mounts are preferred for
transparent local backup and inspection.

## ADR-003: seen means terminally committed

**Decision:** Append a listing ID to the seen set only after a disqualification,
dedupe skip, generated resume, or manual-review outcome is durably recorded.

**Why:** Marking discovery or a temporary failure as seen can permanently lose a valid
listing. Reprocessing after a crash is safer than silent loss.

**Alternative considered:** Marking every attempted listing as seen. That approach can
permanently hide work after a temporary failure.

## ADR-004: standard library configuration in Phase 0

**Decision:** Use a frozen typed dataclass and explicit parsers rather than adding a
runtime settings dependency.

**Why:** The Phase 0 contract is small, explicit, and testable with the standard
library. This reduces Pi installation surface and keeps configuration parsing free of
network or filesystem side effects.

## ADR-005: exactly one listing source

**Decision:** Reject configurations that set both `LISTINGS_URL` and
`LISTINGS_URL_TEMPLATE`.

**Why:** Silent precedence makes diagnostics and test expectations ambiguous. The
operator must choose the intended source mode.

## ADR-006: year-swappable Simplify snapshot

**Decision:** Default documentation to the raw
`SimplifyJobs/Summer{year}-Internships` snapshot on the upstream `dev` branch, while
retaining a complete `LISTINGS_URL` override.

**Why:** The Summer 2027 repository exposes `.github/scripts/listings.json` on `dev`,
but branch and path ownership remains upstream. A full URL override prevents a source
layout change from requiring a release.

## ADR-007: model selection stays in configuration

**Decision:** `ANTHROPIC_API_KEY` authenticates the provider and `ANTHROPIC_MODEL`
retains a nonempty model ID supplied by the operator.

**Why:** Avoiding a hard-coded model lets later evaluation, cost, and latency findings
drive selection without source edits. Provider support is validated only when the live
adapter is implemented.

## ADR-008: deterministic screening passes are nonterminal

**Decision:** Tier 0 or Tier 1 disqualification and exhausted manual review are terminal
in Phase 1. Passing deterministic screening is recorded but does not join the seen set.

**Why:** Dedupe, semantic screening, and resume generation are not implemented yet.
Treating a partial pass as complete would hide the listing from those later stages.

## ADR-009: fixture boundaries are the default executable path

**Decision:** The Phase 1 demo loads bundled fictional JSON and a fixture posting
fetcher. It does not read a resume, environment configuration, credentials, or network.

**Why:** The repository can demonstrate orchestration and persistence without exposing
private data or making results depend on external services.

## ADR-010: resolve, validate, and pin every HTTP hop

**Decision:** Resolve each HTTP(S) hostname, reject the target if any advertised address
is non-public, and connect directly to one validated address. Disable implicit redirect
handling and repeat the full validation for every redirect target.

**Why:** Validating a hostname before giving it to an auto-resolving client leaves a
DNS-change gap. Automatic redirects can also turn a public starting URL into a private
destination. Address pinning and manual redirects keep both decisions inside one tested
boundary.

## ADR-011: keep browser rendering optional and isolated

**Decision:** Static retrieval is the default. Selenium is an optional dependency used
only when static text is insufficient. The wrapper validates its starting and final URL,
sets timeouts, and closes each session after success or failure.

**Why:** A browser executes untrusted page behavior and may load subresources outside
the primary origin. The adapter is testable in Phase 2, but routine browser execution
must wait for the container isolation and Chromium controls in Phase 7.

## ADR-012: use immutable Git snapshots for discovery

**Decision:** Use a shallow bare Git cache as the default Simplify snapshot transport.
Fetch a configured branch into a private internal ref, resolve its commit, and read the
configured JSON blob without checkout. Keep the protected HTTP loader as a fallback.

**Why:** Commit IDs give each scan an immutable source version, unchanged commits can be
skipped, and Git reuses cached objects between updates. A separate processed-commit
marker advances only after the complete scan succeeds.

**Security boundary:** Only the exact SimplifyJobs Summer repository pattern over HTTPS
is accepted. Redirects, prompts, credential helpers, hooks, alternate Git protocols,
user Git configuration, and shell execution are disabled. Git does not replace the
address-pinned HTTP client used for individual posting URLs.

**Alternative considered:** Conditional HTTP snapshot downloads. They remain useful as
a fallback and can avoid unchanged transfers, but a changed snapshot is downloaded as a
complete document and has no repository commit identity.

## ADR-013: use calendar-month, filename-backed role deduplication

**Decision:** Compare generated resumes only within the configured recruiting-cycle and
safe company directory. Normalize roles by Unicode, case, punctuation, internship noise,
seasons, standalone four-digit years, and token order. Do not stem words in v1.

**Time rule:** Subtract six calendar months from the evaluation date and clamp to the
target month's final valid day. A matching document newer than that date is a duplicate;
one exactly on the cutoff proceeds. Both generation and evaluation timestamps must carry
an explicit timezone, while the v1 filename comparison remains day-granular.

**Why:** The rule follows the planned directory structure, resets naturally between
recruiting cycles, and favors proceeding when age or role identity is ambiguous. Keeping
`engineer` and `engineering` distinct is a documented conservative v1 limitation.

**Safety boundary:** Output paths are planned without writes, normalized into bounded
portable components, and resolved under `DATA_DIR`. Directory creation is explicit and
lazy, symbolic company directories are rejected, and an existing filename is never
overwritten.

## ADR-014: provider-neutral structured model boundary

**Decision:** Screening and rewriting depend on a small `StructuredModelClient`
protocol. The first live adapter uses Anthropic's fixed Messages endpoint, forces one
named strict tool, bounds the response, and parses only the matching `tool_use` input.

**Why:** Model IDs remain configuration, deterministic fakes exercise every default
test, and future providers can implement the same protocol without changing domain
policy. A second exact local validation means provider-side schema enforcement is an
additional guard, not a trust assumption.

**Safety boundary:** Posting text is JSON-encoded as untrusted data and the system
instruction rejects embedded commands. Missing fields, extra fields, wrong types,
invalid confidence, multiple tool calls, and malformed envelopes are retryable failures,
never eligibility evidence. Low confidence never auto-disqualifies. API keys and raw
provider bodies are excluded from persisted errors.

## ADR-015: patch and validate an immutable DOCX base

**Decision:** Extract a stable paragraph/section map from the cycle base resume, keep
the contact block outside the rewrite payload, validate a structured rewrite locally,
then patch and reorder a copied DOCX package. Publish the validated copy through a
no-replace hard link in the already-prepared company directory.

**Why:** Rebuilding a resume from model text would discard styles, layout, hyperlinks,
and provenance of factual claims. Stable paragraph IDs permit model-safe redaction and
exact local lookup without sharing contact data or asking the model to reproduce the
document structure.

**Truthfulness boundary:** Every base section must remain exactly once. Numeric claims
must have the same multiset, technologies must already exist somewhere in the base,
proficiency cannot be escalated, and contact or hyperlink paragraphs cannot be changed.
Invalid schemas retry; unsupported claims stop before document assembly.

**Document boundary:** The base hash must remain unchanged. The output must reopen,
preserve page geometry and contact text, contain every validated replacement, and match
the requested section order. Identifying package metadata and revision IDs are scrubbed,
an existing destination is never replaced, and shadow mode performs no filesystem write.

## ADR-016: checkpoint only a reconciled terminal source scan

**Decision:** Hold one operating-system lock from source acquisition through summary
and heartbeat persistence. Mark a Git commit processed only when every outcome returned
by the application pipeline is terminal, every returned terminal ID is in the seen set,
and cross-file state reconciliation succeeds.

**Why:** Advancing the source marker after a shadow result, retry, partial failure, or
state mismatch could silently remove a listing from future consideration. Re-fetching a
known commit is inexpensive compared with losing an application opportunity.

**Recovery boundary:** Terminal decisions are appended before seen IDs. If a process
stops between those writes, the next terminal commit recognizes the existing decision,
adds only the missing seen ID, and avoids a duplicate log record. A stable lock file is
harmless after a crash because ownership is enforced by the operating system rather
than by file existence.

## ADR-017: one hardened multi-architecture worker image

**Decision:** Deploy one Python 3.12 Bookworm-based image on Ubuntu Server arm64. Use
Debian's matching Chromium/chromedriver packages, Tini as PID 1, and a fixed non-root
UID/GID `10001`. Persist only `/app/data` and `/app/state` through SSD-backed host bind
mounts.

**Why:** The modular monolith already enforces one state writer. One image minimizes Pi
memory and operational complexity, while host bind mounts keep private data inspectable,
backup-friendly, and independent of container/image replacement.

**Target profile:** The first server is a Raspberry Pi 4B with 4 GB RAM, one fan, and
an M.2 SATA SSD exposed through the HAT's USB 3 bridge. The worker defaults to two CPUs
and a 1536 MiB hard memory limit so Ubuntu and Docker retain operating headroom.

**Isolation boundary:** Compose publishes no ports, drops all capabilities, enables
`no-new-privileges`, makes the root filesystem read-only, bounds PIDs/memory/logs, and
uses tmpfs for browser scratch space. Chromium's `--no-sandbox` is allowed only inside
this isolated container because nested browser sandboxes are unreliable under the
selected Docker restrictions.

**Operational boundary:** `restart: unless-stopped` covers process and host restarts.
The heartbeat reports stale/failed operation but does not automatically restart an
otherwise running container. Hardware acceptance still requires a target-arm64 browser
smoke, persistence drills, and a 24-hour shadow soak.
