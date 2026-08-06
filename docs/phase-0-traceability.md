# Phase 0 traceability

**Gate result (2026-08-05):** formatting passed, lint passed, strict typing passed,
and 24 tests passed with 90.3% combined line/branch coverage on Python 3.12.

| Requirement | Implementation | Automated evidence |
|---|---|---|
| One validated `Settings` object | `src/auto_interner/config.py` | `tests/unit/test_config.py` |
| Explicit/current recruiting year | `Settings.from_env` | `F-CFG-001`, `F-CFG-002` |
| URL or year template | `Settings.source_url` | `F-CFG-003` through `F-CFG-006` |
| Bounded numeric work settings | explicit parsers and safe ranges | `F-CFG-007` |
| Stable shadow-mode parsing | explicit boolean parser | `F-CFG-008` |
| Key required only for live model work | runtime prerequisite check | `F-CFG-009` |
| Swappable nonempty model ID | `ANTHROPIC_MODEL` validation | model configuration unit tests |
| Base resume prerequisite | cycle-scoped path check | `F-CFG-010` |
| Lazy runtime layout | `ensure_runtime_layout` | `F-CFG-011` |
| Configured cycle controls paths | `cycle_data_dir` | `F-CFG-012` |
| Structured logs | `JsonFormatter` | log-injection unit test |
| No secret in diagnostics | `safe_summary` | CLI component test |
| Registered suite markers | `pyproject.toml` | pytest strict-marker startup |

## Intentional Phase 0 limits

- `config-check` is a diagnostic, not the future `run-once` or `daemon` pipeline.
- It makes no listing, browser, or model call.
- Runtime directories are not created during settings parsing.
- The base resume is checked for existence only; structural DOCX validation belongs to
  Phase 5.
- Docker and Compose files belong to Phase 7 and are not predeclared as working.
