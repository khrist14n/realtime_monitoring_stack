"""Domain models: service catalog + SLO definitions, parsed from services.yaml."""

from __future__ import annotations

import dataclasses
from typing import Any

import yaml

VALID_SLIS = ("availability", "latency", "throughput", "freshness")

DEFAULT_METRICS: dict[str, Any] = {
    "requests_metric": "http_requests_total",
    "status_label": "status",
    "error_status_regex": "5..",
    "latency_histogram_metric": "http_request_duration_seconds_bucket",
    "latency_bucket_unit": "seconds",
    "freshness_metric": "batch_job_last_success_ts_seconds",
}

DEFAULT_BURN_RATES = {
    "fast": 14.4,  # ~2% of a 30d budget consumed in 1h -> page
    "slow": 6.0,  # ~5% of a 30d budget consumed in 6h -> warn
}
DEFAULT_WINDOWS = {
    "fast": "1h",
    "fast_short": "5m",
    "slow": "6h",
    "slow_short": "30m",
}


class ConfigError(ValueError):
    """Raised when services.yaml is invalid."""


@dataclasses.dataclass(frozen=True)
class Slo:
    name: str
    sli: str
    target: float  # e.g. 0.999
    window: str = "30d"
    latency_threshold_ms: float | None = None
    throughput_per_sec: float | None = None
    max_freshness_seconds: float | None = None

    def validate(self) -> None:
        if self.sli not in VALID_SLIS:
            raise ConfigError(
                f"SLO '{self.name}' has unsupported sli '{self.sli}' "
                f"(expected one of {', '.join(VALID_SLIS)})"
            )
        if not 0.0 < self.target < 1.0:
            raise ConfigError(f"SLO '{self.name}' target must be in (0, 1), got {self.target}")
        if self.sli == "latency" and not self.latency_threshold_ms:
            raise ConfigError(f"Latency SLO '{self.name}' requires latency_threshold_ms")
        if self.sli == "throughput" and (
            not self.throughput_per_sec or self.throughput_per_sec <= 0
        ):
            raise ConfigError(f"Throughput SLO '{self.name}' requires throughput_per_sec > 0")
        if self.sli == "freshness" and (
            not self.max_freshness_seconds or self.max_freshness_seconds <= 0
        ):
            raise ConfigError(f"Freshness SLO '{self.name}' requires max_freshness_seconds > 0")

    @property
    def error_budget(self) -> float:
        """The tolerable error fraction: 1 - target (e.g. 0.001 for 99.9%)."""
        return 1.0 - self.target

    @property
    def latency_threshold_seconds(self) -> float | None:
        if self.latency_threshold_ms is None:
            return None
        return self.latency_threshold_ms / 1000.0


@dataclasses.dataclass(frozen=True)
class Service:
    name: str
    targets: list[str]
    slos: list[Slo]
    team: str = "platform"
    metrics: dict[str, Any] = dataclasses.field(default_factory=dict)

    def metric(self, key: str) -> str:
        return self.metrics.get(key, DEFAULT_METRICS[key])


@dataclasses.dataclass(frozen=True)
class StackConfig:
    services: list[Service]
    scrape_interval: str = "15s"
    evaluation_interval: str = "30s"

    def slo(self, service: str, slo_name: str) -> Slo:
        for svc in self.services:
            if svc.name == service:
                for slo in svc.slos:
                    if slo.name == slo_name:
                        return slo
        raise KeyError(f"No SLO {service}/{slo_name}")


def _parse_metrics(raw: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_METRICS)
    if raw:
        merged.update(raw)
    return merged


def _parse_slo(raw: dict[str, Any]) -> Slo:
    slo = Slo(
        name=str(raw.get("name", "")),
        sli=str(raw.get("sli", "")),
        target=float(raw["target"]),
        window=str(raw.get("window", "30d")),
        latency_threshold_ms=raw.get("latency_threshold_ms"),
        throughput_per_sec=raw.get("throughput_per_sec"),
        max_freshness_seconds=raw.get("max_freshness_seconds"),
    )
    slo.validate()
    return slo


def _parse_service(raw: dict[str, Any], global_metrics: dict[str, Any]) -> Service:
    name = str(raw.get("name", "")).strip()
    if not name:
        raise ConfigError("Every service must have a non-empty name")
    targets = [str(t) for t in raw.get("targets", [])]
    if not targets:
        raise ConfigError(f"Service '{name}' must define at least one scrape target")
    slos = [_parse_slo(s) for s in raw.get("slos", [])]
    if not slos:
        raise ConfigError(f"Service '{name}' must define at least one SLO")
    merged_metrics = dict(global_metrics)
    merged_metrics.update(raw.get("metrics", {}) or {})
    return Service(
        name=name,
        targets=targets,
        slos=slos,
        team=str(raw.get("team", "platform")),
        metrics=merged_metrics,
    )


def load_config(path: str) -> StackConfig:
    """Parse and validate a services.yaml file."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a YAML mapping at the top level")

    global_metrics = _parse_metrics(raw.get("metrics"))
    services = [_parse_service(s, global_metrics) for s in raw.get("services", [])]
    if not services:
        raise ConfigError(f"{path}: no services defined")

    names = [s.name for s in services]
    if len(names) != len(set(names)):
        raise ConfigError(f"{path}: service names must be unique")

    return StackConfig(
        services=services,
        scrape_interval=str(raw.get("scrape_interval", "15s")),
        evaluation_interval=str(raw.get("evaluation_interval", "30s")),
    )
