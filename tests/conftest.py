# ABOUTME: Shared pytest fixtures for the tedsbot test suite.
# ABOUTME: Provides a temporary HOME and a minimal valid config dict.
import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def temp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    repo = tmp_path / "checkout"
    repo.mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "init", "-q", "-b", "main"],
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("fixture\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        [
            "git", "-C", str(repo),
            "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-q", "-m", "init",
        ],
        check=True,
        capture_output=True,
    )
    return repo


@pytest.fixture
def config_dict(checkout: Path) -> dict:
    return {
        "repo": {"path": str(checkout), "base_branch": "main", "github": "example-org/example-app"},
        "errors": {
            "kind": "sentry",
            "org": "example-org",
            "project_id": "123",
            "region_url": "https://us.sentry.io",
            "environment": "production",
            "token": "${SENTRY_AUTH_TOKEN}",
        },
        "tickets": {
            "kind": "jira",
            "url": "https://example.atlassian.net",
            "cloud_id": "00000000-0000-0000-0000-000000000000",
            "project": "APP",
            "token": "${ATLASSIAN_API_TOKEN}",
            "bug_issue_type_id": "10009",
            "fields": {"qa_notes": "customfield_10075", "qa_instructions": "customfield_10073"},
            "statuses": {
                "intake": "To Triage",
                "triage_target": "Dev Team Review",
                "fix_approved": "Approved For Fix",
                "in_progress": "In Progress",
                "code_review": "Code Review",
            },
            "labels": {"from_errors": "sentry-triage", "insufficient_repro": "insufficient-repro"},
        },
        "notify": {"kind": "slack_webhook", "url": "${SLACK_WEBHOOK_URL}"},
        "agent": {"model": "claude-opus-5", "max_turns": {"triage": 60, "fix": 150}},
    }


@pytest.fixture
def env_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTRY_AUTH_TOKEN", "sentry-token")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "atlassian-token")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/T/B/X")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("TEDSBOT_E2E") == "1":
        return
    skip = pytest.mark.skip(reason="set TEDSBOT_E2E=1 with real credentials to run")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip)
