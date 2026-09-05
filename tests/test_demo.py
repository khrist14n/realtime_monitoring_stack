from __future__ import annotations

import random

from demo import app

VALID_STATUSES = {200, 400, 404, 422, 500, 503}


def test_sample_request_shape():
    for _ in range(200):
        method, status, latency = app.sample_request()
        assert method in app.METHODS
        assert status in VALID_STATUSES
        assert 0 < latency <= 10.0


def test_sample_request_is_seeded_deterministic():
    random.seed(1234)
    first = [app.sample_request() for _ in range(50)]
    random.seed(1234)
    second = [app.sample_request() for _ in range(50)]
    assert first == second


def test_error_rate_within_budget_bounds():
    random.seed(99)
    samples = [app.sample_request() for _ in range(10_000)]
    fivexx = sum(1 for _, status, _ in samples if status >= 500) / len(samples)
    # nominal 5xx rate is 0.4%; assert within a wide deterministic band
    assert 0.001 <= fivexx <= 0.01


def test_latency_distribution_has_slow_tail():
    random.seed(7)
    latencies = [lat for _, _, lat in (app.sample_request() for _ in range(5_000))]
    p99 = sorted(latencies)[int(len(latencies) * 0.99) - 1]
    # slow outliers must exist so p99 is meaningful against SLO thresholds
    assert p99 > 0.3
    assert max(latencies) > 1.0


def test_metrics_emitted_to_default_registry():
    import prometheus_client

    app.REQUESTS.labels("test-svc", "GET", "200").inc()
    app.LATENCY.labels("test-svc", "GET").observe(0.123)

    value = prometheus_client.REGISTRY.get_sample_value(
        "http_requests_total", {"service": "test-svc", "method": "GET", "status": "200"}
    )
    assert value == 1.0
    count = prometheus_client.REGISTRY.get_sample_value(
        "http_request_duration_seconds_count", {"service": "test-svc", "method": "GET"}
    )
    assert count == 1.0
    bucket = prometheus_client.REGISTRY.get_sample_value(
        "http_request_duration_seconds_bucket",
        {"service": "test-svc", "method": "GET", "le": "0.5"},
    )
    assert bucket == 1.0


def test_batch_metrics_emitted_to_default_registry():
    import prometheus_client

    app.BATCH_LAST_SUCCESS.labels("test-svc").set(1_700_000_000)
    app.BATCH_RUNS.labels("test-svc", "success").inc()

    ts = prometheus_client.REGISTRY.get_sample_value(
        "batch_job_last_success_ts_seconds", {"service": "test-svc"}
    )
    assert ts == 1_700_000_000
    runs = prometheus_client.REGISTRY.get_sample_value(
        "batch_job_runs_total", {"service": "test-svc", "status": "success"}
    )
    assert runs == 1.0


def test_registered_metric_names_match_slo_conventions():
    import prometheus_client

    sample_names = {s.name for m in prometheus_client.REGISTRY.collect() for s in m.samples}
    assert "http_requests_total" in sample_names
    assert "http_request_duration_seconds_bucket" in sample_names
    assert "http_request_duration_seconds_count" in sample_names
    assert "batch_job_last_success_ts_seconds" in sample_names
    assert "batch_job_runs_total" in sample_names
