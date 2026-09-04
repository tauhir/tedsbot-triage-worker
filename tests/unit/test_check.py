# ABOUTME: Tests the check command with injected probes so no real servers or
# ABOUTME: gh are needed; asserts every check line and the overall verdict.
from pathlib import Path

import httpx
import pytest
import respx
import yaml

from tedsbot.cli import main
from tedsbot.commands.check import run_check


@pytest.fixture
def config_path(tmp_path: Path, config_dict: dict, env_tokens: None) -> Path:
    p = tmp_path / "tedsbot.yaml"
    p.write_text(yaml.safe_dump(config_dict))
    return p


@respx.mock
def test_all_green(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    respx.get("https://example.atlassian.net/rest/api/3/project/APP/statuses").mock(
        return_value=httpx.Response(200, json=[{"name": "Bug", "statuses": [
            {"name": n} for n in ["To Triage", "Dev Team Review", "Approved For Fix", "In Progress", "Code Review"]]}])
    )
    report = run_check(config_path, mcp_probe=lambda c: True, gh_probe=lambda: True)
    assert report.ok
    names = [r[0] for r in report.results]
    assert names == ["config", "checkout", "mcp:sentry", "mcp:atlassian", "gh auth", "ticket statuses", "claude auth"]


@respx.mock
def test_missing_status_and_gh_fail(config_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    respx.get("https://example.atlassian.net/rest/api/3/project/APP/statuses").mock(
        return_value=httpx.Response(200, json=[{"name": "Bug", "statuses": [{"name": "To Triage"}]}])
    )
    report = run_check(config_path, mcp_probe=lambda c: True, gh_probe=lambda: False)
    assert not report.ok
    failed = {r[0]: r[2] for r in report.results if not r[1]}
    assert "gh auth" in failed and "Dev Team Review" in failed["ticket statuses"]


def test_config_failure_short_circuits(tmp_path: Path) -> None:
    report = run_check(tmp_path / "absent.yaml", mcp_probe=lambda c: True, gh_probe=lambda: True)
    assert not report.ok and [r[0] for r in report.results] == ["config"]


def test_cli_check_exit_code(config_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr("tedsbot.commands.check._default_mcp_probe", lambda c: True)
    monkeypatch.setattr("tedsbot.commands.check._default_gh_probe", lambda: False)
    with respx.mock:
        respx.get("https://example.atlassian.net/rest/api/3/project/APP/statuses").mock(
            return_value=httpx.Response(200, json=[]))
        code = main(["-c", str(config_path), "check"])
    out = capsys.readouterr().out
    assert code == 1 and "[FAIL] gh auth" in out and "[ok] config" in out
