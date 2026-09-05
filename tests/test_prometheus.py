from __future__ import annotations

import re

from realtime_monitoring_stack import prometheus
from realtime_monitoring_stack.models import Service, Slo, StackConfig


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
    # service names are sanitized into valid metric names (api-gateway -> api_gateway)
    assert names == {
        f"slo:{s.rule_name}:{slo.sli}:{kind}"
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
        r for r in rules if r["record"] == "slo:api_gateway:availability:error_budget_remaining"
    )
    assert "/ 0.001" in budget["expr"]
    assert "errors:ratio_rate30d" in budget["expr"]
    burn = next(r for r in rules if r["record"] == "slo:api_gateway:availability:burn_rate1h")
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
        r for r in rules if r["record"] == "slo:api_gateway:throughput:errors:ratio_rate5m"
    )
    assert "clamp_max(" in ratio["expr"]
    assert "/ 2, 1)" in ratio["expr"]  # throughput_per_sec=2
    # burn rate / budget reuse the generic machinery
    burn = next(r for r in rules if r["record"] == "slo:api_gateway:throughput:burn_rate1h")
    assert "/ 0.01" in burn["expr"]


def test_freshness_rules_measure_stale_time(cfg):
    rules = prometheus.build_recording_rules(cfg)
    ratio = next(r for r in rules if r["record"] == "slo:payments:freshness:errors:ratio_rate5m")
    assert "avg_over_time(" in ratio["expr"]
    assert "batch_job_last_success_ts_seconds" in ratio["expr"]
    assert "> bool 120" in ratio["expr"]  # max_freshness_seconds=120; bool keeps healthy=0
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


def test_all_recording_rule_names_are_valid_metric_names(cfg):
    pattern = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]*")
    for rule in prometheus.build_recording_rules(cfg):
        assert pattern.fullmatch(rule["record"]), rule["record"]


def test_alert_expressions_reference_sanitized_metric_names(cfg):
    rules = prometheus.build_alert_rules(cfg)
    assert all("slo:api-gateway:" not in rule["expr"] for rule in rules)
    api_rules = [rule for rule in rules if rule["labels"]["service"] == "api-gateway"]
    assert api_rules
    assert all("slo:api_gateway:" in rule["expr"] for rule in api_rules)


def test_weird_service_name_stays_consistent_across_rules():
    svc = Service(
        name="edge.api-v1",
        targets=["edge:8000"],
        slos=[Slo(name="availability", sli="availability", target=0.99)],
    )
    cfg = StackConfig(services=[svc])
    rules = prometheus.build_recording_rules(cfg)
    records = {r["record"] for r in rules}
    # all record names are sanitized (no raw 'edge.api-v1' anywhere)
    assert all(record.startswith("slo:edge_api_v1:") for record in records)
    ratio = next(
        r for r in rules if r["record"] == "slo:edge_api_v1:availability:errors:ratio_rate5m"
    )
    # the label keeps the original name while the metric name is sanitized
    assert ratio["labels"]["service"] == "edge.api-v1"
    # burn-rate and budget exprs reference the sanitized metric names
    burn = next(r for r in rules if r["record"] == "slo:edge_api_v1:availability:burn_rate1h")
    assert "slo:edge_api_v1:availability:errors:ratio_rate1h / 0.01" in burn["expr"]
    budget = next(
        r for r in rules if r["record"] == "slo:edge_api_v1:availability:error_budget_remaining"
    )
    assert "slo:edge_api_v1:availability:errors:ratio_rate30d / 0.01" in budget["expr"]
