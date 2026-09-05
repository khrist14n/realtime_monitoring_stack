# Realtime Monitoring Stack

A deployable, enterprise-grade monitoring stack built on **Prometheus + Grafana + Loki**,
with **custom dashboards**, **PagerDuty integration**, and **SLO tracking** — all
provisioned from a single Python package.

```
┌────────────────────────────────────────────────────────────────────┐
│                      Docker Compose (realtime-monitoring)          │
│                                                                    │
│   services.yaml ──► monitoring-stack config ──► generated/         │
│   (catalog+SLOs)        (Python)              │                    │
│                                              ▼                    │
│   ┌─────────────┐   ┌──────────────┐   ┌───────────┐              │
│   │  Prometheus │◄──│ Alertmanager │──►│ PagerDuty │              │
│   │  (metrics + │   │ (severity    │   │ (pages /  │              │
│   │   SLO rules)│   │  routing)    │   │  warnings)│              │
│   └──────┬──────┘   └──────────────┘   └───────────┘              │
│          │                     ┌───────────┐                      │
│          │ scrape              │  Grafana  │── custom dashboards  │
│          │                     │ (prov.    │   • Services Overview│
│          ▼                     │  via file)│   • SLO & Error Bud. │
│   demo apps / node-exporter / cadvisor      └───────────▲────────┘
│                                                          │ logs
│   ┌──────────────┐    ┌────────────┐    ┌────────────┐   │
│   │  Promtail    │───►│    Loki    │────┘ (Loki data │
│   │ (docker logs)│    │            │    source)      │
│   └──────────────┘    └────────────┘    └────────────┘
└────────────────────────────────────────────────────────────────────┘
```

## What you get

| Component    | Role                                                              |
|--------------|-------------------------------------------------------------------|
| Prometheus   | Scrapes services + infra, evaluates **SLO recording & alert rules** |
| Alertmanager | Routes alerts to **PagerDuty** by severity (`page` vs `warning`)   |
| Grafana      | **Custom dashboards**, Prometheus + Loki datasources, file provisioning |
| Loki         | Centralized log storage (30d retention)                           |
| Promtail     | Ships Docker container logs to Loki with `service` labels          |
| node-exporter / cadvisor | Host + container metrics                               |
| demo apps    | Synthetic HTTP traffic so every panel has live data               |

All configs are **generated, not hand-maintained**: edit `services.yaml`,
re-run `monitoring-stack config`, and the scrape jobs, SLO rules, dashboards,
and log shipping all update together.

## Quick start

Requires Python ≥ 3.10 and Docker with the compose plugin.

```bash
# 1. Install the CLI (into a venv, project-local)
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Optional: configure PagerDuty (see below). Without it the stack
#    still deploys; the receiver is generated with a placeholder key.
cp .env.example .env

# 3. Generate configs, start the stack, run health checks
monitoring-stack deploy

# 4. Open the dashboards
open http://localhost:3000        # Grafana (admin / admin — set GF_SECURITY_ADMIN_PASSWORD!)
open http://localhost:9090        # Prometheus
```

Other commands:

| Command                     | What it does                                            |
|-----------------------------|---------------------------------------------------------|
| `monitoring-stack config`   | (Re)generate all configs into `generated/`              |
| `monitoring-stack validate` | Validate generated YAML/JSON + cross-references         |
| `monitoring-stack status`   | Container status + Prometheus target health             |
| `monitoring-stack check`    | Health checks against a running stack                   |
| `monitoring-stack logs`     | Tail container logs (`logs prometheus` for one service) |
| `monitoring-stack down`     | Stop the stack                                          |

`--services services.yaml` selects the catalog, `--out generated` the output dir.

## Containerized CLI (Docker)

Don't want a local venv? The root `Dockerfile` builds an image with the
`monitoring-stack` CLI and everything it needs at runtime — Python deps
pinned in `requirements.lock`, plus the **docker CLI and compose plugin**,
because `deploy`/`status`/`logs`/`down` shell out to `docker compose`. The
image runs as a non-root user and carries a HEALTHCHECK.

```bash
# Build the CLI image (runtime target)
docker build -t monitoring-stack:local .

# Generate / validate configs against your checkout
# (--user keeps the generated files owned by you, not the container user)
docker run --rm -v "$PWD":/app --user "$(id -u):$(id -g)" monitoring-stack:local config
docker run --rm -v "$PWD":/app --user "$(id -u):$(id -g)" monitoring-stack:local validate

# Full deploy — the container's docker CLI talks to the host daemon via the
# socket. The checkout is mounted at its own host path ($PWD:$PWD) because the
# daemon resolves the compose file's bind mounts against host paths; host
# networking lets the health checks reach the published ports.
# (--env-file .env passes PAGERDUTY_ROUTING_KEY / Grafana credentials)
docker run --rm --network host \
  -v "$PWD":"$PWD" -w "$PWD" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --user "$(id -u):$(getent group docker | cut -d: -f3)" \
  monitoring-stack:local deploy
```

`make` shortcuts:

| Target               | What it does                                        |
|----------------------|-----------------------------------------------------|
| `make docker-build`  | Build the CLI image (`monitoring-stack:local`)      |
| `make docker-config` | Generate configs inside the container (as your user)|
| `make docker-validate` | Validate generated configs inside the container   |
| `make docker-test`   | Build the `dev` image and run pytest inside it      |
| `make docker-deploy` | Deploy the stack via the container (needs socket)   |
| `make docker-status` | Container status + health checks via the container  |
| `make docker-down`   | Stop the stack via the container                    |
| `make docker-tox`    | Run `tox` (test/lint/validate envs) in the dev image|
| `make docker-tox-integration` | Run `tox -e integration` (stack must be deployed) |

The **dev target** (`docker build --target dev -t monitoring-stack:dev .`)
adds the `[dev]` extras (pytest, ruff, tox — pinned in `requirements-dev.lock`)
and runs `pytest` by default, so the whole test suite — with its 80% coverage
gate — runs without a local venv:

```bash
docker run --rm -v "$PWD":/app --user "$(id -u):$(id -g)" monitoring-stack:dev
```

### Locked dependencies & multi-arch

Both images install **pinned versions** from `requirements.lock` (runtime) and
`requirements-dev.lock` (dev), so builds are reproducible — see the header
comments in those files for how to regenerate them. Multi-arch builds work via
buildx (`TARGETARCH` selects the matching docker CLI/compose binaries):

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t monitoring-stack:local .
```

## Podman instead of Docker

The CLI works with **podman** as the container engine. Select it explicitly or
let the CLI auto-detect it (auto-detection prefers `docker`, and falls back to
`podman` when no `docker` binary is on the `PATH`):

```bash
export MONITORING_STACK_RUNTIME=podman
monitoring-stack deploy
```

Requirements & notes:

- **`podman compose`** must be available — podman's `compose` subcommand needs
  `docker-compose` v2 or `podman-compose` installed alongside podman.
- **promtail** ships Docker container logs by mounting the engine socket. With
  podman, point that mount at podman's API socket in `docker-compose.yml`:
  `- /run/podman/podman.sock:/var/run/docker.sock:ro` (rootful). For rootless
  podman, use the per-user socket (e.g. `/run/user/$UID/podman/podman.sock`).
- `monitoring-stack validate` / `check` / `status` are engine-agnostic (HTTP).

## PagerDuty integration

1. In PagerDuty: **Integrations → Events API v2** → create an integration and copy
   the **Integration Key** (this is the routing key).
2. Put it in `.env`: `PAGERDUTY_ROUTING_KEY=your_key_here`
3. Regenerate the config: `monitoring-stack config` (or `deploy`).

Alertmanager then maps alert severity to PagerDuty urgency:

| Alert                                              | Severity | PagerDuty |
|----------------------------------------------------|----------|-----------|
| SLO fast burn (1h & 5m windows > 14.4×)            | `page`   | **high urgency** (critical) |
| SLO slow burn (6h & 30m windows > 6×)              | `warning`| **low urgency** (warning)   |
| Anything else (e.g. infra alerts you add)          | default  | error      |

`validate` (and `deploy`) warn loudly if the key is missing or still a placeholder.

## SLO model

Define services and SLOs once in `services.yaml`; the generator produces:

- **Recording rules** per service/SLO:
  - `slo:{service}:{sli}:errors:ratio_rate{5m,30m,1h,6h,30d}` — error fraction
  - `slo:{service}:{sli}:burn_rate{1h,5m,6h,30m}` — burn rate vs error budget
  - `slo:{service}:{sli}:error_budget_remaining` — 1 − (errors / budget), negative = exhausted

Rule names must be valid Prometheus metric names, so characters that aren't
allowed there are replaced with `_` — e.g. a service named `api-gateway`
produces `slo:api_gateway:availability:errors:ratio_rate5m` (labels, scrape
jobs, and alerts keep the original name).
- **Alert rules** implementing the Google SRE Workbook
  *multi-window, multi-burn-rate* pattern — the fast window catches spikes fast,
  the slow window avoids paging on blips.

Four SLI types are supported:

| SLI | What counts as an error | Required fields |
|---|---|---|
| `availability` | requests matching `error_status_regex` (default 5xx) | — |
| `latency` | requests slower than the threshold | `latency_threshold_ms` |
| `throughput` | time spent below the minimum request rate (good = `min(rate / target, 1)`) | `throughput_per_sec` |
| `freshness` | time the last successful batch run is older than the threshold | `max_freshness_seconds` |

```yaml
services:
  - name: api-gateway
    team: platform
    targets: ["api-gateway:8000"]
    slos:
      - name: availability
        sli: availability
        target: 0.999              # error budget: 0.1% of requests may 5xx
        window: 30d
      - name: latency
        sli: latency
        target: 0.99               # 99% of requests must be < 300ms
        latency_threshold_ms: 300
        window: 30d
      - name: throughput
        sli: throughput
        target: 0.99               # 99% of the time traffic stays >= 2 req/s
        throughput_per_sec: 2
        window: 30d

  - name: payments
    slos:
      - name: freshness           # e.g. a settlement batch that must run on time
        sli: freshness
        target: 0.99               # 99% of the time the last success is < 2 min old
        max_freshness_seconds: 120
        window: 30d
```

Freshness SLIs expect a `batch_job_last_success_ts_seconds` gauge (unix
timestamp of the last successful run) — the demo apps emit one. All four types
feed the same recording-rule machinery, so burn rates, error budgets, alerts,
and dashboard panels work identically.

**Expected application metrics** (the demo apps emit these):

| Metric                                 | Labels                              | Used for            |
|----------------------------------------|-------------------------------------|---------------------|
| `http_requests_total`                  | `service`, `status`, `method`       | availability SLI    |
| `http_request_duration_seconds_bucket` | `service`, `method`, `le` (histogram)| latency SLI        |

Both metric names and the error-status regex are configurable globally or per
service under `metrics:` (see `services.yaml`).

## Custom dashboards

Generated dashboards reference datasources by provisioned uid and a
multi-select `$service` variable, so adding a service to `services.yaml`
immediately adds it to every dashboard.

- **Services Overview** (`uid: services-overview`) — RED metrics: requests/sec,
  error rate, p99 latency, 30d availability; plus a **Loki log-volume panel**
  for log↔metric correlation.
- **SLO & Error Budget** (`uid: slo-error-budget`) — per-service/SLO budget
  gauges (green/yellow/red thresholds), error budget remaining over time,
  burn-rate panels with threshold reference lines at 6×/14.4×.

Dashboards live in `generated/grafana/dashboards/` and are hot-reloaded by the
file provider (30s). You can also copy them into the **Grafana UI** or iterate
on them in the UI and export — the provisioning is deliberately
`allowUiUpdates: true`.

## Extending

- **Add a service**: add an entry to `services.yaml`, run `monitoring-stack config`.
- **New infra alerts**: add a rules file to `generated/prometheus/rules/` (or a
  generator in `realtime_monitoring_stack/prometheus.py`) — reference it in
  `rule_files` in `prometheus.yml`.
- **More receivers**: extend `alertmanager.build_alertmanager_config()` (Slack,
  email, Opsgenie…) and route by severity label.
- **Grafana alerting / annotations**: enable the Grafana alerting feature and
  use the provisioned datasources; the dashboards are already annotation-ready.

## Testing

Run the full suite from a clean checkout:

**Step 1 — one-time setup** (project-local venv, nothing global):

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

or, if you have `make`:

```bash
make setup
```

**Step 2 — unit tests** (`pytest`, no network/Docker needed). Coverage is
measured automatically and the run **fails below 80%** (config in
`pyproject.toml`):

```bash
pytest          # or: make test
```

**Step 3 — config-level validation**: generate the config tree from
`services.yaml`, then validate it (YAML/JSON parsing, rule-file
cross-references, PagerDuty key presence):

```bash
monitoring-stack config
monitoring-stack validate        # or: make validate
```

**Step 4 — PromQL / Alertmanager validation with promtool + amtool** (runs in
Docker so you get the real Prometheus toolchain; needs network to pull images):

```bash
make config      # ensure rules are current
make promtool
```

**Step 5 — live stack checks**: deploy and verify end-to-end:

```bash
monitoring-stack deploy          # builds demo apps, starts stack, health checks
monitoring-stack status          # container status + scrape-target summary
```

**Step 6 — integration smoke tests** (against the deployed stack, skipped by
default):

```bash
MONITORING_STACK_INTEGRATION=1 pytest -m integration
```

These verify what the generators promise, but against the live services:
provisioned dashboards contain panels, demo-app scrape targets are UP, the SLO
recording rules (availability, throughput, freshness) are producing series, and
Loki is ready. In CI this exact step runs in the `deploy-integration` job.

### Linting

```bash
make lint        # ruff check + ruff format --check   (or: ruff check . && ruff format --check .)
make lint-fix    # auto-fix and reformat
```

Ruff is configured in `pyproject.toml` (line length 100, isort import sorting)
and runs in pre-commit, tox (`tox -e lint`), and the CI `lint` job.

### What the tests cover

| Test file | Covers |
|---|---|
| `tests/test_models.py` | services.yaml parsing, SLO validation (sli type, target range, latency threshold, duplicate names, metric overrides), rule-name sanitization (always valid metric names) |
| `tests/test_prometheus.py` | scrape jobs, recording-rule names/windows, burn-rate math, multi-window multi-burn-rate alerts, rule names valid + internally consistent |
| `tests/test_alertmanager.py` | PagerDuty receivers, severity routing, placeholder-key fallback |
| `tests/test_dashboards.py` | panel structure, per-service panels, datasource uids, templating variable, queries reference sanitized rule metrics |
| `tests/test_render.py` | generated file tree, YAML/JSON validity, rule-file ↔ disk consistency, validation pass |
| `tests/test_validators.py` | every `validate` failure mode: bad YAML/JSON, missing rule files, empty rule groups, missing pagerduty receiver, promtail/dashboard issues |
| `tests/test_cli.py`, `tests/test_deploy.py` | CLI dispatch for every command, compose wrappers, health-check logic, docker↔podman runtime selection (all with fakes) |
| `tests/test_demo.py` | demo exporter: sampling distribution, deterministic seeding, metric emission |
| `tests/test_integration.py` | smoke tests against a deployed stack (env-gated, `-m integration`) |

### Adding a test

Tests use the `cfg` fixture (parses `services.yaml`) and the `rendered` fixture
(renders the full tree into a temp dir). Example:

```python
def test_my_service_gets_a_scrape_job(cfg):
    jobs = {j["job_name"] for j in prometheus.build_prometheus_config(cfg)["scrape_configs"]}
    assert "service/my-service" in jobs
```

Tests are hermetic — no network, no Docker — so they run anywhere `pytest`
runs, including CI.

## Layout

```
realtime_monitoring_stack/   # Python package (models, generators, deploy, CLI)
Makefile                     # make setup / test / validate / promtool / deploy …
Dockerfile                   # containerized CLI (see “Containerized CLI (Docker)”)
requirements*.lock           # pinned deps for the Docker images (reproducible)
.env.example                 # optional PagerDuty/Grafana/runtime settings
.github/workflows/ci.yml     # CI: tests + coverage, validation, promtool checks
tox.ini, .pre-commit-config.yaml
services.yaml                # service catalog + SLO definitions
docker-compose.yml           # the stack itself (mounts generated/)
demo/                        # synthetic metrics/logs exporter for live data
generated/                   # ALL configs, produced by `monitoring-stack config`
tests/                       # pytest suite over the generators
```

## CI & dev tooling

- **GitHub Actions** (`.github/workflows/ci.yml`):
  - `lint` job — `ruff check` + `ruff format --check`
  - `test` job (every push/PR) — `pytest` with the 80% coverage gate, config
    generation + validation, and the **HTML coverage report uploaded as an
    artifact** (`coverage-report`)
  - `docker-cli` job — builds the Dockerfile and re-runs config generation,
    validation, the pytest suite, and tox **inside the container**, so the
    image itself stays working
  - `promtool` job — promtool + amtool validation via Docker
  - `deploy-integration` job (pushes to main / manual dispatch) — actually
    deploys the stack with `monitoring-stack deploy`, then runs
    `MONITORING_STACK_INTEGRATION=1 pytest -m integration` against the live
    stack. Gated off PRs to keep PR CI fast and cheap.
- **tox** (`tox.ini`) runs the same steps consistently across machines:
  `tox` (tests), `tox -e lint` (ruff), `tox -e validate` (configs),
  `tox -e integration` (smoke tests).
- **pre-commit** (`.pre-commit-config.yaml`) enforces hygiene + ruff on commit
  (`pre-commit install`; run all files with `pre-commit run --all-files`).
- **Makefile**: `make lint` and `make lint-fix` wrap the ruff commands.

## Production notes

- Change `GF_SECURITY_ADMIN_PASSWORD` (and set up Grafana auth) before exposing
  the stack beyond localhost.
- Data volumes (`prometheus-data`, `grafana-data`, `loki-data`) persist across
  restarts; backups are your responsibility.
- Prometheus retention is 30d and Loki 30d by default — tune to your compliance
  needs.
- The compose file pins exact image tags; bump them deliberately.