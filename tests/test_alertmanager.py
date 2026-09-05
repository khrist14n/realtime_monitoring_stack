from __future__ import annotations

from realtime_monitoring_stack import alertmanager


def test_pagerduty_receivers_and_routing(monkeypatch):
    monkeypatch.setenv("PAGERDUTY_ROUTING_KEY", "abc123")
    conf = alertmanager.build_alertmanager_config()
    receivers = {r["name"]: r for r in conf["receivers"]}
    assert set(receivers) == {"pagerduty", "pagerduty-critical", "pagerduty-warning"}
    assert receivers["pagerduty"]["pagerduty_configs"][0]["routing_key"] == "abc123"
    assert receivers["pagerduty-critical"]["pagerduty_configs"][0]["severity"] == "critical"
    assert receivers["pagerduty-warning"]["pagerduty_configs"][0]["severity"] == "warning"
    # routing: warnings -> low urgency, pages -> critical
    matchers = [(r["matchers"], r["receiver"]) for r in conf["route"]["routes"]]
    assert (['severity="warning"'], "pagerduty-warning") in matchers
    assert (['severity="page"'], "pagerduty-critical") in matchers
    assert conf["route"]["receiver"] == "pagerduty"


def test_placeholder_key_when_unset(monkeypatch):
    monkeypatch.delenv("PAGERDUTY_ROUTING_KEY", raising=False)
    conf = alertmanager.build_alertmanager_config()
    key = conf["receivers"][0]["pagerduty_configs"][0]["routing_key"]
    assert key == alertmanager.PLACEHOLDER_KEY
    assert not alertmanager.has_pagerduty_key()


def test_annotations_forwarded_to_pagerduty(monkeypatch):
    monkeypatch.setenv("PAGERDUTY_ROUTING_KEY", "abc123")
    conf = alertmanager.build_alertmanager_config()
    pd = conf["receivers"][0]["pagerduty_configs"][0]
    assert pd["description"] == "{{ .CommonAnnotations.summary }}"
    assert pd["client"] == "realtime-monitoring-stack"
