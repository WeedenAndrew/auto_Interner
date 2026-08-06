# Configuration

Auto Interner reads environment variables at process startup. It does not automatically
load `.env`; `.env.example` is a safe reference file, while secrets should be supplied
by the shell, Docker Compose, or a local secret manager.

## Listing source

`LISTINGS_SOURCE_MODE` selects `git` or `http`. Git is the default.

### Git snapshot mode

Git mode maintains a private bare repository under
`<STATE_DIR>/source-cache/summer-<year>.git`. Configure:

- `LISTINGS_GIT_REPOSITORY` for one complete repository URL, or
  `LISTINGS_GIT_REPOSITORY_TEMPLATE` for one `{year}` placeholder.
- `LISTINGS_GIT_REF` as a fully qualified branch such as `refs/heads/dev`.
- `LISTINGS_GIT_PATH` as a normalized relative path inside the repository.

The default repository template is:

```text
https://github.com/SimplifyJobs/Summer{year}-Internships.git
```

The transport accepts only exact HTTPS repositories matching
`github.com/SimplifyJobs/Summer<year>-Internships.git`. It disables redirects, prompts,
credential helpers, hooks, non-HTTPS Git protocols, user/global Git configuration, and
shell execution. Fetches are shallow and update a private internal ref. The JSON blob
is size-checked and read directly from its commit; no working tree is created.

The loader reports whether the fetched commit differs from the last successfully
processed commit. A diagnostic `source-check` never marks it processed. The runtime
coordinator records the commit only after its complete scan is terminal and state
reconciliation succeeds.

### Protected HTTP fallback

In `http` mode, choose exactly one endpoint:

- `LISTINGS_URL` pins a complete snapshot URL.
- `LISTINGS_URL_TEMPLATE` substitutes the configured `RECRUITING_YEAR` into one
  `{year}` placeholder.

The verified Summer 2027 source is:

```text
https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json
```

The default example generalizes it as:

```text
https://raw.githubusercontent.com/SimplifyJobs/Summer{year}-Internships/dev/.github/scripts/listings.json
```

The upstream repository currently uses the `dev` branch and stores the machine-readable
snapshot at `.github/scripts/listings.json`. Because upstream layout is outside this
project’s control, operators can switch to `LISTINGS_URL` without a code change.

`auto-interner source-check` performs one live bounded acquisition and reports accepted,
active, and anomalous record counts plus a SHA-256 content hash. Git mode also reports
the commit ID and change status. It persists Git objects in the private source cache but
does not print posting data or update the processed-commit marker.

## Retrieval limits

- Source snapshots are limited to 20 MiB.
- Git fetches default to a 60-second timeout and serialize access to each cache.
- Git repository redirects and protocols other than HTTPS are disabled.
- Individual posting responses are limited to 5 MiB.
- Every hostname must resolve exclusively to public IP addresses.
- HTTP(S) redirects are followed manually and revalidated.
- Connections use a previously validated address rather than silently resolving again.
- `STATIC_FETCH_TIMEOUT_SECONDS` and `BROWSER_FETCH_TIMEOUT_SECONDS` control their
  respective boundaries.

Selenium is available through the `browser` optional dependency. Browser rendering is
not used by `source-check` or the default offline demo. `BROWSER_ENABLED` activates it
only when both configured executable paths exist. The production container supplies
matching Debian Chromium/chromedriver paths and the required isolation controls.

## Model selection

`ANTHROPIC_API_KEY` authenticates the Anthropic account. `ANTHROPIC_MODEL` independently
retains the model ID supplied by the operator. Changing the model therefore requires an
environment change, not a source-code edit. The identifier is required and has no
project default because available models are account- and provider-dependent.

Model selection must be evaluated against labeled screening and rewrite fixtures before
deployment. The live adapter calls only Anthropic's fixed HTTPS Messages endpoint, uses
a bounded response, forces one named strict tool, and rejects every response that does
not contain exactly one matching tool call. The domain layer independently validates
the exact schema and confidence policy. Tests use fakes, and the default suite never
calls Anthropic.

## Runtime commands

- `auto-interner run-once` performs one configured live scan.
- `auto-interner daemon` runs immediately, then waits `POLL_INTERVAL_HOURS` after each
  run completes before starting the next one.
- `auto-interner manual-review-count` reports only the unique backlog count.
- `auto-interner run-once --fixture` exercises the complete pipeline without settings,
  credentials, or network calls. It remains write-free unless `--write` is supplied.

Live write behavior is controlled only by `SHADOW_MODE`. A `true` value validates
screening, rewriting, and the planned output path while producing no final DOCX and
leaving the source version eligible for the next run.

## Variables

| Variable | Default | Constraint |
|---|---:|---|
| `RECRUITING_YEAR` | current year | `2000` through `2100` |
| `LISTINGS_SOURCE_MODE` | `git` | `git` or `http` |
| `LISTINGS_GIT_REPOSITORY` | none | exact allowed complete HTTPS repository URL |
| `LISTINGS_GIT_REPOSITORY_TEMPLATE` | Simplify year template | contains `{year}` once |
| `LISTINGS_GIT_REF` | `refs/heads/dev` | safe fully qualified branch ref |
| `LISTINGS_GIT_PATH` | `.github/scripts/listings.json` | normalized relative path |
| `GIT_FETCH_TIMEOUT_SECONDS` | `60` | `5` through `600` |
| `LISTINGS_URL` | none | complete HTTP(S) URL; mutually exclusive with template |
| `LISTINGS_URL_TEMPLATE` | none | complete HTTP(S) URL containing `{year}` once |
| `POLL_INTERVAL_HOURS` | `2` | `0.25` through `168` |
| `WINDOW_SIZE` | `100` | `1` through `1000` |
| `MAX_FETCH_CONCURRENCY` | `4` | `1` through `16` |
| `STATIC_FETCH_TIMEOUT_SECONDS` | `15` | `1` through `120` |
| `BROWSER_FETCH_TIMEOUT_SECONDS` | `35` | `1` through `300` |
| `BROWSER_ENABLED` | `false` | enable the live fallback only in an isolated runtime |
| `CHROMIUM_BINARY` | none | existing Chromium executable when browser is enabled |
| `CHROMEDRIVER_PATH` | none | existing matching driver when browser is enabled |
| `BROWSER_NO_SANDBOX` | `false` | container-only compatibility switch |
| `MAX_FETCH_ATTEMPTS` | `3` | `1` through `10` |
| `ANTHROPIC_MODEL` | none | nonempty Anthropic model ID supplied by the operator |
| `ANTHROPIC_API_KEY` | none | required only before a live model call |
| `SHADOW_MODE` | `true` | common true/false spellings |
| `DATA_DIR` | `/app/data` | private base and generated-document root |
| `STATE_DIR` | `/app/state` | private state root |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |

Compose also reads `AUTO_INTERNER_DATA_DIR` and `AUTO_INTERNER_STATE_DIR` for host bind
mounts and `HEALTHCHECK_MAX_AGE_SECONDS` for heartbeat staleness. The Pi 4B defaults are
`AUTO_INTERNER_MEMORY_LIMIT=1536m`,
`AUTO_INTERNER_MEMORY_RESERVATION=256m`, and `AUTO_INTERNER_CPUS=2.0`. Adjust those
deployment limits only after the target-host smoke test and soak measurements. These
are deployment settings rather than application-domain settings.
