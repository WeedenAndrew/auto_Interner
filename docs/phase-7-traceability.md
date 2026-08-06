# Phase 7 traceability

The repository now contains the Phase 7 container and operations implementation. The
hardware-dependent arm64 and 24-hour soak gates remain pending until they run on the
Raspberry Pi 4B 4 GB server with its USB-attached M.2 SATA SSD.

| Contract | Implementation | Current evidence |
|---|---|---|
| Linux multi-architecture image | Python 3.12 Bookworm multi-arch base | Dockerfile contract test; live build pending locally |
| Non-root worker | fixed UID/GID `10001` | Dockerfile and CI image-user check |
| Matching browser packages | Debian `chromium` plus `chromium-driver` | offline browser-smoke service and arm64 workflow |
| Bind-mounted durability | configurable host data/state bind mounts | Compose contract and Pi restart procedure |
| `NF-REL-004` restart persistence | `restart: unless-stopped` plus host mounts | Pi reboot drill pending |
| `NF-REL-005` rebuild persistence | image-independent host paths | Pi rebuild drill pending |
| Graceful shutdown | daemon `SIGINT`/`SIGTERM` event handling | scheduler tests; container stop drill pending |
| `NF-PER-006` idle memory | `1536m` hard worker limit on the 4 GB host | target measurement pending |
| `NF-PER-007` browser peak | two-CPU default and bounded worker resources | target measurement pending |
| `NF-PER-010` logs | `10m` × three-file `json-file` rotation | Compose contract; 24-hour observation pending |
| `NF-PRT-002` x86_64 container | container CI job | executes after repository publication |
| `NF-PRT-003` arm64 image/browser | manual self-hosted arm64 workflow | target Pi execution pending |
| Health/heartbeat | bounded local JSON health check | unit tests and Compose healthcheck |
| Container isolation | read-only root, no ports, all capabilities dropped | Compose security contract |
| Runtime privacy | `.dockerignore` excludes secrets, runtime, tests, and private documents | build-context contract test |

The default worker uses outbound networking because it must fetch public listings and
call the configured model provider. It exposes no inbound ports. Chromium uses
`--no-sandbox` only inside the non-root, capability-dropped, read-only container; the
separate browser smoke runs with networking disabled.

Phase 7 acceptance requires all of the following on Ubuntu Server 24.04 LTS arm64:

1. `docker compose build --pull worker` succeeds.
2. Fixture and browser smoke services pass.
3. The offline Python suite passes on arm64.
4. State and generated data survive container recreation, image rebuild, and host reboot.
5. Twelve scheduled cycles complete without overlap or unbounded resource growth.
6. The 24-hour shadow-mode soak checklist in `raspberry-pi.md` is recorded and reviewed.
