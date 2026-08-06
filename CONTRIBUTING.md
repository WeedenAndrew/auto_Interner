# Contributing

Auto Interner is built as gated vertical slices. Contributions should stay inside the
current phase, include tests for new behavior, and avoid describing planned features
as complete.

## Local setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

Run the complete local quality gate before opening a pull request:

```powershell
.\.venv\Scripts\python -m ruff format --check .
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m mypy
.\.venv\Scripts\python -m pytest --cov=auto_interner --cov-branch --cov-fail-under=85
```

## Change rules

- Reference documented test-case IDs in test names or docstrings when applicable.
- Add positive and negative regression examples for every screening rule.
- Inject clocks, network clients, browser factories, and model clients.
- Preserve the single-writer boundary for state and generated documents.
- Treat listing data, URLs, paths, posting text, and model output as untrusted.
- Update documentation when behavior or a public claim changes.

## Publication and test rules

- Public artifacts must stand on their own without editor, generator, or drafting
  provenance.
- Describe only behavior demonstrated by the repository; label future work as planned.
- Keep real resumes and personal details out of source, fixtures, logs, snapshots, and
  decision records.
- Default tests must use fictional data and fake network, browser, and model boundaries.
- Live tests must be explicit, opt-in, and excluded from the default suite.
- Only repository maintainers may authorize staging, commits, pushes, or remote changes.

## Privacy

Never commit a real resume, generated application document, API key, `.env` file,
application history, browser profile, or production runtime state. Test identities and
postings must be fictional or sanitized.
