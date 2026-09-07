# ABOUTME: Tests the fix-run gates: clean checkout on the base branch, ticket in the
# ABOUTME: approved status, and no open PR for the branch (gh is injected, never real).
import json
import subprocess
from pathlib import Path

import pytest

from tedsbot.errors import GateError
from tedsbot.gates import checkout_is_clean_on, no_open_pr_for, ticket_is_in


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True, capture_output=True)


def test_clean_checkout_on_base_passes(checkout: Path) -> None:
    checkout_is_clean_on(checkout, "main")


def test_dirty_checkout_is_refused(checkout: Path) -> None:
    (checkout / "scratch.txt").write_text("x")
    with pytest.raises(GateError, match="uncommitted"):
        checkout_is_clean_on(checkout, "main")


def test_wrong_branch_is_refused(checkout: Path) -> None:
    _git(checkout, "checkout", "-q", "-b", "feature")
    with pytest.raises(GateError, match="on 'feature', expected 'main'"):
        checkout_is_clean_on(checkout, "main")


def test_ticket_status_gate() -> None:
    ticket_is_in(lambda key: "Approved For Fix", "APP-1", "Approved For Fix")
    with pytest.raises(GateError, match="APP-1 is in 'Backlog', expected 'Approved For Fix'"):
        ticket_is_in(lambda key: "Backlog", "APP-1", "Approved For Fix")


def _fake_gh(stdout: str, returncode: int = 0, stderr: str = ""):
    calls: list[list[str]] = []

    def run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_no_open_pr_passes_and_queries_the_branch() -> None:
    run = _fake_gh("[]")
    no_open_pr_for("example-org/example-app", "tedsbot/APP-1", run=run)
    assert run.calls[0][:3] == ["gh", "pr", "list"] and "--head" in run.calls[0] and "tedsbot/APP-1" in run.calls[0]
    assert "--repo" in run.calls[0] and "example-org/example-app" in run.calls[0]


def test_open_pr_is_refused_with_its_url() -> None:
    run = _fake_gh(json.dumps([{"number": 7, "url": "https://github.com/example-org/example-app/pull/7"}]))
    with pytest.raises(GateError, match="pull/7"):
        no_open_pr_for("example-org/example-app", "tedsbot/APP-1", run=run)


def test_gh_failure_is_a_gate_error() -> None:
    with pytest.raises(GateError, match="gh pr list failed"):
        no_open_pr_for("example-org/example-app", "tedsbot/APP-1", run=_fake_gh("", 1, "not logged in"))
