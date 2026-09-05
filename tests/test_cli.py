from __future__ import annotations

import subprocess
import sys

from realtime_monitoring_stack import deploy
from realtime_monitoring_stack.cli import main


def test_config_command_writes_files(tmp_path):
    out = tmp_path / "out"
    rc = main(["config", "--services", "services.yaml", "--out", str(out)])
    assert rc == 0
    assert (out / "prometheus/prometheus.yml").is_file()
    assert (out / "grafana/dashboards/services-overview.json").is_file()


def test_config_command_accepts_options_before_subcommand(tmp_path):
    out = tmp_path / "out"
    rc = main(["--services", "services.yaml", "--out", str(out), "config"])
    assert rc == 0
    assert (out / "prometheus/prometheus.yml").is_file()


def test_validate_command_passes_on_generated_tree(tmp_path):
    out = tmp_path / "out"
    assert main(["config", "--services", "services.yaml", "--out", str(out)]) == 0
    assert main(["validate", "--out", str(out)]) == 0


def test_validate_command_fails_on_missing_dir(tmp_path):
    rc = main(["validate", "--out", str(tmp_path / "nope")])
    assert rc == 1


def test_config_command_fails_on_bad_services_file(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("services: []\n")
    rc = main(["config", "--services", str(bad), "--out", str(tmp_path / "out")])
    assert rc == 1


def test_unknown_command_rejected():
    import pytest

    with pytest.raises(SystemExit):
        main(["definitely-not-a-command"])


def _record(monkeypatch, name: str, result=None):
    calls: list = []

    def fake(*args, **kw):
        calls.append((name, args, kw))
        return result

    monkeypatch.setattr(deploy, name, fake)
    return calls


def test_deploy_command_generates_then_composes(monkeypatch, tmp_path):
    calls = _record(monkeypatch, "compose_up")
    _record(monkeypatch, "wait_and_report")
    out = tmp_path / "out"
    rc = main(["deploy", "--services", "services.yaml", "--out", str(out)])
    assert rc == 0
    assert (out / "prometheus/prometheus.yml").is_file()
    assert calls  # compose_up was invoked


def test_deploy_command_aborts_on_bad_catalog(monkeypatch, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("services: []\n")
    calls = _record(monkeypatch, "compose_up")
    rc = main(["deploy", "--services", str(bad), "--out", str(tmp_path / "out")])
    assert rc == 1
    assert calls == []  # never reached compose


def test_down_command_delegates(monkeypatch):
    calls = _record(monkeypatch, "compose_down")
    assert main(["down"]) == 0
    assert calls == [("compose_down", (), {})]


def test_status_command_ps_then_health(monkeypatch):
    calls = _record(monkeypatch, "compose_ps")
    _record(monkeypatch, "wait_and_report")
    assert main(["status"]) == 0
    assert calls


def test_check_command_runs_health_checks(monkeypatch):
    calls = _record(monkeypatch, "wait_and_report")
    assert main(["check"]) == 0
    assert calls == [("wait_and_report", (), {})]


def test_logs_command_tails_all_or_one_service(monkeypatch):
    calls: list = []
    monkeypatch.setattr(deploy, "compose_logs", lambda service: calls.append(service))
    assert main(["logs"]) == 0
    assert main(["logs", "prometheus"]) == 0
    assert calls == [None, "prometheus"]


def test_validate_reports_errors_and_exit_code(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        "realtime_monitoring_stack.cli.validators.validate_generated",
        lambda out_dir: [("error", "boom"), ("warning", "careful")],
    )
    assert main(["validate"]) == 1
    out = capsys.readouterr().out
    assert "error:   boom" in out and "warning: careful" in out and "1 error(s)" in out


def test_cli_runs_as_module_subprocess():
    result = subprocess.run(
        [sys.executable, "-m", "realtime_monitoring_stack.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0
    assert "usage: monitoring-stack" in result.stdout
