# ABOUTME: Tests the check command with injected probes so no real servers or
# ABOUTME: gh are needed; asserts every check line and the overall verdict.
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
import respx
import yaml

from tedsbot.cli import main
from tedsbot.commands.check import _default_mcp_probe, run_check

STATUSES_URL = (
    "https://api.atlassian.com/ex/jira/00000000-0000-0000-0000-000000000000"
    "/rest/api/3/project/APP/statuses"
)
SENTRY_ORG_URL = "https://us.sentry.io/api/0/organizations/example-org/"


def _mock_sentry_auth(status: int = 200) -> None:
    respx.get(SENTRY_ORG_URL).mock(return_value=httpx.Response(status, json={}))


@pytest.fixture
def config_path(tmp_path: Path, config_dict: dict, env_tokens: None) -> Path:
    p = tmp_path / "tedsbot.yaml"
    p.write_text(yaml.safe_dump(config_dict))
    return p


@respx.mock
def test_all_green(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    _mock_sentry_auth()
    respx.get(STATUSES_URL).mock(
        return_value=httpx.Response(200, json=[{"name": "Bug", "statuses": [
            {"name": n} for n in ["To Triage", "Dev Team Review", "Approved For Fix", "In Progress", "Code Review"]]}])
    )
    report = run_check(config_path, mcp_probe=lambda c: True, gh_probe=lambda: True)
    assert report.ok
    names = [r[0] for r in report.results]
    assert names == ["config", "checkout", "mcp:sentry", "mcp:atlassian", "sentry auth",
                     "gh auth", "ticket statuses", "claude auth"]


@respx.mock
def test_missing_status_and_gh_fail(config_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    _mock_sentry_auth()
    respx.get(STATUSES_URL).mock(
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
        _mock_sentry_auth()
        respx.get(STATUSES_URL).mock(return_value=httpx.Response(200, json=[]))
        code = main(["-c", str(config_path), "check"])
    out = capsys.readouterr().out
    assert code == 1 and "[FAIL] gh auth" in out and "[ok] config" in out


def test_default_mcp_probe_unreachable_on_nonzero_exit() -> None:
    config = {"command": sys.executable, "args": ["-c", "raise SystemExit(1)"]}
    assert _default_mcp_probe(config) is False


def test_default_mcp_probe_reachable_on_zero_exit() -> None:
    config = {"command": sys.executable, "args": ["-c", "import sys; sys.stdin.read()"]}
    assert _default_mcp_probe(config) is True


def test_default_mcp_probe_unreachable_on_missing_binary() -> None:
    config = {"command": "/nonexistent/binary-xyz", "args": []}
    assert _default_mcp_probe(config) is False


def test_default_mcp_probe_reachable_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="x", timeout=20)

    monkeypatch.setattr("tedsbot.commands.check.subprocess.run", _raise_timeout)
    assert _default_mcp_probe({"command": "x", "args": []}) is True


def test_statuses_check_reports_transport_error(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    with respx.mock:
        _mock_sentry_auth()
        respx.get(STATUSES_URL).mock(side_effect=httpx.ConnectError("boom"))
        report = run_check(config_path, mcp_probe=lambda c: True, gh_probe=lambda: True)
    names = [r[0] for r in report.results]
    statuses_result = next(r for r in report.results if r[0] == "ticket statuses")
    assert statuses_result[1] is False and "boom" in statuses_result[2]
    assert names.index("claude auth") == names.index("ticket statuses") + 1


@respx.mock
def test_check_reports_unregistered_log_store(
    tmp_path: Path, config_dict: dict, env_tokens: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    config_dict["logs"] = {"kind": "grafana", "url": "https://g", "token": "t"}
    config_path = tmp_path / "tedsbot.yaml"
    config_path.write_text(yaml.safe_dump(config_dict))
    _mock_sentry_auth()
    respx.get(STATUSES_URL).mock(return_value=httpx.Response(200, json=[]))
    report = run_check(config_path, mcp_probe=lambda c: True, gh_probe=lambda: True)
    names = [r[0] for r in report.results]
    logs_row = next(r for r in report.results if r[0] == "provider:logs")
    assert logs_row[1] is False and "grafana" in logs_row[2]
    assert not any(n.startswith("mcp:grafana") for n in names)
    assert names[-1] == "claude auth"
    assert not report.ok


@respx.mock
def test_sentry_auth_row_passes_on_200(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    _mock_sentry_auth()
    respx.get(STATUSES_URL).mock(return_value=httpx.Response(200, json=[]))
    report = run_check(config_path, mcp_probe=lambda c: True, gh_probe=lambda: True)
    row = next(r for r in report.results if r[0] == "sentry auth")
    assert row[1] is True


@respx.mock
def test_sentry_auth_row_fails_with_status(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    _mock_sentry_auth(401)
    respx.get(STATUSES_URL).mock(return_value=httpx.Response(200, json=[]))
    report = run_check(config_path, mcp_probe=lambda c: True, gh_probe=lambda: True)
    row = next(r for r in report.results if r[0] == "sentry auth")
    assert row[1] is False and "401" in row[2]
    assert not report.ok
