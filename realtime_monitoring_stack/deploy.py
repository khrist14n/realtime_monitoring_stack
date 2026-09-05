"""docker compose orchestration + post-deploy health checks."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import requests

COMPOSE_FILE = "docker-compose.yml"
HEALTH_RETRIES = 30
HEALTH_INTERVAL = 5


def _compose(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", "-f", COMPOSE_FILE, *args]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(f"docker compose {' '.join(args)} failed (exit {result.returncode})")
    return result


def compose_up() -> None:
    print("Starting stack: docker compose up -d --build")
    _compose("up", "-d", "--build")
    print("Stack started. Waiting for services to become healthy...")


def compose_down() -> None:
    _compose("down")
    print("Stack stopped.")


def compose_ps() -> subprocess.CompletedProcess:
    return _compose("ps")


def compose_logs(service: str | None) -> None:
    args = (
        ["logs", "--tail=200", "-f"] if service is None else ["logs", "--tail=200", "-f", service]
    )
    result = subprocess.run(["docker", "compose", "-f", COMPOSE_FILE, *args], check=False)
    raise SystemExit(result.returncode)


def _url(name: str) -> str:
    return os.environ.get(
        f"{name.upper()}_URL",
        {
            "prometheus": "http://localhost:9090",
            "grafana": "http://localhost:3000",
            "loki": "http://localhost:3100",
        }[name],
    )


def _wait_ready(url: str, path: str, name: str, timeout: int) -> bool:
    for _ in range(timeout):
        try:
            resp = requests.get(f"{url}{path}", timeout=5)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(HEALTH_INTERVAL)
    return False


def health_check() -> dict[str, bool]:
    """Poll the key services and report readiness."""
    results: dict[str, bool] = {}
    for name, path in (("prometheus", "/-/ready"), ("grafana", "/api/health"), ("loki", "/ready")):
        ok = _wait_ready(_url(name), path, name, HEALTH_RETRIES)
        results[name] = ok
        print(f"  {name:<12} {'UP' if ok else 'DOWN'}  ({_url(name)})")
    return results


def targets_summary() -> None:
    """Summarize Prometheus scrape targets (up/down per job)."""
    try:
        resp = requests.get(f"{_url('prometheus')}/api/v1/targets", timeout=10)
        resp.raise_for_status()
    except requests.RequestException:
        print("  (could not query Prometheus targets)")
        return
    targets = resp.json()["data"]["activeTargets"]
    by_job: dict[str, list[bool]] = {}
    for t in targets:
        by_job.setdefault(t["labels"].get("job", "?"), []).append(t["health"] == "up")
    for job, states in sorted(by_job.items()):
        up = sum(states)
        print(f"  {job:<24} {up}/{len(states)} targets up")


def wait_and_report() -> None:
    print("Health checks:")
    results = health_check()
    if not all(results.values()):
        print("\nSome services are not ready yet — check `monitoring-stack logs`.")
        raise SystemExit(1)
    print("\nPrometheus scrape targets:")
    targets_summary()
