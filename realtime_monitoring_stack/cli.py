"""Command line interface: `monitoring-stack [config|validate|deploy|...]`."""

from __future__ import annotations

import argparse
import sys

from realtime_monitoring_stack import deploy, render, validators
from realtime_monitoring_stack.models import ConfigError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="monitoring-stack",
        description="Deploy the enterprise Prometheus + Grafana + Loki stack "
        "with custom dashboards, PagerDuty integration, and SLO tracking.",
    )
    parser.add_argument(
        "--services",
        default="services.yaml",
        help="path to the service catalog (default: services.yaml)",
    )
    parser.add_argument(
        "--out",
        default="generated",
        help="output directory for generated configs (default: generated)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Also accept --services/--out after the subcommand (e.g. `config --out x`),
    # without clobbering the main-parser value when omitted.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--services", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument("--out", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    sub.add_parser("config", parents=[common], help="generate all configs into --out")
    sub.add_parser("validate", parents=[common], help="validate the generated configs")
    sub.add_parser(
        "deploy", parents=[common], help="generate configs, start the stack, run health checks"
    )
    sub.add_parser("down", parents=[common], help="stop the stack")
    sub.add_parser("status", parents=[common], help="show container status + health checks")
    sub.add_parser("check", parents=[common], help="run health checks against a running stack")
    logs = sub.add_parser("logs", parents=[common], help="tail container logs")
    logs.add_argument(
        "service", nargs="?", default=None, help="compose service name (default: all)"
    )
    return parser


def _load_or_die(args: argparse.Namespace) -> render.StackConfig | None:
    try:
        return render.load_services(args.services)
    except (ConfigError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command in ("config", "deploy"):
        cfg = _load_or_die(args)
        if cfg is None:
            return 1
        files = render.generate_all(cfg, out_dir=args.out)
        print(f"Generated {len(files)} config files in {render.output_abs(args.out)}/")
        ok, msg = render.env_is_configured()
        print(("[✓] " if ok else "[!] ") + msg)
        if args.command == "config":
            return 0

    if args.command == "validate":
        issues = validators.validate_generated(args.out)
        if not issues:
            print("Validation passed — generated configs look good.")
            return 0
        errors = [i for i in issues if i[0] == "error"]
        warnings = [i for i in issues if i[0] == "warning"]
        for _, message in errors:
            print(f"error:   {message}")
        for _, message in warnings:
            print(f"warning: {message}")
        print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
        return 1 if errors else 0

    if args.command == "deploy":
        deploy.compose_up()
        deploy.wait_and_report()
        print("\nDone. Grafana: http://localhost:3000  Prometheus: http://localhost:9090")
        return 0

    if args.command == "down":
        deploy.compose_down()
        return 0

    if args.command == "status":
        deploy.compose_ps()
        deploy.wait_and_report()
        return 0

    if args.command == "check":
        deploy.wait_and_report()
        return 0

    if args.command == "logs":
        deploy.compose_logs(args.service)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
