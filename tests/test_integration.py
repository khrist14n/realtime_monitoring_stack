"""Smoke tests against a *deployed* stack.

Skipped by default. To run them, deploy first and opt in:

    monitoring-stack deploy
    MONITORING_STACK_INTEGRATION=1 pytest -m integration

They verify the same things the config generators promise, but against the
live Prometheus/Grafana/Loki instances:
  * dashboards are provisioned and contain panels
  * demo-app scrape targets are UP
  * SLO recording rules are actually producing series
"""

from __future__ import annotations

import os

import pytest
import requests

pytestmark = pytest.mark.integration

GRAFANA = os.environ.get("GRAFANA_URL", "http://localhost:3000").rstrip("/")
PROMETHEUS = os.environ.get("PROMETHEUS_URL", "http://localhost:9090").rstrip("/")
LOKI = os.environ.get("LOKI_URL", "http://localhost:3100").rstrip("/")
ADMIN_USER = os.environ.get("GF_SECURITY_ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("GF_SECURITY_ADMIN_PASSWORD", "admin")

DASHBOARD_UIDS = ["services-overview", "slo-error-budget"]


def _require_deployed_stack() -> None:
    if not os.environ.get("MONITORING_STACK_INTEGRATION"):
        pytest.skip("set MONITORING_STACK_INTEGRATION=1 to run integration tests")


def test_grafana_health():
    _require_deployed_stack()
    resp = requests.get(f"{GRAFANA}/api/health", timeout=10)
    assert resp.status_code == 200
    assert resp.json()["database"] == "ok"


def test_dashboards_provisioned_with_panels():
    _require_deployed_stack()
    auth = (ADMIN_USER, ADMIN_PASS)
    for uid in DASHBOARD_UIDS:
        resp = requests.get(f"{GRAFANA}/api/dashboards/uid/{uid}", auth=auth, timeout=10)
        assert resp.status_code == 200, f"dashboard {uid} not provisioned: {resp.text}"
        assert resp.json()["dashboard"]["panels"], f"dashboard {uid} has no panels"


def test_prometheus_targets_up():
    _require_deployed_stack()
    resp = requests.get(f"{PROMETHEUS}/api/v1/targets", timeout=10)
    assert resp.status_code == 200
    targets = resp.json()["data"]["activeTargets"]
    demo_jobs = {
        t["labels"].get("job") for t in targets if t["labels"].get("job", "").startswith("service/")
    }
    assert demo_jobs, "no service/* scrape jobs found"
    for target in targets:
        if target["labels"].get("job") in demo_jobs:
            assert target["health"] == "up", f"target down: {target}"


def test_slo_recording_rules_produce_series():
    _require_deployed_stack()
    for query in (
        "slo:api-gateway:availability:errors:ratio_rate5m",
        "slo:api-gateway:throughput:errors:ratio_rate5m",
        "slo:payments:freshness:errors:ratio_rate5m",
    ):
        resp = requests.get(
            f"{PROMETHEUS}/api/v1/query",
            params={"query": query},
            timeout=10,
        )
        assert resp.status_code == 200
        result = resp.json()["data"]["result"]
        assert result, f"recording rule {query} returned no series — is the stack warm?"
        assert result[0]["value"][1] != "NaN"


def test_loki_ready():
    _require_deployed_stack()
    resp = requests.get(f"{LOKI}/ready", timeout=10)
    assert resp.status_code == 200
