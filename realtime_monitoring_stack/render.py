"""Render every config file for the stack into the generated/ directory."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from realtime_monitoring_stack import alertmanager, grafana, loki, prometheus
from realtime_monitoring_stack.models import StackConfig

OUTPUT_ROOT = "generated"


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def generate_all(cfg: StackConfig, out_dir: str = OUTPUT_ROOT) -> list[str]:
    """Generate the full config tree. Returns the list of written files."""
    root = Path(out_dir)
    written: list[str] = []

    # Prometheus
    _write_yaml(root / "prometheus/prometheus.yml", prometheus.build_prometheus_config(cfg))
    written.append("prometheus/prometheus.yml")
    _write_yaml(
        root / "prometheus/rules/recording.yml",
        {
            "groups": [
                {"name": "slo-recording-rules", "rules": prometheus.build_recording_rules(cfg)}
            ]
        },
    )
    written.append("prometheus/rules/recording.yml")
    _write_yaml(
        root / "prometheus/rules/alerts.yml",
        {"groups": [{"name": "slo-alerting-rules", "rules": prometheus.build_alert_rules(cfg)}]},
    )
    written.append("prometheus/rules/alerts.yml")

    # Alertmanager
    _write_yaml(root / "alertmanager/alertmanager.yml", alertmanager.build_alertmanager_config())
    written.append("alertmanager/alertmanager.yml")

    # Loki + Promtail
    (root / "loki").mkdir(parents=True, exist_ok=True)
    (root / "loki/loki-config.yaml").write_text(loki.LOKI_CONFIG, encoding="utf-8")
    written.append("loki/loki-config.yaml")
    _write_yaml(root / "promtail/promtail-config.yaml", loki.build_promtail_config())
    written.append("promtail/promtail-config.yaml")

    # Grafana provisioning
    _write_yaml(
        root / "grafana/provisioning/datasources/datasources.yml", grafana.build_datasources()
    )
    written.append("grafana/provisioning/datasources/datasources.yml")
    _write_yaml(
        root / "grafana/provisioning/dashboards/dashboards.yml", grafana.build_dashboard_provider()
    )
    written.append("grafana/provisioning/dashboards/dashboards.yml")
    for filename, dashboard in grafana.build_dashboards(cfg).items():
        _write_json(root / f"grafana/dashboards/{filename}", dashboard)
        written.append(f"grafana/dashboards/{filename}")

    return written


def load_services(services_path: str) -> StackConfig:
    from realtime_monitoring_stack.models import load_config

    return load_config(services_path)


def output_abs(out_dir: str) -> str:
    return str(Path(out_dir).resolve())


def env_is_configured() -> tuple[bool, str]:
    """Return (ok, message) describing PagerDuty key presence."""
    if alertmanager.has_pagerduty_key():
        return True, "PAGERDUTY_ROUTING_KEY is set — PagerDuty alerts are live."
    return False, (
        "PAGERDUTY_ROUTING_KEY is not set — the Alertmanager PagerDuty receiver "
        "was generated with a placeholder key. Set it in .env to receive pages."
    )
