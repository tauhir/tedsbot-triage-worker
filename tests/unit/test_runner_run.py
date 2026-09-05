# ABOUTME: Tests the executing half of the runner: transcript, summary
# ABOUTME: resolution, setup-failure envelope, and Slack notification.
import json
from pathlib import Path

import httpx
import pytest
import respx
import yaml
from claude_agent_sdk import ResultMessage

from tedsbot import runner
from tedsbot.config import load_config
from tedsbot.runner import TRIAGE_TOOLS, RunSpec

WEBHOOK = "https://hooks.slack.example/T/B/X"


@pytest.fixture
def cfg(tmp_path: Path, config_dict: dict, env_tokens: None):
    p = tmp_path / "tedsbot.yaml"
    p.write_text(yaml.safe_dump(config_dict))
    return load_config(p)


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    d = tmp_path / "run"
    d.mkdir()
    return d


def _spec() -> RunSpec:
    return RunSpec(kind="triage_sentry", prompt_name="triage_sentry",
                   inputs={"sentry_issue": "APP-1"}, max_turns=60,
                   tools=list(TRIAGE_TOOLS), run_id="r1")


def _result_message(text: str) -> ResultMessage:
    return ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1,
                         is_error=False, num_turns=1, session_id="s1", result=text)


SUMMARY = {
    "kind": "triage_sentry",
    "ticket": "APP-7",
    "ticket_url": "https://example.atlassian.net/browse/APP-7",
    "recommendation": "🟢",
    "headline": "null deref in checkout",
    "ok": True,
}


def _agent(run_dir: Path, *, summary: dict | None = None, raises: Exception | None = None):
    """Build a fake query() that writes a summary then yields/raises."""

    async def _query(*, prompt: str, options: object):
        if summary is not None:
            (run_dir / "summary.json").write_text(json.dumps(summary))
        yield "starting"
        yield _result_message("agent finished")
        if raises is not None:
            raise raises

    return _query


async def test_successful_run_records_transcript_and_notifies(
    cfg, run_dir: Path, temp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "query", _agent(run_dir, summary=SUMMARY))
    with respx.mock:
        route = respx.post(WEBHOOK).mock(return_value=httpx.Response(200))
        summary = await runner.run(cfg, _spec(), run_dir)
    assert summary.ok is True and summary.ticket == "APP-7"
    lines = (run_dir / "transcript.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["type"] for line in lines] == ["str", "ResultMessage"]
    resolved = json.loads((run_dir / "summary.resolved.json").read_text())
    assert resolved["headline"] == "null deref in checkout"
    assert (run_dir / "prompt.md").read_text()
    posted = json.loads(route.calls[0].request.content)["text"]
    assert posted.startswith("*🟢 ") and "*<https://example.atlassian.net/browse/APP-7|APP-7>*" in posted
    assert "*Technical:* null deref in checkout" in posted and "Approved For Fix" in posted


async def test_crash_after_summary_reports_not_ok(
    cfg, run_dir: Path, temp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "query",
                        _agent(run_dir, summary=SUMMARY, raises=RuntimeError("boom")))
    with respx.mock:
        route = respx.post(WEBHOOK).mock(return_value=httpx.Response(200))
        summary = await runner.run(cfg, _spec(), run_dir)
    assert summary.ok is False
    # The agent's own headline survives; the crash is appended to it.
    assert summary.headline.startswith("null deref in checkout")
    assert "run failed" in summary.headline
    assert json.loads(route.calls[0].request.content)["text"].startswith("*⚠️ Triage run failed")


async def test_setup_failure_never_escapes(
    cfg, run_dir: Path, temp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*args: object, **kwargs: object) -> str:
        raise KeyError("missing_fact")

    monkeypatch.setattr(runner, "render_prompt", _boom)
    monkeypatch.setattr(runner, "query", _agent(run_dir, summary=SUMMARY))
    with respx.mock:
        route = respx.post(WEBHOOK).mock(return_value=httpx.Response(200))
        summary = await runner.run(cfg, _spec(), run_dir)
    assert summary.ok is False
    assert "before agent start" in summary.headline
    assert (run_dir / "summary.resolved.json").is_file()
    assert json.loads(route.calls[0].request.content)["text"].startswith("*⚠️ Triage run failed")


async def test_notifier_failure_does_not_raise(
    cfg, run_dir: Path, temp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "query", _agent(run_dir, summary=SUMMARY))
    with respx.mock:
        respx.post(WEBHOOK).mock(return_value=httpx.Response(500, text="nope"))
        summary = await runner.run(cfg, _spec(), run_dir)
    assert summary.ok is True and summary.ticket == "APP-7"
