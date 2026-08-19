# Security policy

## Reporting a vulnerability

Please do not publish credentials, private resume data, or exploitable details in a
public issue. Report security problems through a private GitHub security advisory when
that feature is enabled; otherwise, contact the repository owner directly.

Include the affected component, reproduction steps using fictional data, impact, and
any suggested mitigation. Do not test against private systems or third-party services
without authorization.

## Security scope

Security-sensitive boundaries include URL validation and redirects, path containment,
prompt injection, model-output validation, secrets and PII handling, atomic state
commits, pipeline locking, and container isolation. A path escape, SSRF path, secret
leak, unsupported resume claim, or state-corruption bug blocks release.

Static HTTP connections are restricted to validated public addresses, use bounded
responses, and revalidate redirects. Selenium processes untrusted page content and
should not be enabled outside an isolated runtime. CAPTCHA, authentication, and access
control bypasses are out of scope.

Git snapshot acquisition accepts only the configured SimplifyJobs HTTPS repository
pattern. It disables redirects, interactive credentials, hooks, shell execution, and
non-HTTPS protocols, then reads the bounded JSON blob from a fixed commit without a
checkout. The cache and processed-commit marker belong under the private state root.

Generated-resume paths use normalized bounded components, reject reserved Windows names
and symbolic company directories, and are resolved under the configured data root before
and after lazy directory creation. Existing output paths are never silently overwritten.
Dedupe reads filenames only from the current cycle's safe company directory; malformed,
future-dated, and non-regular DOCX entries are ignored with sanitized anomaly records.

Semantic screening treats every posting as untrusted data. The live model boundary is
limited to a fixed HTTPS provider endpoint with bounded responses and an exact tool-call
envelope. Provider output is revalidated locally with no coercion or extra fields. Low
confidence cannot cause an automatic disqualification, and sanitized failures never
persist API keys, provider bodies, or posting text.

Resume rewriting uses a separate model-safe projection that excludes the pre-section
contact block and redacts contact patterns elsewhere. Hyperlink/contact paragraphs are
read-only. A local validator rejects missing or invented sections, changed metrics,
new technologies, stronger proficiency, contact data, duplicate locators, and unknown
paragraphs before the DOCX writer runs. The base file is hash-checked before and after
assembly; the output is scrubbed, reopened, validated, and linked without replacement.

The complete worker holds a nonblocking operating-system lock for the full source scan.
A source version is checkpointed only after every terminal result is present in the
seen set and the state logs reconcile. Shadow, retry, exception, and reconciliation
failure paths never advance that marker. Heartbeats and run summaries contain counts,
paths, identifiers, statuses, and sanitized failure types—not posting bodies, model
payloads, résumé content, or credentials.

The production Compose service exposes no ports and runs with a read-only root
filesystem, all Linux capabilities dropped, `no-new-privileges`, bounded PIDs/memory,
tmpfs browser scratch space, and a fixed non-root UID/GID. Private data and state are
limited to explicit SSD-backed bind mounts. Missing bind paths are rejected rather than
created implicitly.

Chromium uses `--no-sandbox` only inside that isolated container; host execution keeps
the browser disabled by default. The worker still requires outbound network access for
public postings and the configured model provider. The offline fixture and browser
smoke services use `network_mode: none`.

Docker Compose reads the API key from the ignored local `.env`. Treat membership in the
host `docker` group as root-equivalent, keep `.env` mode `0600`, never share resolved
`docker compose config` output, and store backups on a second physical or encrypted
remote destination.
