from __future__ import annotations

from realtime_monitoring_stack import grafana
from realtime_monitoring_stack.dashboards import (
    PROM,
    build_services_overview,
    build_slo_dashboard,
)


def _all_panels(dashboard: dict) -> list[dict]:
    return dashboard["panels"]


def test_services_overview_structure(cfg):
    dash = build_services_overview(cfg)
    assert dash["uid"] == "services-overview"
    assert dash["title"] == "Services Overview"
    panels = _all_panels(dash)
    assert any(p["type"] == "row" for p in panels)
    stats = [p for p in panels if p["type"] == "stat"]
    assert len(stats) == 4
    series = [p for p in panels if p["type"] == "timeseries"]
    assert len(series) == 4
    # Loki panel present for log correlation
    assert any(p["datasource"] == {"type": "loki", "uid": "loki"} for p in series)
    for panel in panels:
        if panel["type"] != "row":
            assert panel["targets"], f"{panel['title']} has no queries"


def test_slo_dashboard_has_per_service_panels(cfg):
    dash = build_slo_dashboard(cfg)
    assert dash["uid"] == "slo-error-budget"
    panels = _all_panels(dash)
    budget_stats = [p for p in panels if p["type"] == "stat"]
    expected = sum(len(s.slos) for s in cfg.services)
    assert len(budget_stats) == expected
    titles = " ".join(p["title"] for p in budget_stats).lower()
    for service in cfg.services:
        assert service.name in titles
    # thresholds warn/alert on budget depletion
    steps = budget_stats[0]["fieldConfig"]["defaults"]["thresholds"]["steps"]
    assert {s["color"] for s in steps} == {"red", "yellow", "green"}


def test_dashboards_use_provisioned_datasource_uids(cfg):
    for builder in (build_services_overview, build_slo_dashboard):
        dash = builder(cfg)
        for panel in _all_panels(dash):
            if panel["type"] == "row":
                continue
            assert panel["datasource"] in (PROM, {"type": "loki", "uid": "loki"}), panel["title"]
            for target in panel["targets"]:
                assert "refId" in target


def test_templating_service_variable(cfg):
    dash = build_services_overview(cfg)
    var = dash["templating"]["list"][0]
    assert var["name"] == "service"
    assert var["type"] == "query"
    assert var["includeAll"] and var["multi"]


def test_dashboards_serialize_to_valid_json(cfg):
    import json

    for builder in (build_services_overview, build_slo_dashboard):
        assert json.loads(json.dumps(builder(cfg))) == builder(cfg)


def test_provisioning_files(cfg):
    ds = grafana.build_datasources()
    assert {d["uid"] for d in ds["datasources"]} == {"prometheus", "loki"}
    prom = next(d for d in ds["datasources"] if d["uid"] == "prometheus")
    assert prom["url"] == "http://prometheus:9090" and prom["isDefault"]
    provider = grafana.build_dashboard_provider()
    assert provider["providers"][0]["options"]["path"] == "/var/lib/grafana/dashboards"
    assert set(grafana.build_dashboards(cfg)) == {"services-overview.json", "slo-error-budget.json"}
