# Realtime monitoring stack — CLI image.
#
# Provides the `monitoring-stack` command together with everything the code
# needs at runtime:
#   * the package's Python deps (PyYAML, requests, prometheus-client),
#     pinned in `requirements.lock` for reproducible builds,
#   * the docker CLI **and** the docker compose plugin, because
#     `deploy` / `status` / `logs` / `down` shell out to `docker compose`.
#
# Targets (default = the hardened `runtime` image):
#   * runtime (default) — the CLI, running as a non-root user with a HEALTHCHECK:
#       docker build -t monitoring-stack:local .
#   * dev — same deps plus the `[dev]` extras (pinned in `requirements-dev.lock`,
#     includes tox); entrypoint is pytest:
#       docker build --target dev -t monitoring-stack:dev .
#
# Multi-arch: arch detection uses TARGETARCH (buildx) so cross-compiled builds
# pick the right docker binaries, e.g.:
#   docker buildx build --platform linux/amd64,linux/arm64 -t monitoring-stack:local .
#
# Run — generate/validate configs against your checkout. `--user` keeps the
# generated files owned by you instead of the image's `stack` user:
#   docker run --rm -v "$PWD":/app --user "$(id -u):$(id -g)" monitoring-stack:local config
#   docker run --rm -v "$PWD":/app --user "$(id -u):$(id -g)" monitoring-stack:local validate
#
# Run — full deploy. The checkout must be mounted at its own host path (the
# daemon resolves the compose file's bind mounts against host paths), the
# container's docker CLI needs the daemon socket, and host networking lets the
# health checks reach the published ports:
#   docker run --rm --network host \
#     -v "$PWD":"$PWD" -w "$PWD" \
#     -v /var/run/docker.sock:/var/run/docker.sock \
#     --user "$(id -u):$(getent group docker | cut -d: -f3)" \
#     monitoring-stack:local deploy
#   (pass --env-file .env for PAGERDUTY_ROUTING_KEY / Grafana credentials)
#
# Run — tests with the dev image:
#   docker run --rm -v "$PWD":/app --user "$(id -u):$(id -g)" monitoring-stack:dev
#
# The Makefile wraps all of the above: make docker-build / docker-config /
# docker-validate / docker-test / docker-deploy / docker-status / docker-down /
# docker-tox / docker-tox-integration.

FROM python:3.12-slim AS base

# --- docker CLI + compose plugin (client only) --------------------------------
# Static binaries are used instead of the docker.io metapackage to keep the
# image slim — no daemon, no systemd. The CLI/plugin versions are build args so
# they can be bumped without rewriting the whole step.
ARG DOCKER_CLI_VERSION=27.3.1
ARG DOCKER_COMPOSE_VERSION=2.29.7
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl ca-certificates; \
    case "${TARGETARCH:-$(uname -m)}" in \
      amd64|x86_64)  DOCKER_ARCH=x86_64 ;; \
      arm64|aarch64) DOCKER_ARCH=aarch64 ;; \
      *) echo "unsupported architecture: ${TARGETARCH:-$(uname -m)}"; exit 1 ;; \
    esac; \
    curl -fsSL "https://download.docker.com/linux/static/stable/${DOCKER_ARCH}/docker-${DOCKER_CLI_VERSION}.tgz" -o /tmp/docker.tgz; \
    tar -xzf /tmp/docker.tgz -C /tmp docker/docker --strip-components=1; \
    install -m 0755 /tmp/docker /usr/local/bin/docker; \
    rm -rf /tmp/docker.tgz /tmp/docker; \
    mkdir -p /usr/local/lib/docker/cli-plugins; \
    curl -fsSL "https://github.com/docker/compose/releases/download/v${DOCKER_COMPOSE_VERSION}/docker-compose-linux-${DOCKER_ARCH}" \
      -o /usr/local/lib/docker/cli-plugins/docker-compose; \
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose; \
    apt-get purge -y --auto-remove curl ca-certificates; \
    rm -rf /var/lib/apt/lists/*; \
    docker --version; \
    docker compose version

# --- Python deps: pinned via lock files, then the package itself -------------
WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# Runtime deps first, so this layer only rebuilds when the lock changes.
COPY requirements.lock ./
RUN pip install -r requirements.lock

COPY pyproject.toml README.md ./
COPY realtime_monitoring_stack/ realtime_monitoring_stack/
COPY demo/ demo/
# --no-deps: every dependency already came from the lock file.
RUN pip install --no-deps .

# --- Dev target: same deps + test/lint/tox tooling ---------------------------
# Runs `pytest` (pyproject.toml's `[tool.pytest.ini_options]` applies the
# coverage gate) when started with no arguments.
FROM base AS dev

# Editable-style resolution: the host checkout is mounted over /app at runtime,
# and PYTHONPATH keeps it ahead of the site-packages copy installed in `base`,
# so pytest runs against (and coverage measures) the mounted sources — the
# same behavior as `pip install -e ".[dev]"` in the venv workflow.
ENV PYTHONPATH=/app
COPY requirements-dev.lock ./
RUN pip install -r requirements-dev.lock
ENTRYPOINT []
CMD ["pytest"]

# --- Runtime target (default): hardened CLI image -----------------------------
FROM base AS runtime

# Run as a non-root user. /app is chowned so generated configs can be written
# in place; when mounting your checkout over /app, pass `--user "$(id -u):$(id -g)"`
# (or keep the default and fix ownership afterwards).
RUN useradd --create-home --uid 1000 stack \
    && mkdir -p /app/generated \
    && chown -R stack:stack /app
USER stack

# The image is meant for one-shot invocations, not a long-running daemon, so
# the healthcheck simply confirms the CLI starts — it is reported by
# `docker inspect` / `docker ps` and can gate compose healthchecks.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["monitoring-stack", "--help"]

# The CLI resolves services.yaml / generated/ / docker-compose.yml relative to
# the working directory — mount the checkout at /app (see header comment).
ENTRYPOINT ["monitoring-stack"]
CMD ["--help"]