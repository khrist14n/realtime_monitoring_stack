from __future__ import annotations

import json

import yaml

from realtime_monitoring_stack import validators


def test_render_writes_expected_tree(rendered):
    out, files = rendered
    assert len(files) == len(set(files))
    for rel in files:
        assert (out / rel).is_file(), f"missing {rel}"
    assert set(files) == {
        "prometheus/prometheus.yml",
        "prometheus/rules/recording.yml",
        "prometheus/rules/alerts.yml",
        "alertmanager/alertmanager.yml",
        "loki/loki-config.yaml",
        "promtail/promtail-config.yaml",
        "grafana/provisioning/datasources/datasources.yml",
        "grafana/provisioning/dashboards/dashboards.yml",
        "grafana/dashboards/services-overview.json",
        "grafana/dashboards/slo-error-budget.json",
    }


def test_rendered_files_are_valid_yaml_json(rendered):
    out, _ = rendered
    for rel in (
        "prometheus/prometheus.yml",
        "alertmanager/alertmanager.yml",
        "promtail/promtail-config.yaml",
        "loki/loki-config.yaml",
    ):
        assert yaml.safe_load((out / rel).read_text()) is not None, rel
    for dash in out.glob("grafana/dashboards/*.json"):
        assert json.loads(dash.read_text())["panels"], dash


def test_prometheus_rule_files_match_disk(rendered):
    out, _ = rendered
    prom = yaml.safe_load((out / "prometheus/prometheus.yml").read_text())
    rule_files = [f.split("/")[-1] for f in prom["rule_files"]]
    on_disk = sorted(p.name for p in (out / "prometheus/rules").glob("*.yml"))
    assert sorted(rule_files) == on_disk


def test_recording_rules_syntactically_consistent(rendered):
    out, _ = rendered
    recording = yaml.safe_load((out / "prometheus/rules/recording.yml").read_text())
    rules = recording["groups"][0]["rules"]
    # burn-rate rules reference ratio rules that exist
    records = {r["record"] for r in rules}
    for rule in rules:
        for token in rule["expr"].split():
            if token.startswith("slo:"):
                assert token in records, f"{rule['record']} references unknown {token}"


def test_validate_passes_on_generated_tree(rendered):
    out, _ = rendered
    issues = validators.validate_generated(str(out))
    errors = [i for i in issues if i[0] == "error"]
    assert errors == []


def test_validate_flags_missing_dir(tmp_path):
    issues = validators.validate_generated(str(tmp_path / "nope"))
    assert issues and issues[0][0] == "error"
