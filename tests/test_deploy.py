from __future__ import annotations

import subprocess

import pytest

from realtime_monitoring_stack import deploy


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise deploy.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


def test_compose_up_down_ps_delegate_to_docker(monkeypatch):
    monkeypatch.setenv(deploy.RUNTIME_ENV, "docker")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        deploy.subprocess,
        "run",
        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""),
    )
    deploy.compose_up()
    deploy.compose_down()
    deploy.compose_ps()
    for call in calls:
        assert call[:3] == ["docker", "compose", "-f"]
        assert call[3] == deploy.COMPOSE_FILE
    assert calls[0][4] == "up"
    assert calls[1][4] == "down"
    assert calls[2][4] == "ps"


def test_compose_up_delegates_to_podman_when_configured(monkeypatch):
    monkeypatch.setenv(deploy.RUNTIME_ENV, "podman")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        deploy.subprocess,
        "run",
        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""),
    )
    deploy.compose_up()
    assert calls[0][:3] == ["podman", "compose", "-f"]
    assert calls[0][3] == deploy.COMPOSE_FILE


def test_runtime_autodetects_podman_without_docker(monkeypatch):
    def _which(name: str) -> str | None:
        return "/usr/bin/podman" if name == "podman" else None

    monkeypatch.delenv(deploy.RUNTIME_ENV, raising=False)
    monkeypatch.setattr(deploy.shutil, "which", _which)
    assert deploy.container_runtime() == "podman"
    assert deploy._compose_command("ps")[:3] == ["podman", "compose", "-f"]


def test_runtime_requires_valid_value(monkeypatch):
    monkeypatch.setenv(deploy.RUNTIME_ENV, "nerdctl")
    with pytest.raises(SystemExit, match=deploy.RUNTIME_ENV):
        deploy.container_runtime()


def test_runtime_errors_when_no_engine_available(monkeypatch):
    monkeypatch.delenv(deploy.RUNTIME_ENV, raising=False)
    monkeypatch.setattr(deploy.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="no container runtime"):
        deploy.container_runtime()


def test_compose_failure_raises_system_exit(monkeypatch):
    monkeypatch.setenv(deploy.RUNTIME_ENV, "docker")

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "boom")

    monkeypatch.setattr(deploy.subprocess, "run", fake_run)
    with pytest.raises(SystemExit, match="failed"):
        deploy.compose_up()


def test_compose_logs_tails_service(monkeypatch):
    monkeypatch.setenv(deploy.RUNTIME_ENV, "docker")
    monkeypatch.setattr(
        deploy.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""),
    )
    with pytest.raises(SystemExit, match="0"):
        deploy.compose_logs("prometheus")


def test_health_check_reports_all_up(monkeypatch, capsys):
    monkeypatch.setattr(deploy, "HEALTH_RETRIES", 1)
    monkeypatch.setattr(deploy, "HEALTH_INTERVAL", 0)
    monkeypatch.setattr(deploy, "_url", lambda name: f"http://{name}")
    monkeypatch.setattr(deploy.requests, "get", lambda url, timeout=5: _FakeResponse(200))
    results = deploy.health_check()
    assert results == {"prometheus": True, "grafana": True, "loki": True}
    out = capsys.readouterr().out
    assert "UP" in out and "DOWN" not in out


def test_health_check_reports_down_on_errors(monkeypatch):
    monkeypatch.setattr(deploy, "HEALTH_RETRIES", 1)
    monkeypatch.setattr(deploy, "HEALTH_INTERVAL", 0)
    monkeypatch.setattr(deploy, "_url", lambda name: "http://nonexistent")

    def boom(url, timeout=5):
        raise deploy.requests.RequestException("connection refused")

    monkeypatch.setattr(deploy.requests, "get", boom)
    results = deploy.health_check()
    assert results == {"prometheus": False, "grafana": False, "loki": False}


def test_targets_summary_reports_up_counts(monkeypatch, capsys):
    targets = {
        "data": {
            "activeTargets": [
                {"labels": {"job": "service/api-gateway"}, "health": "up"},
                {"labels": {"job": "service/api-gateway"}, "health": "up"},
                {"labels": {"job": "node"}, "health": "down"},
            ]
        }
    }
    monkeypatch.setattr(deploy, "_url", lambda name: "http://prometheus")
    monkeypatch.setattr(deploy.requests, "get", lambda url, timeout=10: _FakeResponse(200, targets))
    deploy.targets_summary()
    out = capsys.readouterr().out
    assert "service/api-gateway" in out and "2/2 targets up" in out
    assert "node" in out and "0/1 targets up" in out


def test_targets_summary_tolerates_unreachable_prometheus(monkeypatch, capsys):
    def boom(url, timeout=10):
        raise deploy.requests.RequestException("no route")

    monkeypatch.setattr(deploy.requests, "get", boom)
    deploy.targets_summary()
    assert "could not query" in capsys.readouterr().out


def test_wait_and_report_succeeds_when_all_healthy(monkeypatch, capsys):
    monkeypatch.setattr(
        deploy, "health_check", lambda: {"prometheus": True, "grafana": True, "loki": True}
    )
    monkeypatch.setattr(deploy, "targets_summary", lambda: None)
    deploy.wait_and_report()
    out = capsys.readouterr().out
    assert "Health checks:" in out and "Prometheus scrape targets:" in out


def test_wait_and_report_fails_when_service_down(monkeypatch, capsys):
    monkeypatch.setattr(
        deploy, "health_check", lambda: {"prometheus": False, "grafana": True, "loki": True}
    )
    monkeypatch.setattr(deploy, "targets_summary", lambda: None)
    with pytest.raises(SystemExit) as exc_info:
        deploy.wait_and_report()
    assert exc_info.value.code == 1
    assert "not ready" in capsys.readouterr().out


def test_compose_logs_default_tails_everything(monkeypatch):
    monkeypatch.setenv(deploy.RUNTIME_ENV, "docker")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        deploy.subprocess,
        "run",
        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""),
    )
    with pytest.raises(SystemExit, match="0"):
        deploy.compose_logs(None)
    assert calls[0][4:] == ["logs", "--tail=200", "-f"]


def test_runtime_prefers_docker_when_both_installed(monkeypatch):
    monkeypatch.delenv(deploy.RUNTIME_ENV, raising=False)
    monkeypatch.setattr(
        deploy.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in ("docker", "podman") else None,
    )
    assert deploy.container_runtime() == "docker"


def test_podman_compose_failure_message_names_engine(monkeypatch):
    monkeypatch.setenv(deploy.RUNTIME_ENV, "podman")

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "boom")

    monkeypatch.setattr(deploy.subprocess, "run", fake_run)
    with pytest.raises(SystemExit, match="^podman compose up -d --build failed"):
        deploy.compose_up()
