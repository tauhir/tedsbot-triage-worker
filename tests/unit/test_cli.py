# ABOUTME: Tests the argparse CLI surface: version, help, subcommand names.
# ABOUTME: Command behaviour is tested in the per-command test modules.
import pytest

from tedsbot import __version__
from tedsbot.cli import build_parser, main


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_parser_has_expected_subcommands() -> None:
    parser = build_parser()
    subparsers = next(a for a in parser._actions if a.dest == "command")
    assert set(subparsers.choices) == {"check", "triage", "fix", "worker"}


def test_triage_has_sentry_and_ticket() -> None:
    parser = build_parser()
    ns = parser.parse_args(["triage", "sentry", "APP-1"])
    assert ns.command == "triage" and ns.triage_kind == "sentry" and ns.target == "APP-1"
    ns = parser.parse_args(["triage", "ticket", "APP-2"])
    assert ns.triage_kind == "ticket" and ns.target == "APP-2"


def test_no_command_prints_help_and_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "usage:" in capsys.readouterr().err
