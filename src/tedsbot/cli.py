# ABOUTME: argparse entry point for the tedsbot CLI.
# ABOUTME: Parses subcommands and dispatches to the command modules.
from __future__ import annotations

import argparse
import sys

from tedsbot import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tedsbot", description="Triage and fix worker.")
    parser.add_argument("--version", action="version", version=f"tedsbot {__version__}")
    parser.add_argument("-c", "--config", default="tedsbot.yaml", help="Path to config YAML.")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("check", help="Validate config and connectivity.")

    triage = sub.add_parser("triage", help="Run one triage analysis.")
    triage_sub = triage.add_subparsers(dest="triage_kind", required=True)
    for kind, help_text in (("sentry", "Sentry issue id or URL"), ("ticket", "Ticket key")):
        p = triage_sub.add_parser(kind)
        p.add_argument("target", help=help_text)

    fix = sub.add_parser("fix", help="Implement an approved ticket as a draft PR.")
    fix.add_argument("target", help="Ticket key")

    worker = sub.add_parser("worker", help="Poll and launch runs in a loop.")
    worker.add_argument("--once", action="store_true", help="Run one cycle and exit.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    if ns.command is None:
        parser.print_help(sys.stderr)
        return 2
    return _dispatch(ns)


def _dispatch(ns: argparse.Namespace) -> int:
    from pathlib import Path

    config_path = Path(ns.config)
    if ns.command == "check":
        from tedsbot.commands.check import run_check

        report = run_check(config_path)
        for name, ok, detail in report.results:
            print(f"[{'ok' if ok else 'FAIL'}] {name} — {detail}")
        return 0 if report.ok else 1
    # Remaining command modules are wired in later tasks; unknown commands report clearly.
    print(f"{ns.command}: not implemented yet", file=sys.stderr)
    return 1
