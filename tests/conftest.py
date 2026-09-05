from __future__ import annotations

import pytest

from realtime_monitoring_stack.models import load_config


@pytest.fixture(scope="session")
def cfg():
    return load_config("services.yaml")


@pytest.fixture(scope="session")
def rendered(tmp_path_factory, cfg):
    """Render the full config tree into a temp dir once per session."""
    from realtime_monitoring_stack import render

    out = tmp_path_factory.mktemp("generated")
    files = render.generate_all(cfg, out_dir=str(out))
    return out, files
