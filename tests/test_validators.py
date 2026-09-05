"""Validators: exercise every error/warning branch of validate_generated()."""

from __future__ import annotations

import json

import yaml

from realtime_monitoring_stack import render, validators
from realtime_monitoring_stack.models import load_config


def _render(tmp_path) -> tuple:
    """Render a fresh, valid config tree into tmp_path and return (root, files)."""
    cfg = load_config("services.yaml")
    out = tmp_path / "out"
    files = render.generate_all(cfg, out_dir=str(out))
    return out, files


def _errors(issues) -> list[str]:
    return [msg for level, msg in issues if level == "error"]


def test_valid_tree_only_warns_about_placeholder_key(tmp_path):
    out, _ = _render(tmp_path)
    issues = validators.validate_generated(str(out))
    assert _errors(issues) == []
    assert any(level == "warning" and "placeholder" in msg for level, msg in issues)


def test_missing_dir_is_an_error(tmp_path):
    issues = validators.validate_generated(str(tmp_path / "nope"))
    assert _errors(issues) and "does not exist" in _errors(issues)[0]


def test_invalid_yaml_in_prometheus_config(tmp_path):
    out, _ = _render(tmp_path)
    (out / "prometheus/prometheus.yml").write_text("{not: [valid\n", encoding="utf-8")
    issues = validators.validate_generated(str(out))
    assert any("invalid YAML" in msg for msg in _errors(issues))


def test_rule_file_referenced_but_missing(tmp_path):
    out, _ = _render(tmp_path)
    path = out / "prometheus/prometheus.yml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["rule_files"].append("/etc/prometheus/rules/missing.yml")
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    issues = validators.validate_generated(str(out))
    assert any("missing.yml" in msg for msg in _errors(issues))


def test_rules_file_without_groups_is_an_error(tmp_path):
    out, _ = _render(tmp_path)
    path = out / "prometheus/rules/recording.yml"
    path.write_text("groups: []\n", encoding="utf-8")
    issues = validators.validate_generated(str(out))
    assert any("no rule groups" in msg for msg in _errors(issues))


def test_rules_file_with_empty_rule_list_is_an_error(tmp_path):
    out, _ = _render(tmp_path)
    path = out / "prometheus/rules/alerts.yml"
    path.write_text("groups:\n- name: g\n  rules: []\n", encoding="utf-8")
    issues = validators.validate_generated(str(out))
    assert any("no rules found" in msg for msg in _errors(issues))


def test_alertmanager_missing_pagerduty_receiver(tmp_path):
    out, _ = _render(tmp_path)
    path = out / "alertmanager/alertmanager.yml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["receivers"] = [{"name": "other", "webhook_configs": [{"url": "http://x"}]}]
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    issues = validators.validate_generated(str(out))
    assert any("missing 'pagerduty' receiver" in msg for msg in _errors(issues))


def test_promtail_without_clients_is_an_error(tmp_path):
    out, _ = _render(tmp_path)
    path = out / "promtail/promtail-config.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["clients"] = []
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    issues = validators.validate_generated(str(out))
    assert any("no clients configured" in msg for msg in _errors(issues))


def test_invalid_yaml_in_loki_config(tmp_path):
    out, _ = _render(tmp_path)
    (out / "loki/loki-config.yaml").write_text(":\n  - ]", encoding="utf-8")
    issues = validators.validate_generated(str(out))
    assert any("invalid YAML" in msg for msg in _errors(issues))


def test_missing_dashboard_json_is_an_error(tmp_path):
    out, _ = _render(tmp_path)
    for dash in (out / "grafana/dashboards").glob("*.json"):
        dash.unlink()
    issues = validators.validate_generated(str(out))
    assert any("no dashboard JSON" in msg for msg in _errors(issues))


def test_dashboard_with_invalid_json_is_an_error(tmp_path):
    out, _ = _render(tmp_path)
    dash = next((out / "grafana/dashboards").glob("*.json"))
    dash.write_text("{not json", encoding="utf-8")
    issues = validators.validate_generated(str(out))
    assert any("invalid JSON" in msg for msg in _errors(issues))


def test_dashboard_missing_panels_or_uid(tmp_path):
    out, _ = _render(tmp_path)
    dash = out / "grafana/dashboards/slo-error-budget.json"
    dash.write_text(json.dumps({"uid": "slo-error-budget"}), encoding="utf-8")
    issues = validators.validate_generated(str(out))
    assert any("no panels" in msg for msg in _errors(issues))

    dash.write_text(json.dumps({"panels": [{"type": "row"}]}), encoding="utf-8")
    issues = validators.validate_generated(str(out))
    assert any("missing uid" in msg for msg in _errors(issues))
