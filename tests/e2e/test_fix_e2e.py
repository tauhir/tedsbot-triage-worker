# ABOUTME: Real end-to-end fix run against a sandbox ticket describing a planted bug.
# ABOUTME: Spends credits; runs only with TEDSBOT_E2E=1 and the fix-specific env vars set.
"""End-to-end fix run.

To exercise this test, stage a fixture:

1. Clone this repository on `main` somewhere the worker can write to (its
   own checkout, not one you also use for anything else): the fix gate
   refuses to start on a checkout with uncommitted changes or that is off
   the base branch, and a run leaves branches and commits behind.
2. Point a config's `repo.path` at that clone and `repo.github` at
   `tauhir/tedsbot-triage-worker` (or a fork you control).
3. Create a sandbox ticket in the project's configured `fix_approved`
   status, describing a small, real, planted bug in that clone (something
   the agent can locate, fix, and cover with a test in a few minutes).
4. Set the environment variables below and run with TEDSBOT_E2E=1.

Environment variables:
- TEDSBOT_E2E_FIX_CONFIG: path to the config file described above.
- TEDSBOT_E2E_FIX_TICKET: the sandbox ticket's key.

The test cleans up after itself: it closes the PR the run opens and deletes
its branch. It does not revert the ticket's status or comments.
"""
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
# e2e tests can run concurrently and new_run_dir() creates the directory at
# run start, before the summary is written. Filtering the diff by kind and
# target makes that scoping explicit rather than relying on which other e2e
# tests happen to exist.
def _new_run_dir(before: set[Path], key: str) -> Path:
    new = {d for d in set(_runs_dir().iterdir()) - before if d.name.endswith(f"-fix-{key}")}
    assert len(new) == 1, f"expected exactly one new fix run dir for {key}, found {sorted(new)}"
    return new.pop()


def test_fix_opens_draft_pr_and_summary() -> None:
    config = _required_env("TEDSBOT_E2E_FIX_CONFIG")
    key = _required_env("TEDSBOT_E2E_FIX_TICKET")
    before = _snapshot()
    proc = subprocess.run(["uv", "run", "tedsbot", "-c", config, "fix", key],
                          capture_output=True, text=True, check=False)
    pr_url = None
    try:
        assert proc.returncode == 0, proc.stdout + proc.stderr
        run_dir = _new_run_dir(before, key)
        summary = json.loads((run_dir / "summary.resolved.json").read_text())
        assert summary["status"] in ("draft PR opened", "CI green", "CI red, handed back")
        pr_url = summary.get("pr_url")
        assert pr_url, f"no pr_url in summary: {summary}"
    finally:
        if pr_url:
            cleanup = subprocess.run(
                ["gh", "pr", "close", pr_url, "--delete-branch", "--comment", "tedsbot e2e run, closing"],
                capture_output=True, text=True, check=False,
            )
            print(cleanup.stdout + cleanup.stderr)
