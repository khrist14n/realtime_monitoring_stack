from __future__ import annotations

import pytest

from realtime_monitoring_stack.models import ConfigError, load_config


def test_loads_default_catalog(cfg):
    assert len(cfg.services) == 4
    names = [s.name for s in cfg.services]
    assert "api-gateway" in names and "payments" in names
    for service in cfg.services:
        assert service.targets
        assert service.slos
        assert service.team


def test_slo_targets_parsed(cfg):
    slo = cfg.slo("api-gateway", "availability")
    assert slo.target == pytest.approx(0.999)
    assert slo.error_budget == pytest.approx(0.001)
    latency = cfg.slo("api-gateway", "latency")
    assert latency.latency_threshold_ms == 300
    assert latency.latency_threshold_seconds == pytest.approx(0.3)


def test_invalid_sli_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "services:\n"
        "  - name: api\n"
        "    targets: [api:8000]\n"
        "    slos:\n"
        "      - name: x\n"
        "        sli: unknown-sli\n"
        "        target: 0.99\n"
    )
    with pytest.raises(ConfigError, match="unknown-sli"):
        load_config(str(bad))


def test_invalid_target_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "services:\n"
        "  - name: api\n"
        "    targets: [api:8000]\n"
        "    slos:\n"
        "      - name: x\n"
        "        sli: availability\n"
        "        target: 1.5\n"
    )
    with pytest.raises(ConfigError, match="target"):
        load_config(str(bad))


def test_throughput_slo_requires_positive_throughput(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "services:\n"
        "  - name: api\n"
        "    targets: [api:8000]\n"
        "    slos:\n"
        "      - name: x\n"
        "        sli: throughput\n"
        "        target: 0.99\n"
    )
    with pytest.raises(ConfigError, match="throughput_per_sec"):
        load_config(str(bad))


def test_freshness_slo_requires_max_age(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "services:\n"
        "  - name: api\n"
        "    targets: [api:8000]\n"
        "    slos:\n"
        "      - name: x\n"
        "        sli: freshness\n"
        "        target: 0.99\n"
    )
    with pytest.raises(ConfigError, match="max_freshness_seconds"):
        load_config(str(bad))


def test_new_slo_types_parsed(cfg):
    throughput = cfg.slo("api-gateway", "throughput")
    assert throughput.sli == "throughput"
    assert throughput.throughput_per_sec == 2
    freshness = cfg.slo("payments", "freshness")
    assert freshness.sli == "freshness"
    assert freshness.max_freshness_seconds == 120


def test_latency_slo_requires_threshold(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "services:\n"
        "  - name: api\n"
        "    targets: [api:8000]\n"
        "    slos:\n"
        "      - name: x\n"
        "        sli: latency\n"
        "        target: 0.99\n"
    )
    with pytest.raises(ConfigError, match="latency_threshold_ms"):
        load_config(str(bad))


def test_duplicate_service_names_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "services:\n"
        "  - name: api\n"
        "    targets: [a:8000]\n"
        "    slos: [{name: x, sli: availability, target: 0.99}]\n"
        "  - name: api\n"
        "    targets: [b:8000]\n"
        "    slos: [{name: x, sli: availability, target: 0.99}]\n"
    )
    with pytest.raises(ConfigError, match="unique"):
        load_config(str(bad))


def test_per_service_metric_override(tmp_path):
    custom = tmp_path / "custom.yaml"
    custom.write_text(
        "metrics:\n"
        "  requests_metric: grpc_server_handled_total\n"
        "services:\n"
        "  - name: api\n"
        "    targets: [api:8000]\n"
        "    slos: [{name: x, sli: availability, target: 0.99}]\n"
    )
    cfg = load_config(str(custom))
    assert cfg.services[0].metric("requests_metric") == "grpc_server_handled_total"
    # defaults preserved for other keys
    assert cfg.services[0].metric("status_label") == "status"
