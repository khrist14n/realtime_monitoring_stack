"""Grafana provisioning: datasources + file-based dashboard provider."""

from __future__ import annotations

from realtime_monitoring_stack.dashboards import build_services_overview, build_slo_dashboard
from realtime_monitoring_stack.models import StackConfig


def build_datasources() -> dict:
    return {
        "apiVersion": 1,
        "datasources": [
            {
                "name": "Prometheus",
                "uid": "prometheus",
                "type": "prometheus",
                "access": "proxy",
                "url": "http://prometheus:9090",
                "isDefault": True,
                "jsonData": {"timeInterval": "15s"},
            },
            {
                "name": "Loki",
                "uid": "loki",
                "type": "loki",
                "access": "proxy",
                "url": "http://loki:3100",
                "jsonData": {"maxLines": 1000},
            },
        ],
    }


def build_dashboard_provider() -> dict:
    return {
        "apiVersion": 1,
        "providers": [
            {
                "name": "default",
                "orgId": 1,
                "folder": "",
                "type": "file",
                "disableDeletion": False,
                "updateIntervalSeconds": 30,
                "allowUiUpdates": True,
                "options": {"path": "/var/lib/grafana/dashboards"},
            }
        ],
    }


def build_dashboards(cfg: StackConfig) -> dict[str, dict]:
    """Return {filename: dashboard_json} for every generated dashboard."""
    return {
        "services-overview.json": build_services_overview(cfg),
        "slo-error-budget.json": build_slo_dashboard(cfg),
    }
