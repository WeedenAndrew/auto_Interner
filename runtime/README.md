# Private runtime directory

This directory is the local bind-mount root used during development. Every child is
ignored by Git because it may contain a real base resume, tailored resumes, application
history, demonstration output, or decision records.

Expected local layout after a run needs it:

```text
runtime/
|-- data/<recruiting_year>/baseplate/base_resume.docx
|-- state/tmp/
`-- demo-state/
```

On the Raspberry Pi, use SSD-backed host paths such as
`/srv/auto-interner/data` and `/srv/auto-interner/state` rather than placing private
runtime data inside the repository. The Compose file reads those locations from
`AUTO_INTERNER_DATA_DIR` and `AUTO_INTERNER_STATE_DIR`.

The container runs as UID/GID `10001`; the two bind-mount directories and private base
résumé must be readable/writable by that identity. See `docs/raspberry-pi.md`.

Never place production files under `tests/fixtures/`.
