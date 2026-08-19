# Worked example — a curated resume

Real output. The corpus below was built from the public repositories at
<https://github.com/WeedenAndrew>, nothing else.

## The posting

```
Software Engineering Intern — Summer 2027

We are looking for a student who likes building things end to end.

Requirements:
- Python
- Familiarity with Git and version control
- You have written unit tests
- Comfortable reading and debugging code you did not write

Nice to have:
- Docker
- SQL
- Experience with REST APIs
- Any shipped side project, however small
```

## The corpus

Four blocks, ingested from GitHub. Every bullet is a fact GitHub asserts —
repository name, description, primary language. Nothing inferred.

- **auto_Interner** — tags: `python`
- **Goblin-Flip** — tags: `dart`
- **neetcode-submissions** — tags: `python`
- **WeedenAndrew** — tags: `—`

## The tailored resume

```
PROJECTS
--------
auto_Interner  (2026)
  • Automatic Internship application pipeline.
  • Written primarily in Python.
neetcode-submissions  (2026)
  • My NeetCode.io problem submissions.
  • Written primarily in Python.
```

## The coverage report

```
COVERAGE — 50% of requirement weight surfaced

Surfaced:
  [required ] python  <- gh-auto_interner

GAPS — nothing in your corpus supports these:
  [preferred] docker
       posting said: "Docker"
  [preferred] rest
       posting said: "Experience with REST APIs"
  [preferred] sql
       posting said: "SQL"

```

## Why this is the interesting part

Coverage is **50%**, and `docker`, `rest` and `sql` are reported as gaps.

The author has production experience with all three. A résumé generator
would infer them from context and write the bullet. This one cannot —
nothing in the corpus supports the claim, so it says so.

The gap is closed by *asking*:

> This role asks for docker and nothing in your corpus covers it. Have you
> used it anywhere — coursework, a side project, a job you haven't added
> yet? If not, skip it; a real gap is worth knowing about.

Answer it and the gap closes with your sentence. Skip it and it stays a gap,
reported honestly. Either way nothing is invented.

---

Reproduce:

```bash
PYTHONPATH=src python -m auto_interner.corpus  # see docs/examples/
```
