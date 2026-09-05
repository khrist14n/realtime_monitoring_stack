"""Prometheus configuration + SLO recording/alerting rule generation.

Implements the Google SRE Workbook "multi-window, multi-burn-rate" alerting
pattern: a fast-burn window (1h/5m) pages on critical budget consumption, a
slow-burn window (6h/30m) warns earlier on sustained lower burn.

Recording rules keep the `service` label (via `sum by (service)`) so dashboards
can aggregate across services without knowing service names at build time.
"""

from __future__ import annotations

from realtime_monitoring_stack.models import (
    DEFAULT_BURN_RATES,
    DEFAULT_WINDOWS,
    Service,
    Slo,
    StackConfig,
)

RATIO_WINDOWS = ("5m", "30m", "1h", "6h", "30d")
BURN_RATE_WINDOWS = ("1h", "5m", "6h", "30m")
RUNBOOK_URL = "https://sre.google/sre-book/service-level-objectives/"

DEFAULT_SCRAPE_INTERVAL = "15s"
DEFAULT_EVALUATION_INTERVAL = "30s"

INFRA_JOBS = [
    {
        "job_name": "node",
        "static_configs": [{"targets": ["node-exporter:9100"]}],
    },
    {
        "job_name": "cadvisor",
        "static_configs": [{"targets": ["cadvisor:8080"]}],
    },
    {
        "job_name": "prometheus",
        "static_configs": [{"targets": ["localhost:9090"]}],
    },
    {
        "job_name": "alertmanager",
        "static_configs": [{"targets": ["alertmanager:9093"]}],
    },
    {
        "job_name": "loki",
        "static_configs": [{"targets": ["loki:3100"]}],
    },
    {
        "job_name": "promtail",
        "static_configs": [{"targets": ["promtail:9080"]}],
    },
    {
        "job_name": "grafana",
        "static_configs": [{"targets": ["grafana:3000"]}],
    },
]


def _service_job(service: Service, scrape_interval: str) -> dict:
    return {
        "job_name": f"service/{service.name}",
        "scrape_interval": scrape_interval,
        "static_configs": [{"targets": service.targets, "labels": {"service": service.name}}],
    }


def build_prometheus_config(cfg: StackConfig) -> dict:
    """Return the full prometheus.yml as a dict (rendered to YAML by callers)."""
    scrape_configs = [_service_job(s, cfg.scrape_interval) for s in cfg.services]
    scrape_configs.extend(INFRA_JOBS)
    return {
        "global": {
            "scrape_interval": cfg.scrape_interval,
            "evaluation_interval": cfg.evaluation_interval,
            "scrape_timeout": "10s",
        },
        "rule_files": [
            "/etc/prometheus/rules/recording.yml",
            "/etc/prometheus/rules/alerts.yml",
        ],
        "alerting": {"alertmanagers": [{"static_configs": [{"targets": ["alertmanager:9093"]}]}]},
        "scrape_configs": scrape_configs,
    }


def _error_ratio_expr(service: Service, slo: Slo, window: str) -> str:
    """PromQL for the error fraction (0..1) over `window` for one service/SLO.

    availability: errors are requests matching error_status_regex.
    latency:      errors are requests slower than the SLO threshold.
    throughput:   errors when the request rate drops below throughput_per_sec;
                  good = min(actual / target, 1).
    freshness:    fraction of the window during which the last successful batch
                  run is older than max_freshness_seconds.
    """
    svc_label = f'service="{service.name}"'
    if slo.sli == "availability":
        req = service.metric("requests_metric")
        status = service.metric("status_label")
        regex = service.metric("error_status_regex")
        total = f"sum by (service) (rate({req}{{{svc_label}}}[{window}]))"
        errors = f'sum by (service) (rate({req}{{{svc_label},{status}=~"{regex}"}}[{window}]))'
        return f"{errors} / {total}"
    if slo.sli == "latency":
        hist = service.metric("latency_histogram_metric")
        threshold = slo.latency_threshold_seconds
        good = f'sum by (service) (rate({hist}{{{svc_label},le="{threshold}"}}[{window}]))'
        total = f'sum by (service) (rate({hist}{{{svc_label},le="+Inf"}}[{window}]))'
        return f"1 - ({good} / {total})"
    if slo.sli == "throughput":
        req = service.metric("requests_metric")
        total = f"sum by (service) (rate({req}{{{svc_label}}}[{window}]))"
        return f"1 - clamp_max({total} / {slo.throughput_per_sec:.6g}, 1)"
    # freshness SLI: fraction of window where the job was stale. `bool` keeps
    # the comparison emitting 0 (healthy) instead of dropping the series, so
    # the SLO/burn/error-budget rules stay populated while the batch is fresh.
    fresh = service.metric("freshness_metric")
    max_age = slo.max_freshness_seconds
    return f"avg_over_time((time() - {fresh}{{{svc_label}}} > bool {max_age:.6g})[{window}:1m])"


def _ratio_rule(service: Service, slo: Slo, window: str) -> dict:
    return {
        "record": f"slo:{service.rule_name}:{slo.sli}:errors:ratio_rate{window}",
        "expr": _error_ratio_expr(service, slo, window),
        "labels": {"service": service.name, "slo": slo.name, "team": service.team},
    }


def _burn_rate_rule(service: Service, slo: Slo, window: str) -> dict:
    return {
        "record": f"slo:{service.rule_name}:{slo.sli}:burn_rate{window}",
        "expr": (
            f"slo:{service.rule_name}:{slo.sli}:errors:ratio_rate{window} / {slo.error_budget:.6g}"
        ),
        "labels": {"service": service.name, "slo": slo.name, "team": service.team},
    }


def _error_budget_rule(service: Service, slo: Slo) -> dict:
    return {
        "record": f"slo:{service.rule_name}:{slo.sli}:error_budget_remaining",
        "expr": (
            f"1 - (slo:{service.rule_name}:{slo.sli}:errors:ratio_rate{slo.window} / "
            f"{slo.error_budget:.6g})"
        ),
        "labels": {"service": service.name, "slo": slo.name, "team": service.team},
    }


def _alert_rule(service: Service, slo: Slo, kind: str) -> dict:
    """kind: 'fast' (page) or 'slow' (warning)."""
    burn = DEFAULT_BURN_RATES["fast" if kind == "fast" else "slow"]
    windows = DEFAULT_WINDOWS
    long_w, short_w = (
        (windows["fast"], windows["fast_short"])
        if kind == "fast"
        else (windows["slow"], windows["slow_short"])
    )
    expr = (
        f"slo:{service.rule_name}:{slo.sli}:burn_rate{long_w} > {burn} and "
        f"slo:{service.rule_name}:{slo.sli}:burn_rate{short_w} > {burn}"
    )
    prefix = "SloFastBurnCritical" if kind == "fast" else "SloSlowBurnWarning"
    name = f"{prefix}-{service.name}-{slo.sli}"
    return {
        "alert": name,
        "expr": expr,
        "for": "1m",
        "labels": {
            "severity": "page" if kind == "fast" else "warning",
            "service": service.name,
            "slo": slo.name,
            "team": service.team,
        },
        "annotations": {
            "summary": "SLO error budget burning fast for {{ $labels.service }} ({{ $labels.slo }})"
            if kind == "fast"
            else "SLO error budget being consumed for {{ $labels.service }} ({{ $labels.slo }})",
            "description": (
                f"Burn rate for {slo.sli} SLO of {{{{ $labels.service }}}} exceeds "
                f"{burn}x over the {long_w} window while the {short_w} window is also "
                f"elevated. Budget consumed so far: "
                f"{{{{ $value | humanizePercentage }}}} of the {slo.window} budget."
            ),
            "runbook_url": RUNBOOK_URL,
        },
    }


def build_recording_rules(cfg: StackConfig) -> list[dict]:
    rules: list[dict] = []
    for service in cfg.services:
        for slo in service.slos:
            rules.extend(_ratio_rule(service, slo, w) for w in RATIO_WINDOWS)
            rules.extend(_burn_rate_rule(service, slo, w) for w in BURN_RATE_WINDOWS)
            rules.append(_error_budget_rule(service, slo))
    return rules


def build_alert_rules(cfg: StackConfig) -> list[dict]:
    rules: list[dict] = []
    for service in cfg.services:
        for slo in service.slos:
            rules.append(_alert_rule(service, slo, "fast"))
            rules.append(_alert_rule(service, slo, "slow"))
    return rules
