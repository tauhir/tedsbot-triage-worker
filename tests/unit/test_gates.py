# ABOUTME: Tests the fix-run gates: clean checkout on the base branch, ticket in the
# ABOUTME: approved status, and no open PR for the branch (gh is injected, never real).
import json
import logging
import subprocess
from pathlib import Path

import pytest
import yaml

from tedsbot.config import load_config
from tedsbot.errors import GateError
from tedsbot.gates import (
    checkout_is_clean_on,
    no_open_pr_for,
    restore_checkout,
    run_fix_gates,
    ticket_is_in,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True, capture_output=True)


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "tedsbot.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


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


def _mixed_run(gh_stdout: str = "[]"):
    """Delegate git commands to the real subprocess.run; fake only gh."""
    calls: list[list[str]] = []

    def run(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd[0] == "git":
            check = kwargs.pop("check", False)
            return subprocess.run(cmd, check=check, **kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout=gh_stdout, stderr="")

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_run_fix_gates_runs_all_three_in_order(
    checkout: Path, config_dict: dict, env_tokens: None, tmp_path: Path
) -> None:
    cfg = load_config(_write(tmp_path, config_dict))
    run = _mixed_run()
    status_calls: list[str] = []

    def status_of(key: str) -> str:
        status_calls.append(key)
        return "Approved For Fix"

    run_fix_gates(cfg, status_of, "APP-1", "tedsbot/APP-1", run=run)

    assert status_calls == ["APP-1"]
    gh_call = next(c for c in run.calls if c[0] == "gh")
    assert "--head" in gh_call and "tedsbot/APP-1" in gh_call
    assert "--repo" in gh_call and "example-org/example-app" in gh_call


def test_run_fix_gates_short_circuits_on_dirty_checkout(
    checkout: Path, config_dict: dict, env_tokens: None, tmp_path: Path
) -> None:
    (checkout / "scratch.txt").write_text("x")
    cfg = load_config(_write(tmp_path, config_dict))
    run = _mixed_run()

    def status_of(key: str) -> str:
        raise AssertionError("should not be called")

    with pytest.raises(GateError, match="uncommitted"):
        run_fix_gates(cfg, status_of, "APP-1", "tedsbot/APP-1", run=run)

    assert not any(call[0] == "gh" for call in run.calls)


def test_detached_head_is_refused(checkout: Path) -> None:
    _git(checkout, "checkout", "-q", "--detach")
    with pytest.raises(GateError, match="on 'HEAD', expected 'main'"):
        checkout_is_clean_on(checkout, "main")


def test_restore_checkout_returns_to_base_when_clean(checkout: Path, caplog) -> None:
    _git(checkout, "checkout", "-q", "-b", "tedsbot/APP-1")
    (checkout / "fix.txt").write_text("fixed\n")
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-q", "-m", "fix")

    with caplog.at_level(logging.ERROR, logger="tedsbot.gates"):
        assert restore_checkout(checkout, "main") is None

    head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "--abbrev-ref", "HEAD"],
                          capture_output=True, text=True, check=True)
    assert head.stdout.strip() == "main"
    # The fixture checkout has no origin, so the fast-forward pull fails; a
    # restore reports that through the log instead of raising.
    assert any("pull --ff-only" in record.getMessage() for record in caplog.records)


def test_restore_checkout_leaves_dirty_tree_alone(checkout: Path) -> None:
    _git(checkout, "checkout", "-q", "-b", "tedsbot/APP-1")
    (checkout / "scratch.txt").write_text("x")

    note = restore_checkout(checkout, "main")

    assert note == "checkout left on 'tedsbot/APP-1' with uncommitted changes"
    head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "--abbrev-ref", "HEAD"],
                          capture_output=True, text=True, check=True)
    assert head.stdout.strip() == "tedsbot/APP-1"
    assert (checkout / "scratch.txt").exists()
