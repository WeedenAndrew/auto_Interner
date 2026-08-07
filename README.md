# Auto Interner

A local, AI-assisted internship discovery and resume tailoring pipeline designed
for one user on a Raspberry Pi. Auto Interner will find unseen listings, conservatively
screen hard disqualifiers, prevent duplicate work, and create truthfully tailored DOCX
resumes for human review.

> **Project status:** Phase 6 orchestration is complete. The repository
> includes validated live source retrieval, protected posting fetches, deterministic
> screening, portable output-path planning, current cycle six-month role
> deduplication, a strict provider-neutral model boundary with an Anthropic adapter,
> PII-separated truthfulness validation, template-preserving DOCX generation,
> crash-aware reconciled state, non-overlapping run coordination, run summaries and
> heartbeats, complete fixture execution, operator commands, and a hardened
> multi-architecture Docker/Compose deployment. Raspberry Pi arm64 validation and the
> required 24-hour soak remain pending on the target server.

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
- [Phase 0 traceability](docs/phase-0-traceability.md)
- [Phase 1 traceability](docs/phase-1-traceability.md)
- [Phase 2 traceability](docs/phase-2-traceability.md)
- [Phase 3 traceability](docs/phase-3-traceability.md)
- [Phase 4 traceability](docs/phase-4-traceability.md)
- [Phase 5 traceability](docs/phase-5-traceability.md)
- [Phase 6 traceability](docs/phase-6-traceability.md)
- [Phase 7 traceability](docs/phase-7-traceability.md)
- [Raspberry Pi deployment](docs/raspberry-pi.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## License

Licensed under the [MIT License](LICENSE).
