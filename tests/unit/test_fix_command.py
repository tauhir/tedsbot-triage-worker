# ABOUTME: Tests the fix command orchestration with injected gates, run function,
# ABOUTME: CI watch, ticketing and notifier; no agent, git, or gh is ever real.
import json
import logging
from pathlib import Path

import pytest
import yaml

from tedsbot.ci import CiVerdict
from tedsbot.cli import main
from tedsbot.commands.fix import build_fix_spec, fix
from tedsbot.config import load_config
from tedsbot.errors import GateError, ProviderError
from tedsbot.runner import FIX_TOOLS
from tedsbot.summary import RunSummary

SLACK = "https://hooks.slack.example/T/B/X"


@pytest.fixture
def cfg(tmp_path: Path, config_dict: dict, env_tokens: None):
    config_dict["fix"] = {"ci_wait_minutes": 5}
    p = tmp_path / "tedsbot.yaml"
    p.write_text(yaml.safe_dump(config_dict))
    return load_config(p)


class FakeTickets:
    def __init__(self, status: str = "Approved For Fix") -> None:
        self.status, self.comments = status, []

    def status_of(self, key: str) -> str:
        return self.status

    def comment(self, key: str, body: str) -> None:
        self.comments.append((key, body))


class FakeNotifier:
    def __init__(self) -> None:
        self.posts: list[str] = []

    def post(self, text: str) -> None:
        self.posts.append(text)


def _draft(pr="https://github.com/example-org/example-app/pull/9"):
    async def run_fn(c, spec, run_dir):
        return RunSummary(kind="fix", ticket="APP-7", ticket_url="https://example.atlassian.net/browse/APP-7",
                          status="draft PR opened", pr_url=pr, headline="guarded null", tldr="Fixed.", ok=True)
    return run_fn


def test_fix_spec(cfg) -> None:
    spec = build_fix_spec(cfg, "APP-7")
    assert spec.kind == "fix" and spec.prompt_name == "fix" and spec.include_edit_tools
    assert spec.tools == FIX_TOOLS and spec.max_turns == 150
    assert spec.inputs == {"ticket_key": "APP-7", "branch": "tedsbot/APP-7", "base_branch": "main",
                           "github_repo": "example-org/example-app", "test_command": "none",
                           "pr_body_path": f"{cfg.repo.path}/.git/tedsbot/pr-body.md"}


async def test_gate_refusal_notifies_and_never_runs_the_agent(cfg, temp_home: Path) -> None:
    notifier, tickets = FakeNotifier(), FakeTickets()
    started = []

    async def run_fn(c, spec, run_dir):
        started.append(1)

    def gates(c, status_of, key, branch):
        raise GateError("checkout has uncommitted changes")

    summary, run_dir = await fix(cfg, "APP-7", run_fn=run_fn, gates_fn=gates, tickets=tickets, notifier=notifier)
    assert not started and summary.ok is False and summary.status == "gate refused"
    assert "uncommitted" in summary.headline and (run_dir / "summary.resolved.json").exists()
    assert notifier.posts and "precondition failed" in notifier.posts[0]


async def test_red_ci_hands_back_with_comment_and_second_message(cfg, temp_home: Path) -> None:
    notifier, tickets = FakeNotifier(), FakeTickets()
    summary, run_dir = await fix(cfg, "APP-7", run_fn=_draft(), gates_fn=lambda *a: None,
                                 watch_fn=lambda url, w, p: CiVerdict("failed", ["tests"]), tickets=tickets, notifier=notifier)
    assert summary.status == "CI red, handed back" and summary.headline.startswith("CI failed: tests")
    assert tickets.comments and tickets.comments[0][1].startswith("[tedsbot] CI is red")
    assert any("handed back" in p for p in notifier.posts)
    assert json.loads((run_dir / "summary.resolved.json").read_text())["status"] == "CI red, handed back"


async def test_red_ci_still_hands_back_when_comment_fails(cfg, temp_home: Path) -> None:
    class FailingCommentTickets(FakeTickets):
        def comment(self, key: str, body: str) -> None:
            raise ProviderError("jira down")

    notifier, tickets = FakeNotifier(), FailingCommentTickets()
    summary, run_dir = await fix(cfg, "APP-7", run_fn=_draft(), gates_fn=lambda *a: None,
                                 watch_fn=lambda url, w, p: CiVerdict("failed", ["tests"]), tickets=tickets, notifier=notifier)
    assert summary.status == "CI red, handed back"
    assert json.loads((run_dir / "summary.resolved.json").read_text())["status"] == "CI red, handed back"
    assert any("handed back" in p for p in notifier.posts)


async def test_green_ci_posts_second_message_without_comment(cfg, temp_home: Path) -> None:
    notifier, tickets = FakeNotifier(), FakeTickets()
    summary, _ = await fix(cfg, "APP-7", run_fn=_draft(), gates_fn=lambda *a: None,
                           watch_fn=lambda url, w, p: CiVerdict("passed"), tickets=tickets, notifier=notifier)
    assert summary.status == "CI green" and not tickets.comments and any("passed CI" in p for p in notifier.posts)


async def test_no_ci_wait_when_disabled(tmp_path: Path, config_dict: dict, env_tokens: None, temp_home: Path) -> None:
    p = tmp_path / "t.yaml"; p.write_text(yaml.safe_dump(config_dict)); c = load_config(p)
    called = []
    summary, _ = await fix(c, "APP-7", run_fn=_draft(), gates_fn=lambda *a: None,
                           watch_fn=lambda *a: called.append(1), tickets=FakeTickets(), notifier=FakeNotifier())
    assert not called and summary.status == "draft PR opened"


def test_cli_fix_exit_codes(tmp_path: Path, config_dict: dict, env_tokens: None, temp_home: Path,
                            monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "tedsbot.yaml"; p.write_text(yaml.safe_dump(config_dict))
    monkeypatch.setattr("tedsbot.commands.fix._run", _draft())
    monkeypatch.setattr("tedsbot.commands.fix._gates", lambda *a: None)
    monkeypatch.setattr("tedsbot.commands.fix._ticketing", lambda cfg: FakeTickets())
    monkeypatch.setattr("tedsbot.commands.fix._notifier", lambda cfg: FakeNotifier())
    assert main(["-c", str(p), "fix", "APP-7"]) == 0
    assert "Draft PR opened" in capsys.readouterr().out
    assert main(["-c", str(tmp_path / "absent.yaml"), "fix", "APP-7"]) == 2


async def test_fix_restores_checkout_after_run(cfg, temp_home: Path) -> None:
    calls: list[tuple] = []

    def restore(path, base_branch):
        calls.append((path, base_branch))

    await fix(cfg, "APP-7", run_fn=_draft(), gates_fn=lambda *a: None, restore_fn=restore,
              watch_fn=lambda url, w, p: CiVerdict("passed"), tickets=FakeTickets(), notifier=FakeNotifier())
    assert calls == [(cfg.repo.path, cfg.repo.base_branch)]

    async def boom(c, spec, run_dir):
        raise RuntimeError("agent exploded")

    with pytest.raises(RuntimeError, match="agent exploded"):
        await fix(cfg, "APP-7", run_fn=boom, gates_fn=lambda *a: None, restore_fn=restore,
                  tickets=FakeTickets(), notifier=FakeNotifier())
    assert calls == [(cfg.repo.path, cfg.repo.base_branch)] * 2


async def test_dirty_checkout_note_is_posted_and_logged(cfg, temp_home: Path, caplog) -> None:
    notifier = FakeNotifier()
    with caplog.at_level(logging.WARNING, logger="tedsbot.commands.fix"):
        await fix(cfg, "APP-7", run_fn=_draft(), gates_fn=lambda *a: None,
                  restore_fn=lambda path, base: "checkout left on 'tedsbot/APP-7' with uncommitted changes",
                  watch_fn=lambda url, w, p: CiVerdict("passed"), tickets=FakeTickets(), notifier=notifier)
    assert any("uncommitted changes" in post for post in notifier.posts)
    assert any("uncommitted changes" in record.getMessage() for record in caplog.records)


async def test_gate_provider_error_is_reported_not_raised(cfg, temp_home: Path) -> None:
    """A ticketing outage while a gate is being read is a refusal to report, not a traceback."""
    notifier = FakeNotifier()
    started = []

    async def run_fn(c, spec, run_dir):
        started.append(1)

    def gates(c, status_of, key, branch):
        raise ProviderError("jira 503")

    summary, run_dir = await fix(cfg, "APP-7", run_fn=run_fn, gates_fn=gates, restore_fn=lambda p, b: None,
                                 tickets=FakeTickets(), notifier=notifier)
    assert not started and summary.ok is False and summary.status == "gate refused"
    assert "gate could not be evaluated" in summary.headline and "jira 503" in summary.headline
    assert notifier.posts and "precondition failed" in notifier.posts[0]
    assert (run_dir / "summary.resolved.json").exists()
