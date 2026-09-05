"""Validate the generated config tree before (and after) deployment."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from realtime_monitoring_stack import alertmanager

ValidationIssue = tuple[str, str]  # (level, message)  level in {"error", "warning"}


def _load_yaml(path: Path) -> tuple[object | None, ValidationIssue | None]:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")), None
    except yaml.YAMLError as exc:
        return None, ("error", f"{path}: invalid YAML: {exc}")


def validate_generated(out_dir: str = "generated") -> list[ValidationIssue]:
    root = Path(out_dir)
    issues: list[ValidationIssue] = []

    if not root.is_dir():
        issues.append(("error", f"{out_dir}/ does not exist — run `monitoring-stack config` first"))
        return issues

    # --- Prometheus ---
    prom_file = root / "prometheus/prometheus.yml"
    prom_cfg, issue = _load_yaml(prom_file)
    if issue:
        issues.append(issue)
    else:
        for rule_file in prom_cfg["rule_files"]:
            rel = Path(rule_file.lstrip("/"))
            candidate = (
                root / "prometheus" / "rules" / rel.name
                if rel.parent.name == "rules"
                else root / rel
            )
            if not candidate.exists():
                issues.append(
                    ("error", f"rule file referenced by prometheus.yml missing: {rule_file}")
                )

    for rules_file in ("recording.yml", "alerts.yml"):
        path = root / "prometheus/rules" / rules_file
        data, issue = _load_yaml(path)
        if issue:
            issues.append(issue)
        elif not data or not data.get("groups"):
            issues.append(("error", f"{path}: no rule groups found"))
        else:
            rules = data["groups"][0]["rules"]
            if not rules:
                issues.append(("error", f"{path}: no rules found"))

    # --- Alertmanager ---
    am_file = root / "alertmanager/alertmanager.yml"
    am_cfg, issue = _load_yaml(am_file)
    if issue:
        issues.append(issue)
    else:
        receivers = {r["name"] for r in am_cfg.get("receivers", [])}
        if "pagerduty" not in receivers:
            issues.append(("error", "alertmanager.yml: missing 'pagerduty' receiver"))
        if am_file.read_text(encoding="utf-8").find(alertmanager.PLACEHOLDER_KEY) != -1:
            issues.append(
                (
                    "warning",
                    (
                        "alertmanager.yml: PagerDuty routing key is a placeholder — "
                        "set PAGERDUTY_ROUTING_KEY and regenerate"
                    ),
                )
            )

    # --- Loki / Promtail ---
    _, issue = _load_yaml(root / "loki/loki-config.yaml")
    if issue:
        issues.append(issue)
    promtail_cfg, issue = _load_yaml(root / "promtail/promtail-config.yaml")
    if issue:
        issues.append(issue)
    else:
        if not promtail_cfg.get("clients"):
            issues.append(("error", "promtail-config.yaml: no clients configured"))

    # --- Grafana ---
    for prov in ("datasources.yml", "dashboards.yml"):
        data, issue = _load_yaml(
            root
            / "grafana/provisioning"
            / ("datasources" if "datasource" in prov else "dashboards")
            / prov
        )
        if issue:
            issues.append(issue)
    dashboard_dir = root / "grafana/dashboards"
    dashboards = sorted(dashboard_dir.glob("*.json"))
    if not dashboards:
        issues.append(("error", f"{dashboard_dir}: no dashboard JSON files found"))
    for dash in dashboards:
        try:
            data = json.loads(dash.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            issues.append(("error", f"{dash}: invalid JSON: {exc}"))
            continue
        if not data.get("panels"):
            issues.append(("error", f"{dash}: no panels"))
        if not data.get("uid"):
            issues.append(("error", f"{dash}: missing uid"))

    return issues
