# ABOUTME: Tests the triage command wiring with an injected run function so
# ABOUTME: no agent is started: spec shape, run dir creation, exit codes.
import logging
from pathlib import Path

import pytest
import yaml

from tedsbot.cli import main
from tedsbot.commands.triage import build_sentry_spec, build_ticket_spec, triage
from tedsbot.config import load_config
from tedsbot.errors import ProviderError
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

    class T:
        def status_of(self, key):
            return "Dev Team Review"

    class N:
        def post(self, t):
            pass

    async def fake_run(c, spec, run_dir):
        seen["run_dir"] = run_dir
        return RunSummary(kind=spec.kind, headline="ok", ok=True)

    summary, run_dir = await triage(cfg, build_sentry_spec(cfg, "APP-1"), run_fn=fake_run, tickets=T(), notifier=N())
    assert summary.ok and run_dir == seen["run_dir"]
    assert run_dir.parent == temp_home / ".tedsbot" / "runs"


async def test_triage_warns_when_ticket_moved_past_target(cfg, temp_home: Path) -> None:
    posts = []

    class N:
        def post(self, t): posts.append(t)

    class T:
        def status_of(self, key): return "Done"

    async def fake_run(c, spec, run_dir):
        return RunSummary(kind="triage_sentry", ticket="APP-1", headline="ok", tldr="t", ok=True)

    await triage(cfg, build_sentry_spec(cfg, "APP-1"), run_fn=fake_run, tickets=T(), notifier=N())
    assert posts and "is in 'Done' after triage" in posts[0]


async def test_triage_silent_when_ticket_in_target(cfg, temp_home: Path) -> None:
    posts = []

    class N:
        def post(self, t): posts.append(t)

    class T:
        def status_of(self, key): return "Dev Team Review"

    async def fake_run(c, spec, run_dir):
        return RunSummary(kind="triage_sentry", ticket="APP-1", headline="ok", tldr="t", ok=True)

    await triage(cfg, build_sentry_spec(cfg, "APP-1"), run_fn=fake_run, tickets=T(), notifier=N())
    assert posts == []


async def test_triage_status_reread_survives_provider_error(cfg, temp_home: Path,
                                                             caplog: pytest.LogCaptureFixture) -> None:
    class N:
        def post(self, t):
            raise AssertionError("should not post when status_of raises")

    class T:
        def status_of(self, key):
            raise ProviderError("jira down")

    async def fake_run(c, spec, run_dir):
        return RunSummary(kind="triage_sentry", ticket="APP-1", headline="ok", tldr="t", ok=True)

    with caplog.at_level(logging.WARNING):
        summary, _run_dir = await triage(cfg, build_sentry_spec(cfg, "APP-1"), run_fn=fake_run, tickets=T(), notifier=N())
    assert summary.ok
    assert any("APP-1" in r.message for r in caplog.records)


async def test_triage_warning_post_survives_provider_error(cfg, temp_home: Path,
                                                            caplog: pytest.LogCaptureFixture) -> None:
    class N:
        def post(self, t):
            raise ProviderError("slack down")

    class T:
        def status_of(self, key):
            return "Done"

    async def fake_run(c, spec, run_dir):
        return RunSummary(kind="triage_sentry", ticket="APP-1", headline="ok", tldr="t", ok=True)

    with caplog.at_level(logging.WARNING):
        summary, _run_dir = await triage(cfg, build_sentry_spec(cfg, "APP-1"), run_fn=fake_run, tickets=T(), notifier=N())
    assert summary.ok
    assert any("is in 'Done' after triage" in r.message for r in caplog.records)


def test_cli_exit_codes(tmp_path: Path, config_dict: dict, env_tokens: None, temp_home: Path,
                        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "tedsbot.yaml"
    p.write_text(yaml.safe_dump(config_dict))

    class FakeTickets:
        def status_of(self, key: str) -> str:
            return "Dev Team Review"

    class FakeNotifier:
        def post(self, text: str) -> None:
            pass

    monkeypatch.setattr("tedsbot.commands.triage._ticketing", lambda cfg: FakeTickets())
    monkeypatch.setattr("tedsbot.commands.triage._notifier", lambda cfg: FakeNotifier())

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
