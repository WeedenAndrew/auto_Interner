# Auto Interner

**One person's internship pipeline, running unattended on a Raspberry Pi.**

It finds listings you have not seen, screens the hard disqualifiers
conservatively, refuses to apply to the same role twice, tailors your résumé to
what is left, and hands you a document to submit yourself.

Deliberately single-user. One résumé, one person, one industry. Every design
choice below follows from that: local state, no accounts, no server, no
multi-tenancy, and a machine that can sit on a shelf and run for a year.

Generalising it for other people is a different project, and it is
[Curat0r](https://github.com/WeedenAndrew/Curat0r).

> **Status: complete and running.** 335 tests, full offline test gate,
> multi-architecture Docker deployment.
>
> **Automatic submission is deliberately out of scope.** It violates the terms
> of service of most application portals, and auto-submitted applications get
> flagged as spam — which is worse than not applying. The expensive, error-prone
> work is *finding, screening, and tailoring*; that is what this automates.
> Submission is three minutes of human review per application, and keeping a
> human at that step is correct design rather than an unfinished feature.

**What it does**

```
snapshot → scan → fetch → deterministic screen → semantic screen
        → role dedupe → validated rewrite → DOCX assembly → atomic commit
```

Two properties are unusual enough to call out:

**It cannot lie about you.** The rewrite validator rejects any model output that
alters a numeric claim, introduces a technology absent from your source resume,
or escalates a stated proficiency. Truthfulness is enforced structurally, not
requested in a prompt.

**Your contact data never reaches the model.** It is extracted into a local-only
block before any request is built, and the validator refuses any rewrite that
reintroduces it.

### `auto_interner.corpus` is scheduled to leave this repository

A second tailoring strategy grew here: instead of letting a model write and then
validating it, keep a corpus of blocks you wrote and *select* a subset, so
nothing is ever authored on your behalf. Stronger guarantee, and it works.

It is also not this project's job. It is corpus-driven, source-agnostic and
built for arbitrary users, which is the definition of the other repository. It
currently sits at 1,889 lines and 75 tests, imported by nothing on the live
path, reachable only from scripts.

It moves to [Curat0r](https://github.com/WeedenAndrew/Curat0r) as that project's
selection core. Recorded here rather than quietly deleted, because a reader
running `find` will notice the directory and deserves to know why it is there.

## Worked example — one corpus, two live postings

Two real Summer 2027 listings, pulled from the same public feed this project
already ingests: a backend internship at Sentry and a mobile internship at
TikTok. One corpus, one page each.

```
corpus  10 blocks / 29 lines      one page

                                    Sentry                 TikTok
                                    ---------------------- ----------------------
  ********                          keep                   keep
  ********                          keep                   keep
  ********                          keep                   keep
  Proficient Languages: Python, Ja  keep                   keep
  Frameworks/Libraries: Flutter, P  keep                   keep
  Auto Interner                     keep                   keep
* Fantasy Blackjack                 keep                     . 
* Goblin Flip                         .                    keep
  Curat0r                             .                      . 
  GAN Agent                           .                      . 

                          coverage  83                     100
                          evidence  15                     9
                       unsupported  algorithms             none
```

The mobile posting keeps the Flutter game and drops the Python and TypeScript
one. The backend posting does the reverse. Nothing was rewritten to achieve
that — both are subsets of blocks the user wrote. Both postings are in
[`docs/examples/`](docs/examples/) verbatim, as pulled.

`********` marks a masked field: contact details, employers, university, and
one client. Asterisks rather than substitutions on purpose, because a plausible
replacement like "Insurance Services Client" reads as real content and
misrepresents the document.

### Read `evidence`, not `coverage`, to compare two postings

TikTok scores 100% and Sentry 83%, but Sentry is the stronger application. The
denominator of `coverage` is how many skills the posting happened to name,
which is a fact about the writing. `evidence` — absolute requirement weight
actually surfaced — is 15 against 9, and `is_comparable()` flags any posting too
thin for its percentage to be set beside another's.

### The corpus is the constraint, not the engine

Run against the résumé alone — 8 blocks against a page that holds about the same
— and the two postings produce nearly identical documents. Nothing competes, so
nothing is chosen. Selection only becomes selection once the corpus is larger
than the page.

Those extra blocks came from README files in the user's own repositories, and
they ship marked `_verified: false`. Building that corpus automatically is
[Curat0r](https://github.com/WeedenAndrew/Curat0r); this repository is what
consumes it.

### The output can only ever be a subset of your own document

`assemble_from_template` copies the base `.docx` and deletes paragraphs. It has
no insert path, which means an unverified block cannot reach a finished document
even by mistake — it can influence what is *kept*, and to appear it must first
exist in the résumé you maintain. That is a stronger guarantee than a validator,
because it is structural rather than checked.

### It is your own file, not a rebuild

The output is the base `.docx` copied with unselected paragraphs deleted. Font,
margins, tab stops, heading rules and the GitHub hyperlinks all survive because
nothing was touched. A generated document that is correct but looks nothing like
the résumé you have been sending is a new document to proofread, not a tailored
one.

### Six structural rules run before coverage is considered

| Rule | Why |
|---|---|
| Education in full | No posting lists a degree as a requirement, so coverage always drops it — from an internship application, where its absence is disqualifying |
| At least two terms of experience | One job reads as no history, whatever the posting asked for |
| At most two projects | Five reads as a list of hobbies rather than a claim about strengths. Three fit the line estimate and still spilled in Word, leaving one bullet alone on page two |
| Exactly two bullets per project | Floor and ceiling both. Coverage alone gave one entry four bullets and rendered the next as a bare title, which reads as abandoned rather than deliberate |
| Fill the page, or say why not | A résumé that stops two thirds down reads as thin, and typesetting cannot hide it |
| Repository links sit on the project's title line, at the right margin | The position experience and education already use for location and dates. A link on its own line spends a line of a one-page budget on a URL |

The link rule is layout, not content, and is held to that: whitespace may move,
and a test asserts that nothing a reader would call a word changes. Getting
there with literal spaces — as the source résumé did, with eighty-four of them —
is not a position at all. It holds at exactly one font size and one margin, and
overflowed anyway, wrapping the link onto the line it was padded to avoid.

### Where the corpus came from

Résumé sections plus public GitHub repositories, deduplicated. `Auto Interner`
from the résumé and `auto_Interner` from GitHub are one project; the richer
block wins.

Screening drops what does not belong on a résumé, with a reason each time:

```
2 kept, 3 dropped
  keep  auto_Interner        keep  Goblin-Flip
  drop  neetcode-submissions  - exercise or interview practice, not a built thing
  drop  WeedenAndrew          - your GitHub profile README, not a project
  drop  bbit-learning-labs    - a fork - the work is someone else's unless you say otherwise
```

Full run: [`docs/examples/curated-resume.md`](docs/examples/curated-resume.md)

## Design goals

- Prefer a false pass over silently hiding a valid internship.
- Keep resumes, application history, generated documents, and credentials local.
- Make every external boundary replaceable with an offline fake.
- Commit state only after a terminal decision or validated artifact exists.
- Run comfortably on a 4 GB arm64 Raspberry Pi as one modular worker.
- Maintain an offline demonstration suitable for a public portfolio repository.

## Data and model configuration

Configuration points to the public
[SimplifyJobs Summer 2027 Internships](https://github.com/SimplifyJobs/Summer2027-Internships)
repository and its readable snapshot on the upstream `dev` branch. The default
source is a shallow fetch into a private bare Git cache. Each check resolves one fixed
commit and reads only the configured JSON blob without checkout or execution. If the
commit matches the last successfully processed commit, a later polling orchestrator can
skip the cycle. Protected HTTP snapshot retrieval remains an explicit fallback.

Git is only the snapshot transport. Individual job URLs continue through the separate
public-address HTTP boundary, including redirect revalidation and response limits.

Claude model choice is configuration-only:

```text
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=<model ID available to the account>
```

Populate `ANTHROPIC_API_KEY` only in the ignored local `.env` file.
Set `ANTHROPIC_MODEL` to any compatible model ID available to the account without
modifying source code. The adapter forces a strict client-tool response and applies the
same schema again locally. Its interface is provider-neutral so another provider
can be added without changing screening policy; Anthropic is the only live provider
implemented today.
See the local [configuration reference](docs/configuration.md).

## Architecture

V1 is a modular monolith. Components remain independently testable, while one
orchestrator owns all state and generated-document writes.

```text
snapshot -> scan -> fetch -> deterministic screen -> semantic screen
         -> role dedupe -> validated rewrite -> DOCX assembly -> atomic commit
```

Temporary failures stay retryable. A listing becomes seen only after a terminal outcome
is durably recorded.

Resume contact data is extracted into a local-only block and never included in rewrite
requests. Rewrites can reorder existing sections and rephrase eligible paragraphs, but
are rejected if they omit sections, alter metrics, introduce technologies, strengthen
proficiency, modify hyperlinks, or add contact data. The assembler patches a copy of the
base DOCX, preserves geometry and hyperlinks, scrubs identifying metadata, reopens the
package for validation, and publishes without overwriting an existing file.

Phase 3 deduplication compares only the configured recruiting cycle and company. Role
keys discard internship noise, punctuation, token order, seasons, and standalone years,
while retaining domain terms. A generated role newer than the six-calendar-month cutoff
is a duplicate; a document dated exactly on the cutoff proceeds.

## Local setup

Requirements: Python 3.12 or newer. Static retrieval has no third-party runtime
dependencies. Selenium is an optional dependency for browser-rendered postings.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

Install the browser adapter only on systems configured for isolated Chromium execution:

```powershell
.\.venv\Scripts\python -m pip install -e ".[browser]"
```

Use `.env.example` as a reference, but provide values through the shell or a local
secret manager. The application intentionally does not auto-load `.env`.

The private base resume belongs at:

```text
<DATA_DIR>/<RECRUITING_YEAR>/baseplate/base_resume.docx
```

Validate configuration without contacting GitHub or Anthropic:

```powershell
$env:RECRUITING_YEAR = "2027"
$env:LISTINGS_SOURCE_MODE = "git"
$env:LISTINGS_GIT_REPOSITORY_TEMPLATE = "https://github.com/SimplifyJobs/Summer{year}-Internships.git"
$env:LISTINGS_GIT_REF = "refs/heads/dev"
$env:LISTINGS_GIT_PATH = ".github/scripts/listings.json"
$env:ANTHROPIC_MODEL = "<model ID available to the account>"
$env:DATA_DIR = ".\runtime\data"
$env:STATE_DIR = ".\runtime\state"
.\.venv\Scripts\auto-interner.exe config-check
```

Fetch and validate the configured live snapshot without checkout, résumé access, or a
model call:

```powershell
.\.venv\Scripts\auto-interner.exe source-check
```

Run the complete Phase 1 flow with bundled fictional data and no private inputs or
external calls:

```powershell
.\.venv\Scripts\auto-interner.exe demo --state-dir .\runtime\demo-state
```

Run it a second time with the same state directory to verify that terminal IDs are
skipped while nonterminal work remains eligible for later pipeline stages. The third
run moves the fixture's repeated temporary failure to manual review.

Exercise the complete pipeline with a fictional résumé, posting, and deterministic
model fake. Shadow mode is the default and plans the output without writing a DOCX:

```powershell
.\.venv\Scripts\auto-interner.exe run-once --fixture `
  --data-dir .\runtime\fixture-data `
  --state-dir .\runtime\fixture-state
```

Add `--write` to publish the fictional artifact. Its path follows this stable contract:

```text
<DATA_DIR>/<RECRUITING_YEAR>/<company>/<role>_<MM-DD-YY>.docx
```

For a live run, set the documented environment variables, place the private base résumé
at the configured baseplate path, and run `auto-interner run-once`. Live shadow behavior
is controlled by `SHADOW_MODE`; the fixture-only `--write` flag cannot override it.
Use `auto-interner daemon` for immediate execution followed by serialized polling, and
`auto-interner manual-review-count --state-dir <path>` for a payload-free backlog count.

The Git source commit is marked processed only after all outcomes are terminal and the
decision/seen state reconciles. Shadow, retry, and failed runs intentionally revisit the
same commit later.

## Docker and Raspberry Pi

The production image runs as UID/GID `10001` on a Python 3.12 multi-architecture base
with distribution-matched Chromium and chromedriver. Compose provides SSD-backed bind
mounts, a read-only root filesystem, no inbound ports, bounded memory/PIDs/logs,
heartbeat health, graceful shutdown, and `restart: unless-stopped`.

The initial hardware profile is a Raspberry Pi 4B with 4 GB RAM, active fan cooling,
and a 1 TB M.2 SATA SSD attached through the HAT's USB 3 bridge. Compose therefore
defaults the worker to two CPUs and 1536 MiB of memory while leaving both limits
operator-configurable.

After copying `.env.example` to the ignored `.env` and creating the configured bind
mounts, the portable smoke sequence is:

```bash
docker compose config --quiet
docker compose build --pull worker
docker compose --profile tools run --rm smoke
docker compose --profile tools run --rm browser-smoke
```

Keep `SHADOW_MODE=true` for the first 24 hours on the Pi. The complete SSD setup,
permissions, backup/recovery process, health checks, and twelve-cycle soak checklist are
in the [Raspberry Pi deployment runbook](docs/raspberry-pi.md).

## Quality gate

```powershell
.\.venv\Scripts\python -m ruff format --check .
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m mypy
.\.venv\Scripts\python -m pytest --cov=auto_interner --cov-branch --cov-fail-under=85
```

The GitHub Actions workflow is configured to run the same gate on Python 3.12 for
Windows and Linux. The default suite makes no live network, browser, or model calls.

## Repository guide

- [Implementation roadmap](docs/roadmap.md)
- [Configuration reference](docs/configuration.md)
- [Architecture decisions](docs/decisions.md)
- [Phase 0 traceability](docs/traceability/phase-0.md)
- [Phase 1 traceability](docs/traceability/phase-1.md)
- [Phase 2 traceability](docs/traceability/phase-2.md)
- [Phase 3 traceability](docs/traceability/phase-3.md)
- [Phase 4 traceability](docs/traceability/phase-4.md)
- [Phase 5 traceability](docs/traceability/phase-5.md)
- [Phase 6 traceability](docs/traceability/phase-6.md)
- [Phase 7 traceability](docs/traceability/phase-7.md)
- [Raspberry Pi deployment](docs/raspberry-pi.md)

## License

Licensed under the [MIT License](LICENSE).
