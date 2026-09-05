"""Demo HTTP metrics exporter used to exercise the monitoring stack.

Emits Prometheus-style metrics (requests, errors, latency histogram) and
structured log lines so the whole pipeline — scraping, recording rules,
dashboards, log shipping — has live data to chew on.

Metrics emitted:
  http_requests_total{service, status, method}
  http_request_duration_seconds_bucket{service, method, le}
  http_request_duration_seconds_sum{service, method}
  http_request_duration_seconds_count{service, method}
"""

from __future__ import annotations

import logging
import os
import random
import time

from prometheus_client import Counter, Gauge, Histogram, start_http_server

SERVICE = os.environ.get("SERVICE_NAME", "demo")
PORT = int(os.environ.get("PORT", "8000"))
logger = logging.getLogger(__name__)

REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests handled",
    ["service", "method", "status"],
)
LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["service", "method"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 2.5, 5.0, 10.0),
)

# Simulated batch job (e.g. nightly settlement): exposes the last-success
# timestamp consumed by the `freshness` SLI recording rules.
BATCH_INTERVAL = float(os.environ.get("BATCH_INTERVAL_SECONDS", "45"))
BATCH_FAIL_RATE = float(os.environ.get("BATCH_FAIL_RATE", "0.03"))
BATCH_LAST_SUCCESS = Gauge(
    "batch_job_last_success_ts_seconds",
    "Unix timestamp (seconds) of the last successful batch run",
    ["service"],
)
BATCH_RUNS = Counter("batch_job_runs_total", "Total batch runs", ["service", "status"])

METHODS = ["GET", "POST", "PUT", "DELETE"]


def sample_request() -> tuple[str, int, float]:
    """Return (method, status, latency_seconds) for one synthetic request."""
    method = random.choices(METHODS, weights=[60, 20, 15, 5])[0]

    # Mostly healthy; occasionally slow, rarely 5xx.
    roll = random.random()
    if roll < 0.002:  # 0.2% -> 99.8% availability
        status = 500
        latency = random.uniform(0.05, 2.0)
    elif roll < 0.004:
        status = 503
        latency = random.uniform(0.05, 1.5)
    elif roll < 0.012:
        status = random.choice([400, 404, 422])
        latency = random.uniform(0.005, 0.05)
    else:
        status = 200
        # Log-normal-ish tail so p99 sits meaningfully below the SLO thresholds.
        latency = min(10.0, random.lognormvariate(mu=-1.6, sigma=0.9))
        if latency > 0.9 and random.random() < 0.35:
            latency = random.uniform(0.3, 3.0)  # occasional slow outliers
    return method, status, latency


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=f"service={SERVICE} level=%(levelname)s ts=%(asctime)s %(message)s",
    )
    start_http_server(PORT)
    logger.info("demo exporter %s listening on :%d", SERVICE, PORT)

    last_batch = 0.0
    while True:
        now = time.time()
        if now - last_batch >= BATCH_INTERVAL:
            last_batch = now
            if random.random() < BATCH_FAIL_RATE:
                BATCH_RUNS.labels(SERVICE, "failed").inc()
                logger.error("batch run failed — freshness will degrade")
            else:
                BATCH_RUNS.labels(SERVICE, "success").inc()
                BATCH_LAST_SUCCESS.labels(SERVICE).set(now)
                logger.info("batch run ok")

        method, status, latency = sample_request()
        REQUESTS.labels(SERVICE, method, status).inc()
        LATENCY.labels(SERVICE, method).observe(latency)
        if status >= 500:
            logger.error(
                "request failed method=%s status=%d latency=%.3fs", method, status, latency
            )
        else:
            logger.info("request ok method=%s status=%d latency=%.3fs", method, status, latency)
        time.sleep(random.uniform(0.05, 0.3))


if __name__ == "__main__":
    main()
