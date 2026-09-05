from __future__ import annotations

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
