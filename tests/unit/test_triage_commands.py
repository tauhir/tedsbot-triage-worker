# ABOUTME: Tests the triage command wiring with an injected run function so
# ABOUTME: no agent is started: spec shape, run dir creation, exit codes.
from pathlib import Path

import pytest
import yaml

from tedsbot.cli import main
from tedsbot.commands.triage import build_sentry_spec, build_ticket_spec, triage
from tedsbot.config import load_config
from tedsbot.runner import TRIAGE_TOOLS
from tedsbot.summary import RunSummary


@pytest.fixture
def cfg(tmp_path: Path, config_dict: dict, env_tokens: None):
    p = tmp_path / "tedsbot.yaml"
    p.write_text(yaml.safe_dump(config_dict))
    return load_config(p)


def test_sentry_spec(cfg) -> None:
    spec = build_sentry_spec(cfg, "APP-1")
    assert spec.kind == "triage_sentry" and spec.prompt_name == "triage_sentry"
    assert spec.inputs == {"sentry_issue": "APP-1"} and spec.max_turns == 60
    assert spec.tools == TRIAGE_TOOLS and not spec.include_edit_tools


def test_ticket_spec(cfg) -> None:
    spec = build_ticket_spec(cfg, "APP-2")
    assert spec.kind == "triage_ticket" and spec.inputs == {"ticket_key": "APP-2"}


async def test_triage_creates_run_dir_and_returns_summary(cfg, temp_home: Path) -> None:
    seen: dict = {}

    async def fake_run(c, spec, run_dir):
        seen["run_dir"] = run_dir
        return RunSummary(kind=spec.kind, headline="ok", ok=True)

    summary, run_dir = await triage(cfg, build_sentry_spec(cfg, "APP-1"), run_fn=fake_run)
    assert summary.ok and run_dir == seen["run_dir"]
    assert run_dir.parent == temp_home / ".tedsbot" / "runs"


def test_cli_exit_codes(tmp_path: Path, config_dict: dict, env_tokens: None, temp_home: Path,
                        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "tedsbot.yaml"
    p.write_text(yaml.safe_dump(config_dict))

    async def failing(c, spec, run_dir):
        return RunSummary(kind=spec.kind, headline="agent died", ok=False)

    monkeypatch.setattr("tedsbot.commands.triage._run", failing)
    assert main(["-c", str(p), "triage", "ticket", "APP-9"]) == 1
    assert "agent died" in capsys.readouterr().out

    async def passing(c, spec, run_dir):
        return RunSummary(kind=spec.kind, ticket="APP-9", headline="fine", recommendation="🟢", ok=True)

    monkeypatch.setattr("tedsbot.commands.triage._run", passing)
    assert main(["-c", str(p), "triage", "sentry", "APP-9"]) == 0


def test_cli_config_error_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["-c", str(tmp_path / "absent.yaml"), "triage", "sentry", "APP-1"]) == 2
    assert "config error" in capsys.readouterr().err
