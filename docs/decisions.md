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

**Status:** superseded by [ADR-018](#adr-018-one-pipeline-owns-every-stage). The
nonterminal-pass rule still holds; the `screening_passed` status that carried it no
longer exists because a passing listing now continues to the later stages in the same
run and lands on `shadow_ready`, `dedupe_skipped`, or `resume_generated`.

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

## Corpus extraction, found by running against a live posting (2026-08-18)

Three defects surfaced only when the extractor met a real ByteDance
infrastructure posting rather than a fixture. All three failed *silently* — the
requirement never appeared, so it was absent from the gap list too, and the
resume scored as a fuller match than it was. Fixed, with tests:

| | |
|---|---|
| Sentence-final terms dropped | `"Experience with Docker."` extracted nothing. The word-boundary lookahead excluded `.` to protect `node.js`, and so also excluded every term ending a sentence. |
| Concepts invisible | The taxonomy was 69 named tools. A posting can ask for high availability, disaster recovery and traffic routing without naming one product; 39 capability terms added. |
| Colonless headers unrecognised | `Preferred Qualifications` with no colon left every optional skill inheriting the previous section, so preferred requirements were reported as required. |

A fourth was a design gap rather than a bug: a posting asks for `databases`
while a resume says `MongoDB`. `blocks.SUBSUMES` now records definitional
evidence only — `mongodb` evidences `databases`, `docker` evidences
`containers`. Adjacency is deliberately excluded: Linux is not evidence of
operating-systems fundamentals. Widening it would hide gaps, which is the one
direction this package must not err in.

### Deferred — near-miss suggestions

The same run showed the honest limit of literal tagging. The posting asks for
`disaster recovery`; the resume says *"automated restarts, monitoring, recovery
procedures"*. That is plausibly the same work, but deciding so is a judgment
about meaning, and inferring it would be the generation this package exists to
avoid.

The correct shape is a report addressed to the user, never an edit: *"the
posting asks for disaster recovery; you wrote 'recovery procedures' — is that
the same thing? If so, say so in your own words."* Not built, to keep scope.

### Known weakness — arbitrary tie-break

When no remaining bullet covers an uncovered requirement, ranking falls through
to `-cost`, so the shorter bullet wins. In the ByteDance run this happened to
keep the Raspberry Pi deployment bullet over the pipeline description, which is
the right choice for a reliability role — but by length, not by fit. Selection
should not be described as understanding the role in that case.

## Layout rule: repository links belong on the title line (2026-08-18)

Experience and education already push location and dates to the right margin
with a right tab stop at 10080 twips. Projects did not: the link sat in the same
paragraph but was pushed right by eighty-four literal spaces, which overflowed
and wrapped it onto a line of its own. Two lines of a one-page budget spent on
two URLs.

`assemble.inline_trailing_link` normalises this during assembly. It applies only
to a paragraph holding exactly one hyperlink separated from the title by
whitespace alone, which excludes the contact block — several links,
punctuation-separated, inside a real sentence.

**It ships as layout and is held to that.** `test_link_inlining_changes_no_words`
asserts the non-whitespace text of every paragraph is byte-identical afterwards.
Assembly is otherwise delete-only; this is the one transform, and it is
constrained so it cannot become an edit.

Two mistakes made while writing it, both worth keeping:

- Treating a text-less run as "already positioned". Word leaves those behind
  constantly and they mean nothing.
- Treating the *presence of a tab* as correct. The source paragraph had a tab
  **and** eighty-four spaces **and** no right stop, so the tab fell on a default
  stop and the spaces did the rest. Correctness is the stop, not the character.

## Ranking a feed, and three defects it exposed (2026-08-18)

Scored one corpus against five live Summer-2027 listings — ByteDance, Sentry,
Replit, Roblox, DV Trading — to answer "which of these should I apply to?"

**`score()` is not a ranking signal.** Its denominator is how many skills the
posting happened to name, which is a fact about the writing. DV Trading named
two and ranked first at 50%; ByteDance named sixteen and ranked third at 27% on
four times the evidence. Ranking by coverage percentage rewards vague postings.
`CoverageReport.evidence()` returns absolute weight surfaced and is what a feed
should sort by; `is_comparable()` flags a posting too thin for its percentage to
be set beside another's.

**Alternation was read as conjunction.** *"One or more languages such as Java,
Go, C++, or Python"* is one requirement with four acceptable answers.
Extraction produced four, so a Python programmer was told they lacked Go and
C++ by the posting that said Python was fine. `Requirement.group` now marks
alternates, and coverage counts the group once, satisfied by any member.
Conjunctions — *"data structures, algorithms, networking, and databases"* — stay
separate, because all of that is genuinely wanted.

**Segments were lines, not sentences.** Postings wrap. Roblox put *"one or more
programming languages, including"* on one line and the nine languages on the
next, so the alternation cue and its members never met and eight languages
became gaps. `_segments` now joins continuation lines and breaks only on a
bullet marker, a blank line, or a header.

Effect on the same five postings, gap counts: ByteDance 12 → 10, Roblox 8 → 2,
DV Trading 1 → 0, Sentry 4 → 3. Every removed gap was a false one.

None of this was visible against fixtures. All three defects need a posting
written by someone who was not thinking about the parser.

## Phrase tagging: the same work, described differently (2026-08-18)

A posting asks for "code review". The resume says *"flag coding discrepancies
and issues"*. Literal-term matching called that a gap.

`corpus/tagging.py` adds phrase rules alongside the term vocabulary. It is
emphatically a **tagging** layer, not a rewriting one: the resume text is never
touched, paraphrased or regenerated. Only what an existing sentence is
understood to *count as* widens. Writing "Performed code review" for someone who
did not write it is a fabricated claim; recognising that the sentence they did
write demonstrates code review is reading, which is what a human screener does
anyway.

**Every tag names the words that earned it.** `TagHit` carries the exact
substring, `explain()` prints the provenance, and a test asserts the substring
really occurs in the source. A phrase tag the user disagrees with has to be
visible and removable — a tagger that silently inflates coverage would be worse
than not having one.

**The bar for a rule is that the user could defend it in an interview from that
sentence alone.** *"Automated restarts, monitoring, recovery procedures"* clears
it for `reliability`, `infrastructure`, `monitoring`, `automation`. It does not
clear `disaster recovery`, `high availability` or `distributed systems`, which
mean multi-region failover to the teams that ask for them, and those stay gaps.
Asserted by `test_it_stops_short_of_the_claims_that_would_be_a_stretch`.

Sentry, same corpus and posting: 40% → 83%, gaps 3 → 1. The one remaining is
`algorithms`, which is real — Data Structures coursework is not algorithms.

### Two selection bugs this exposed

- **A bulletless block could never be filled in.** The fill fallback required at
  least one bullet, so a skills line — a header and nothing else by nature —
  was unreachable. Resumes went out without their skills section while reporting
  the corpus exhausted rather than the page.
- **Fixing that let bare project titles back on the page.** Header-only
  selection is now restricted to `BlockKind.SKILL`, in `_plan_block` rather than
  only in fill, because a stub project was also outbidding real ones during
  coverage: a header is cheaper than a header plus evidence.

`git` was not in the taxonomy at all, despite appearing on nearly every posting.
Added, along with `github`/`gitlab`/`bitbucket` as mutual evidence — the
transferable skill is Git and the host is not the requirement.

### One test was passing for the wrong reason

`test_selection_reorders_for_a_different_posting` ran at budget 26 against a
23-line corpus. Everything fitted, so nothing competed, and it was asserting
incidental ordering rather than selection — it would have gone green whatever
the ranking did. Now runs at 14, where the two postings keep genuinely different
blocks, and asserts the kept sets differ in both directions.

## Widening the corpus, and what that exposed (2026-08-18)

Selection against the résumé alone was never really selecting: 8 blocks and 20
lines against a 20-line page, so nothing competed. Two very different postings
produced nearly identical documents.

Candidate blocks were drawn from README files in the user's own repositories —
his sentences, trimmed at clause boundaries only — into
`Artifacts/resume/candidates.json`, every one marked `_verified: false`. Corpus
goes to 12 blocks / 37 lines against the same 20-line page, and five blocks now
differ between a backend posting and a mobile one.

**Unverified blocks cannot reach a document.** `assemble_from_template` copies
the base `.docx` and deletes; it has no insert path. A candidate can influence
what is *kept*, but to appear it must first exist in the résumé the user
maintains. Structural rather than checked, which is the stronger form.

### Three defects the wider corpus exposed

| | |
|---|---|
| Tie-break was string length | With no requirement left to cover, ranking fell to `-cost`, so the shorter bullet won. Now ranks by how much of the posting the bullet speaks to at all, then by the order the user wrote them in — their own judgment about what matters. |
| Mobile work was invisible | `mobile development`, `android`, `ios` and `dart` were not in the taxonomy. A posting asking for iOS or Android could not see a shipped Flutter app, and the only mobile project lost the page to a backend one. |
| Alternation groups held fewer members than their labels named | A term already seen ungrouped could never join a later alternation, so a group was reported unsatisfied while a term printed in its own name was plainly covered. Priority and grouping now upgrade independently. |

After the mobile fix the TikTok listing goes from 75% with an unsatisfied group
to 100% with none, and keeps the Flutter project it had been dropping.

## The base document should be the master, not the one-pager (2026-08-18)

`assemble_from_template` copies the base `.docx` and deletes. That is the
truthfulness guarantee, and it also means a block absent from the base can never
reach a document — so a corpus wider than the base résumé could influence
*ranking* but never appear.

The resolution is not to give the assembler an insert path. It is to point it at
a different document: a **master résumé** holding every verified block, from
which each application is cut down. Delete-only then holds end to end, and the
one-page output is a subset of a document the user maintains and can read.

Master here is 36 lines against a 20-line page. Sentry and TikTok both fill
20/20, and the two differ:

| | Sentry | TikTok |
|---|---|---|
| projects | Auto Interner, Fantasy Blackjack, Curat0r | Auto Interner, Goblin Flip, Curat0r |
| evidence | 15 | 9 |
| coverage | 83% | 100% |
| unsupported | algorithms | none |

Verified: 0 lines in either output that are not in the master.

### Building the master

Two mistakes worth keeping. Cloning a new "Fantasy Blackjack" heading duplicated
a project already on the résumé — the stub removal matched on exact text, and
the real paragraph carries a trailing hyperlink label, so it never matched.
Cloning also strips hyperlinks (inheriting the source paragraph's URL would put
the wrong repository behind the right name), so the duplicate lost its link too.

Extending the existing entry fixes both: the heading keeps its own working link,
the bullets are inserted beneath it, and nothing is duplicated. Prefer amending
an existing block to cloning a new one wherever the block already exists.

## One page, enforced (2026-08-18)

`corpus/formatting.py`. Selection answers to a *line budget*, which is an
estimate; a slightly wrong estimate spills one orphaned line onto a second page,
which reads worse than either a full page or an honest two-page résumé. This
closes the gap from the other end.

Adjustments run cheapest-looking first — dead space, paragraph spacing, margins,
line spacing, and type size last. A reader notices 9.5pt type long before a
0.6in margin. `Floors` stops it at 9.5pt / 0.5in / 0.95 spacing: an unreadable
résumé that fits is not a success, and past that the honest remedy is to cut a
block, which `FitResult.describe()` says out loud.

No new dependency. The capacity model is the same characters-per-line arithmetic
`Bullet.cost` already uses, so selection and fitting agree by construction.
Calibration against LibreOffice: master estimated 53 lines into 49 and rendered
2 pages; the tailored output estimated 36 into 49 and rendered 1.

### Two shape rules

`bullets_by_kind={"project": 2}` — both floor and ceiling. Coverage alone gave
the projects section a ragged shape: one entry earned four bullets while the
next rendered as a bare title, which reads as abandoned rather than deliberate.

`max_blocks_by_kind={"project": 3}` — added after setting the budget from real
page capacity, which had an unwanted consequence: everything fit, so nothing
competed, and the two postings produced near-identical documents again. Filling
the page to the last line is not the same as making it good, and five projects
reads as a list of hobbies rather than a claim about strengths.

### Blocks could enter through three doors; only two were guarded

The cap held in the coverage loop and in `_fill`, and six projects walked
through `_fill_by_recency` anyway. Any rule about what may appear has to be
enforced at every entry point or it is decoration.

### Two tests were passing for the wrong reason

`test_selection_reorders_for_a_different_posting` used the shared fixture, which
has three projects — so once at most three may appear and each costs three
lines, it cannot force a choice at any budget. Rewritten with an explicit
two-project corpus where the competition is the point.

`test_a_full_page_is_not_reported_as_short` used six projects, which the new cap
makes unreachable. It is about fill, not caps, so it now disables the cap
explicitly rather than being quietly weakened.

Final: both documents render on exactly one page, three projects each at two
bullets, differing by one project — Curat0r for the backend posting, Goblin Flip
for the mobile one.

## Word, not LibreOffice, is the renderer that matters (2026-08-18)

The capacity model agreed with LibreOffice exactly — and the documents still put
a single bullet alone on page two in Word. The two lay out the same file
differently: font metrics, hyphenation and widow control are separate
implementations, and one arithmetic model cannot be right for both.

The two errors are not symmetric. Under-filling costs white space; overflowing
costs a whole extra sheet carrying one orphaned line, which is the worst thing a
one-page résumé can look like. `capacity()` now applies a 0.88 safety factor,
biasing the estimate toward the recoverable failure. `max_blocks_by_kind` for
projects went 3 → 2 for the same reason: three fit the estimate and spilled in
practice.

The wider lesson is that a verification step is only as good as the renderer it
uses. The one that counts is whoever opens the file.

## Cleanup pass (2026-08-18)

`ruff check` clean on both repositories. `Priority` now inherits `StrEnum` to
match `BlockKind`; `re.split` calls pass `maxsplit` by keyword; a few long lines
and unsorted imports fixed. Curat0r gained a `[tool.ruff]` block ignoring EXE002
— every file reports it because the working tree lives on a mount that marks
everything executable, which is a property of the filesystem rather than the
code, and chmod does not survive there.

Stale claims in this README were the real find. It advertised "260+ tests"
against an actual 335, and "four structural rules" when there were six. Numbers
on a public page go stale silently: nobody reports them, and an inflated figure
is worse than no figure. Regenerated from source, and the worked example rebuilt
from the current settings rather than left describing a run that no longer
happens.

`CLEANUP.cmd` lists the example assets the README no longer references and asks
before deleting. The posting texts are kept deliberately — they are the
provenance for the worked example.
## ADR-018: one pipeline owns every stage

**Decision:** Delete the Phase 1 `OfflinePipeline` and route every caller — live runs,
`run-once --fixture`, and `demo` — through `ApplicationPipeline`. Move the shared
`PipelineRunResult` record and `PostingFetcher` protocol into `models.py`. Retire the
`screening_passed` status.

**Why:** The two orchestrators had grown from a shared ancestor into ~130 lines of
duplicated stage sequencing, each with its own copy of the fetch boundary protocol. They
had already diverged in a way that cost the live path diagnosability: `OfflinePipeline`
persisted the adapter's classified `failure_reason`, while `ApplicationPipeline`
overwrote it with a generic stage label, so live manual-review records explained less
than demonstration ones. Two implementations of one policy is also two places for a
false disqualification to be introduced independently.

**Consequence:** The demonstration now exercises the semantic, dedupe, rewrite, and
path-planning stages against bundled fictional data instead of stopping after Tier 1. It
runs in permanent shadow mode against a derived data directory under its state
directory, so it still writes no document and reads no private input. Its observable
run counts are unchanged, and a passing fixture listing now records `shadow_ready`
rather than `screening_passed`; both are nonterminal, so repeat-run behavior is
identical.

**Alternative considered:** Keeping `OfflinePipeline` for the demonstration and
extracting the shared stages into helpers. That preserves two entry points into one
policy and leaves the divergence risk in place for a demonstration path that no longer
needs a reduced pipeline.

## ADR-019: Chromium requires writable scratch under a read-only root

**Decision:** Give the browser two writable locations inside the read-only container:
the adapter pins `--user-data-dir` to a single-use directory it creates and deletes per
session, and Compose mounts the whole `/home/auto-interner` as tmpfs rather than only
`.cache`.

**Why:** Chromium refuses to start when `$HOME` is read-only, and it does so twice for
different reasons. It first fails to create its profile container. With the profile
relocated it still fails, because Crashpad derives its database path from `$HOME`
independently of `--user-data-dir`; given an unwritable path it launches
`chrome_crashpad_handler` with an empty `--database` and aborts the browser with
`SIGTRAP`. No Chromium flag avoids the second failure. `--disable-crash-reporter`,
`--crash-dumps-dir`, `--disable-gpu`, `--disable-features=Crashpad`, and
`--disable-breakpad` were each measured and each still aborts; only a writable `$HOME`
succeeds.

**Why both layers:** the profile is the adapter's own concern, so the adapter owns it
and no longer depends on an ambient writable home wherever it runs. It also gains
single-use profile isolation, which matches [ADR-011](#adr-011-keep-browser-rendering-optional-and-isolated).
The writable home is the deployment's concern, so it lives beside the `read_only: true`
that creates the constraint.

**Regression risk:** narrowing that tmpfs back to `.cache`, or dropping the
`--user-data-dir` argument, reintroduces a failure that no unit test can catch — the
Python suite injects fake browser sessions and never launches Chromium. The offline
`browser-smoke` Compose service is the only automated guard, so it must stay in the
container gate.

## ADR-020: one snapshot parser, two interchangeable transports

**Decision:** Replace the flat `source.py` and `git_source.py` modules with an
`auto_interner.sources` package: `snapshot` owns record parsing and the shared types,
while `git` and `http` are transports that depend on it. The parser imports neither.

**Why:** [ADR-012](#adr-012-use-immutable-git-snapshots-for-discovery) states that Git is
only the snapshot transport, but the layout contradicted it. `source.py` mixed
transport-independent record validation with the HTTP loader, so the HTTP transport was
structurally privileged over the Git one and the parser could not be read, tested, or
replaced without pulling in a network client. The package makes the documented
dependency direction visible in the file tree.

**Consequence:** `SnapshotDownload`, `SnapshotResult`, and the parsing entry points are
re-exported from `auto_interner.sources`, so callers import one stable surface while the
transport split stays internal. Adding a third transport means adding a module beside
`git` and `http` rather than editing the parser.
