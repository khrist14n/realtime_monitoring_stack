"""Grafana dashboard JSON builders.

Two dashboards are generated from the service catalog:
  * Services Overview      — RED metrics (rate, errors, duration) per service,
                             plus a Loki log-volume panel for log correlation.
  * SLO & Error Budget     — error budget remaining, burn rates, and error
                             ratios per service/SLO, wired to the recording
                             rules emitted by prometheus.py.

Dashboards reference the datasources by their provisioned uids
("prometheus" / "loki") and a multi-select `$service` template variable.
"""

from __future__ import annotations

from realtime_monitoring_stack.models import StackConfig

SCHEMA_VERSION = 39

PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}


# --------------------------------------------------------------------------- #
# Panel builders
# --------------------------------------------------------------------------- #


def _base(title: str, grid: dict, panel_type: str, datasource: dict) -> dict:
    return {
        "id": 0,  # assigned at assembly time
        "type": panel_type,
        "title": title,
        "datasource": datasource,
        "gridPos": grid,
        "targets": [],
        "fieldConfig": {"defaults": {}, "overrides": []},
        "options": {},
    }


def _timeseries(
    title: str,
    exprs: list[tuple[str, str]],
    grid: dict,
    unit: str = "short",
    datasource: dict = PROM,
    threshold_steps: list[tuple[float | None, str]] | None = None,
) -> dict:
    panel = _base(title, grid, "timeseries", datasource)
    panel["targets"] = [
        {"expr": e, "legendFormat": lf, "refId": chr(65 + i)} for i, (e, lf) in enumerate(exprs)
    ]
    panel["fieldConfig"]["defaults"] = {
        "unit": unit,
        "custom": {
            "drawStyle": "line",
            "fillOpacity": 12,
            "lineWidth": 1,
            "showPoints": "never",
            "spanNulls": True,
            "lineInterpolation": "smooth",
        },
    }
    if threshold_steps:
        panel["fieldConfig"]["defaults"]["thresholds"] = {
            "mode": "absolute",
            "steps": [{"color": color, "value": value} for value, color in threshold_steps],
        }
    panel["options"] = {
        "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
        "tooltip": {"mode": "multi", "sort": "desc"},
    }
    return panel


def _stat(
    title: str,
    exprs: list[tuple[str, str]],
    grid: dict,
    unit: str,
    threshold_steps: list[tuple[float | None, str]],
) -> dict:
    panel = _base(title, grid, "stat", PROM)
    panel["targets"] = [
        {"expr": e, "legendFormat": lf, "refId": chr(65 + i)} for i, (e, lf) in enumerate(exprs)
    ]
    panel["fieldConfig"]["defaults"] = {
        "unit": unit,
        "thresholds": {
            "mode": "absolute",
            "steps": [{"color": color, "value": value} for value, color in threshold_steps],
        },
    }
    panel["options"] = {
        "colorMode": "background",
        "graphMode": "area",
        "justifyMode": "auto",
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        "textMode": "value_and_name",
    }
    return panel


def _row(title: str, grid: dict) -> dict:
    panel = _base(title, grid, "row", {"type": "datasource", "uid": "grafana"})
    panel["collapsed"] = False
    panel.pop("targets")
    return panel


def _service_var() -> dict:
    return {
        "current": {"selected": True, "text": "All", "value": "$__all"},
        "datasource": PROM,
        "definition": "label_values(http_requests_total, service)",
        "hide": 0,
        "includeAll": True,
        "allValue": ".*",
        "label": "Service",
        "multi": True,
        "name": "service",
        "options": [],
        "query": {
            "query": "label_values(http_requests_total, service)",
            "refId": "StandardVariableQuery",
        },
        "refresh": 2,
        "regex": "",
        "skipUrlSync": False,
        "sort": 1,
        "type": "query",
    }


def _dashboard(title: str, uid: str, panels: list[dict], tags: list[str]) -> dict:
    return {
        "annotations": {
            "list": [
                {
                    "builtIn": 1,
                    "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                    "enable": True,
                    "hide": True,
                    "iconColor": "rgba(0, 211, 255, 1)",
                    "name": "Annotations & Alerts",
                    "type": "dashboard",
                }
            ]
        },
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "id": None,
        "links": [],
        "panels": panels,
        "refresh": "30s",
        "schemaVersion": SCHEMA_VERSION,
        "tags": tags,
        "templating": {"list": [_service_var()]},
        "time": {"from": "now-6h", "to": "now"},
        "timepicker": {},
        "timezone": "browser",
        "title": title,
        "uid": uid,
        "version": 1,
        "weekStart": "",
    }


def _assign_ids(panels: list[dict]) -> None:
    for i, panel in enumerate(panels, start=1):
        panel["id"] = i


# --------------------------------------------------------------------------- #
# Dashboard 1: Services Overview
# --------------------------------------------------------------------------- #


def build_services_overview(cfg: StackConfig) -> dict:
    m = cfg.services[0].metrics  # global metric conventions
    req = m["requests_metric"]
    status = m["status_label"]
    regex = m["error_status_regex"]
    hist = m["latency_histogram_metric"]
    svc = 'service=~"$service"'

    rate5 = f"sum(rate({req}{{{svc}}}[5m])) by (service)"
    err_rate5 = (
        f'100 * sum(rate({req}{{{svc},{status}=~"{regex}"}}[5m])) by (service) '
        f"/ sum(rate({req}{{{svc}}}[5m])) by (service)"
    )
    p99 = f"histogram_quantile(0.99, sum(rate({hist}{{{svc}}}[5m])) by (le, service))"
    avail30d = (
        f'100 * (1 - sum(rate({req}{{{svc},{status}=~"{regex}"}}[30d])) by (service) '
        f"/ sum(rate({req}{{{svc}}}[30d])) by (service))"
    )

    panels: list[dict] = []
    panels.append(_row("Services", {"h": 1, "w": 24, "x": 0, "y": 0}))

    stats = [
        ("Requests / sec", [(rate5, "{{service}}")], "reqps", [(None, "green")]),
        (
            "Error rate (5m)",
            [(err_rate5, "{{service}}")],
            "percent",
            [(None, "green"), (1, "yellow"), (5, "red")],
        ),
        (
            "p99 latency",
            [(p99, "{{service}}")],
            "s",
            [(None, "green"), (0.3, "yellow"), (1.0, "red")],
        ),
        (
            "Availability (30d)",
            [(avail30d, "{{service}}")],
            "percent",
            [(None, "red"), (99.0, "yellow"), (99.95, "green")],
        ),
    ]
    for i, (title, exprs, unit, steps) in enumerate(stats):
        panels.append(_stat(title, exprs, {"h": 4, "w": 3, "x": i * 3, "y": 1}, unit, steps))

    panels.append(
        _timeseries(
            "Requests per second",
            [(rate5, "{{service}}")],
            {"h": 8, "w": 12, "x": 0, "y": 5},
            "reqps",
        )
    )
    panels.append(
        _timeseries(
            "Error rate (%)",
            [(err_rate5, "{{service}}")],
            {"h": 8, "w": 12, "x": 12, "y": 5},
            "percent",
            threshold_steps=[(None, "green"), (1, "yellow"), (5, "red")],
        )
    )
    latency_exprs = []
    for q, label in ((0.50, "p50"), (0.95, "p95"), (0.99, "p99")):
        latency_exprs.append(
            (
                f"histogram_quantile({q}, sum(rate({hist}{{{svc}}}[5m])) by (le, service))",
                f"{{{{service}}}} {label}",
            )
        )
    panels.append(
        _timeseries(
            "Latency (p50 / p95 / p99)",
            latency_exprs,
            {"h": 8, "w": 12, "x": 0, "y": 13},
            "s",
        )
    )
    panels.append(
        _timeseries(
            "Log volume (Loki)",
            [('sum by (service) (count_over_time({service=~"$service"}[5m]))', "{{service}}")],
            {"h": 8, "w": 12, "x": 12, "y": 13},
            "short",
            datasource=LOKI,
        )
    )

    _assign_ids(panels)
    return _dashboard(
        "Services Overview", "services-overview", panels, ["monitoring", "red", "slo"]
    )


# --------------------------------------------------------------------------- #
# Dashboard 2: SLO & Error Budget
# --------------------------------------------------------------------------- #


def build_slo_dashboard(cfg: StackConfig) -> dict:
    panels: list[dict] = []
    panels.append(_row("Error Budget Remaining", {"h": 1, "w": 24, "x": 0, "y": 0}))

    # One stat panel per (service, SLO) showing remaining budget as a %.
    budget_steps = [(None, "red"), (0, "yellow"), (50, "green")]
    stats = []
    for service in cfg.services:
        for slo in service.slos:
            metric = f"slo:{service.name}:{slo.sli}:error_budget_remaining"
            stats.append(
                (
                    f"{service.name} · {slo.sli}",
                    [(f"{metric} * 100", "{{service}}")],
                )
            )
    for i, (title, exprs) in enumerate(stats):
        x = (i % 3) * 8
        y = 1 + (i // 3) * 4
        panels.append(
            _stat(title, exprs, {"h": 4, "w": 8, "x": x, "y": y}, "percent", budget_steps)
        )
    budget_y = 1 + ((len(stats) - 1) // 3 + 1) * 4

    budget_expr = '{__name__=~"slo:.*:.*:error_budget_remaining", service=~"$service"} * 100'
    burn_expr = '{__name__=~"slo:.*:.*:burn_rate1h", service=~"$service"}'
    ratio_expr = '{__name__=~"slo:.*:.*:errors:ratio_rate5m", service=~"$service"}'

    panels.append(
        _timeseries(
            "Error budget remaining (%)",
            [(budget_expr, "{{service}} {{slo}}")],
            {"h": 8, "w": 12, "x": 0, "y": budget_y},
            "percent",
        )
    )
    panels.append(
        _timeseries(
            "Burn rate (1h) — fast burn > 14.4x, slow burn > 6x",
            [(burn_expr, "{{service}} {{slo}}")],
            {"h": 8, "w": 12, "x": 12, "y": budget_y},
            "short",
            threshold_steps=[(None, "green"), (1, "yellow"), (6, "orange"), (14.4, "red")],
        )
    )
    panels.append(
        _timeseries(
            "Error ratio (5m)",
            [(ratio_expr, "{{service}} {{slo}}")],
            {"h": 8, "w": 12, "x": 0, "y": budget_y + 8},
            "percentunit",
        )
    )
    panels.append(
        _timeseries(
            "Burn rate (6h) — slow-burn warning window",
            [('{__name__=~"slo:.*:.*:burn_rate6h", service=~"$service"}', "{{service}} {{slo}}")],
            {"h": 8, "w": 12, "x": 12, "y": budget_y + 8},
            "short",
            threshold_steps=[(None, "green"), (1, "yellow"), (6, "orange"), (14.4, "red")],
        )
    )

    _assign_ids(panels)
    return _dashboard(
        "SLO & Error Budget", "slo-error-budget", panels, ["monitoring", "slo", "error-budget"]
    )
