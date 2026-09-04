# ABOUTME: Real end-to-end triage run against a sandbox ticketing project.
# ABOUTME: Spends credits; runs only with TEDSBOT_E2E=1 and TEDSBOT_E2E_CONFIG set.
import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


def _required_env(name: str) -> str:
    """Skip rather than error when a run-specific variable is absent."""
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} not set")
    return value


def _runs_dir() -> Path:
    return Path.home() / ".tedsbot" / "runs"


def _snapshot() -> set[Path]:
    runs = _runs_dir()
    return set(runs.iterdir()) if runs.is_dir() else set()


# Diffing against a pre-launch snapshot (rather than taking the newest entry)
# keeps each test scoped to the run dir it launched, since under -n auto the
# two e2e tests can run concurrently and new_run_dir() creates the directory
# at run start, before the summary is written. This assumes the two e2e
# tests never launch the same kind against the same target concurrently --
# they don't, since they use different subcommands (sentry vs ticket).
def _new_run_dir(before: set[Path]) -> Path:
    new = set(_runs_dir().iterdir()) - before
    assert len(new) == 1, f"expected exactly one new run dir, found {sorted(new)}"
    return new.pop()


def test_triage_sentry_lands_ticket_and_summary() -> None:
    config = _required_env("TEDSBOT_E2E_CONFIG")
    issue = _required_env("TEDSBOT_E2E_SENTRY_ISSUE")
    before = _snapshot()
    proc = subprocess.run(["uv", "run", "tedsbot", "-c", config, "triage", "sentry", issue],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    run_dir = _new_run_dir(before)
    summary = json.loads((run_dir / "summary.resolved.json").read_text())
    assert summary["ok"] is True
    assert summary["recommendation"] in ("🟢", "🟡", "⚪", "🔴")
    assert summary["ticket"] and summary["ticket_url"]


def test_triage_ticket_comments_and_summary() -> None:
    config = _required_env("TEDSBOT_E2E_CONFIG")
    key = _required_env("TEDSBOT_E2E_TICKET")
    before = _snapshot()
    proc = subprocess.run(["uv", "run", "tedsbot", "-c", config, "triage", "ticket", key],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    run_dir = _new_run_dir(before)
    summary = json.loads((run_dir / "summary.resolved.json").read_text())
    assert summary["ok"] is True and summary["ticket"] == key
