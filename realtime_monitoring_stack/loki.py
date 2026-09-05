"""Loki (log storage) and Promtail (log shipping) configuration."""

from __future__ import annotations

LOKI_CONFIG = """\
# Minimal single-binary Loki configuration (Grafana Loki 3.x).
auth_enabled: false

server:
  http_listen_port: 3100

common:
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

limits_config:
  retention_period: 720h
  allow_structured_metadata: true

compactor:
  working_directory: /loki/compactor
  compactor_ring:
    kvstore:
      store: inmemory
"""


def build_promtail_config() -> dict:
    """Promtail config scraping Docker container logs and shipping to Loki.

    The `service` label is derived from the docker-compose service name so log
    streams line up with the `service` label used by Prometheus metrics.
    """
    return {
        "server": {"http_listen_port": 9080, "grpc_listen_port": 0},
        "positions": {"filename": "/tmp/positions.yaml"},
        "clients": [{"url": "http://loki:3100/loki/api/v1/push"}],
        "scrape_configs": [
            {
                "job_name": "docker",
                "docker_sd_configs": [
                    {
                        "host": "unix:///var/run/docker.sock",
                        "refresh_interval": "5s",
                    }
                ],
                "relabel_configs": [
                    {
                        "source_labels": ["__meta_docker_container_name"],
                        "regex": "/(.*)",
                        "target_label": "container",
                    },
                    {
                        "source_labels": [
                            "__meta_docker_container_label_com_docker_compose_service"
                        ],
                        "target_label": "service",
                    },
                    {
                        "source_labels": [
                            "__meta_docker_container_label_com_docker_compose_project"
                        ],
                        "target_label": "compose_project",
                    },
                    {
                        "source_labels": ["__meta_docker_container_log_stream"],
                        "target_label": "stream",
                    },
                ],
            }
        ],
    }
