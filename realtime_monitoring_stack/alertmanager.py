"""Alertmanager configuration with PagerDuty integration.

Routing model:
  severity="page"    -> PagerDuty urgency "high" (critical SLO burn)
  severity="warning" -> PagerDuty urgency "low"  (slow burn / early warning)
  everything else    -> PagerDuty default

The routing key is read from the PAGERDUTY_ROUTING_KEY env var at config
generation time; a placeholder is used (with a loud warning) when unset so the
stack still deploys for local development.
"""

from __future__ import annotations

import os

PLACEHOLDER_KEY = "CHANGE_ME_PAGERDUTY_ROUTING_KEY"

GRAFANA_URL = "http://grafana:3000"


def pagerduty_routing_key() -> str:
    """Routing key for the Events API v2 integration (aka integration key)."""
    return os.environ.get("PAGERDUTY_ROUTING_KEY", "").strip()


def has_pagerduty_key() -> bool:
    return bool(pagerduty_routing_key())


def build_alertmanager_config() -> dict:
    key = pagerduty_routing_key() or PLACEHOLDER_KEY
    common = {
        "routing_key": key,
        "client": "realtime-monitoring-stack",
        "client_url": GRAFANA_URL,
        "description": "{{ .CommonAnnotations.summary }}",
    }
    return {
        "global": {"resolve_timeout": "5m"},
        "route": {
            "receiver": "pagerduty",
            "group_by": ["service", "slo", "severity"],
            "group_wait": "30s",
            "group_interval": "5m",
            "repeat_interval": "4h",
            "routes": [
                {
                    "matchers": ['severity="warning"'],
                    "receiver": "pagerduty-warning",
                    "continue": True,
                },
                {
                    "matchers": ['severity="page"'],
                    "receiver": "pagerduty-critical",
                    "continue": True,
                },
            ],
        },
        "receivers": [
            {
                "name": "pagerduty",
                "pagerduty_configs": [dict(common, severity="error")],
            },
            {
                "name": "pagerduty-critical",
                "pagerduty_configs": [dict(common, severity="critical")],
            },
            {
                "name": "pagerduty-warning",
                "pagerduty_configs": [dict(common, severity="warning")],
            },
        ],
    }
