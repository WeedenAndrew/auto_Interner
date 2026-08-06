# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.12.13-slim-bookworm

FROM ${PYTHON_IMAGE} AS wheel-builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip wheel --wheel-dir /wheels ".[browser]"

FROM ${PYTHON_IMAGE} AS runtime

ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/auto-interner \
    DATA_DIR=/app/data \
    STATE_DIR=/app/state \
    CHROMIUM_BINARY=/usr/bin/chromium \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver \
    BROWSER_ENABLED=true \
    BROWSER_NO_SANDBOX=true \
    HEARTBEAT_PATH=/app/state/heartbeat.json \
    HEALTHCHECK_MAX_AGE_SECONDS=10800

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        chromium \
        chromium-driver \
        git \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${APP_GID}" auto-interner \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home \
        --shell /usr/sbin/nologin auto-interner

COPY --from=wheel-builder /wheels /wheels
RUN python -m pip install --no-index --find-links=/wheels "auto-interner[browser]==0.1.0" \
    && rm -rf /wheels \
    && mkdir -p /app/data /app/state /home/auto-interner/.cache \
    && chown -R "${APP_UID}:${APP_GID}" /app /home/auto-interner

WORKDIR /app
USER ${APP_UID}:${APP_GID}

HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
    CMD ["python", "-m", "auto_interner.healthcheck"]

ENTRYPOINT ["/usr/bin/tini", "--", "auto-interner"]
CMD ["daemon"]
