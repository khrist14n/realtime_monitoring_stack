from __future__ import annotations

from realtime_monitoring_stack import prometheus


def test_scrape_jobs_for_every_service(cfg):
    conf = prometheus.build_prometheus_config(cfg)
    jobs = {j["job_name"] for j in conf["scrape_configs"]}
    for service in cfg.services:
        assert f"service/{service.name}" in jobs
        job = next(j for j in conf["scrape_configs"] if j["job_name"] == f"service/{service.name}")
        assert job["static_configs"][0]["labels"]["service"] == service.name
    assert "node" in jobs and "prometheus" in jobs and "loki" in jobs
    assert conf["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"] == [
        "alertmanager:9093"
    ]


def test_recording_rules_cover_windows_and_metrics(cfg):
    rules = prometheus.build_recording_rules(cfg)
    names = {r["record"] for r in rules}
    assert names == {
        f"slo:{s.name}:{slo.sli}:{kind}"
        for s in cfg.services
        for slo in s.slos
        for kind in (
            *(f"errors:ratio_rate{w}" for w in prometheus.RATIO_WINDOWS),
            *(f"burn_rate{w}" for w in prometheus.BURN_RATE_WINDOWS),
            "error_budget_remaining",
        )
    }
    # every rule carries the service label so dashboards can aggregate
    for rule in rules:
        assert rule["labels"]["service"] in {s.name for s in cfg.services}


def test_recording_rule_expression_uses_error_budget(cfg):
    rules = prometheus.build_recording_rules(cfg)
    budget = next(
        r for r in rules if r["record"] == "slo:api-gateway:availability:error_budget_remaining"
    )
    assert "/ 0.001" in budget["expr"]
    assert "errors:ratio_rate30d" in budget["expr"]
    burn = next(r for r in rules if r["record"] == "slo:api-gateway:availability:burn_rate1h")
    assert "errors:ratio_rate1h / 0.001" in burn["expr"]


def test_latency_rules_use_histogram_bucket(cfg):
    rules = prometheus.build_recording_rules(cfg)
    ratio = next(r for r in rules if r["record"] == "slo:checkout:latency:errors:ratio_rate5m")
    assert 'le="0.5"' in ratio["expr"]  # 500ms threshold in seconds
    assert 'le="+Inf"' in ratio["expr"]
    assert ratio["expr"].startswith("1 -")


def test_throughput_rules_clamp_at_target(cfg):
    rules = prometheus.build_recording_rules(cfg)
    ratio = next(
        r for r in rules if r["record"] == "slo:api-gateway:throughput:errors:ratio_rate5m"
    )
    assert "clamp_max(" in ratio["expr"]
    assert "/ 2, 1)" in ratio["expr"]  # throughput_per_sec=2
    # burn rate / budget reuse the generic machinery
    burn = next(r for r in rules if r["record"] == "slo:api-gateway:throughput:burn_rate1h")
    assert "/ 0.01" in burn["expr"]


def test_freshness_rules_measure_stale_time(cfg):
    rules = prometheus.build_recording_rules(cfg)
    ratio = next(r for r in rules if r["record"] == "slo:payments:freshness:errors:ratio_rate5m")
    assert "avg_over_time(" in ratio["expr"]
    assert "batch_job_last_success_ts_seconds" in ratio["expr"]
    assert "> 120" in ratio["expr"]  # max_freshness_seconds=120
    assert "[5m:1m]" in ratio["expr"]  # subquery resolution
    budget = next(
        r for r in rules if r["record"] == "slo:payments:freshness:error_budget_remaining"
    )
    assert "/ 0.01" in budget["expr"]


def test_alert_rules_multiwindow_multiburn(cfg):
    rules = prometheus.build_alert_rules(cfg)
    assert len(rules) == 2 * sum(len(s.slos) for s in cfg.services)
    fast = [r for r in rules if r["labels"]["severity"] == "page"]
    slow = [r for r in rules if r["labels"]["severity"] == "warning"]
    assert fast and slow
    page = fast[0]
    assert "burn_rate1h > 14.4 and" in page["expr"]
    assert "burn_rate5m > 14.4" in page["expr"]
    assert page["labels"]["service"] and page["labels"]["team"]
    warn = slow[0]
    assert "burn_rate6h > 6" in warn["expr"]
    assert "burn_rate30m > 6" in warn["expr"]
    for rule in rules:
        assert "runbook_url" in rule["annotations"]


def test_budget_rule_negative_budget_allowed(cfg):
    # the formula must allow negative values (budget exhausted)
    rules = prometheus.build_recording_rules(cfg)
    budget = next(r for r in rules if r["record"] == "slo:auth:availability:error_budget_remaining")
    assert budget["expr"].startswith("1 -")
