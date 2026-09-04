# ABOUTME: Real end-to-end triage run against a sandbox ticketing project.
# ABOUTME: Spends credits; runs only with TEDSBOT_E2E=1 and TEDSBOT_E2E_CONFIG set.
import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


def _latest_run_dir() -> Path:
    runs = Path.home() / ".tedsbot" / "runs"
    return max(runs.iterdir())


def test_triage_sentry_lands_ticket_and_summary() -> None:
    config = os.environ["TEDSBOT_E2E_CONFIG"]
    issue = os.environ["TEDSBOT_E2E_SENTRY_ISSUE"]
    proc = subprocess.run(["uv", "run", "tedsbot", "-c", config, "triage", "sentry", issue],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    summary = json.loads((_latest_run_dir() / "summary.resolved.json").read_text())
    assert summary["ok"] is True
    assert summary["recommendation"] in ("🟢", "🟡", "⚪", "🔴")
    assert summary["ticket"] and summary["ticket_url"]


def test_triage_ticket_comments_and_summary() -> None:
    config = os.environ["TEDSBOT_E2E_CONFIG"]
    key = os.environ["TEDSBOT_E2E_TICKET"]
    proc = subprocess.run(["uv", "run", "tedsbot", "-c", config, "triage", "ticket", key],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    summary = json.loads((_latest_run_dir() / "summary.resolved.json").read_text())
    assert summary["ok"] is True and summary["ticket"] == key
