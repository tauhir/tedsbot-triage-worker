# ABOUTME: Tests prompt rendering: required facts are substituted, missing
# ABOUTME: facts fail loudly, and each template carries its hard rules.
import pytest
from jinja2 import UndefinedError

from tedsbot.prompts import render_prompt

FACTS = {
    "sentry_org": "example-org", "sentry_region_url": "https://us.sentry.io",
    "sentry_environment": "production", "sentry_project_id": "123",
    "jira_url": "https://example.atlassian.net", "jira_project": "APP", "jira_cloud_id": "cid",
    "bug_issue_type_id": "10009", "qa_notes_field": "customfield_10075",
    "qa_instructions_field": "customfield_10073", "status_intake": "To Triage",
    "status_triage_target": "Dev Team Review", "status_fix_approved": "Approved For Fix",
    "status_in_progress": "In Progress", "status_code_review": "Code Review",
    "label_from_errors": "sentry-triage", "label_insufficient_repro": "insufficient-repro",
}


def test_triage_sentry_substitutes_facts_and_inputs() -> None:
    text = render_prompt("triage_sentry", FACTS, sentry_issue="APP-1", summary_path="/run/summary.json")
    assert "SENTRY_ISSUE: APP-1" in text
    assert "submit_summary" in text and "/run/summary.json" not in text
    assert "tldr" in text and "non-engineers" in text
    assert "outcome" in text and "first_seen" in text and "em-dash" in text
    assert "Plain sentences everywhere you write" in text
    assert "example-org" in text and "Dev Team Review" in text and "sentry-triage" in text
    assert "NEVER modify repository code" in text
    assert '"kind": "triage_sentry"' in text


def test_triage_ticket_substitutes() -> None:
    text = render_prompt("triage_ticket", FACTS, ticket_key="APP-2", summary_path="/run/summary.json")
    assert "TICKET_KEY: APP-2" in text
    assert "tldr" in text and "non-engineers" in text
    assert "outcome" in text and "first_seen" in text and "em-dash" in text
    assert "Plain sentences everywhere you write" in text
    assert "insufficient-repro" in text and "customfield_10075" in text


def test_triage_ticket_carries_hard_rules() -> None:
    text = render_prompt("triage_ticket", FACTS, ticket_key="APP-2", summary_path="/run/summary.json")
    assert "NEVER modify repository code" in text
    assert "[tedsbot] " in text
    assert "followed by the recommendation tier on the same line" in text
    assert "Never move a ticket backwards" in text
    assert '"kind": "triage_ticket"' in text


def test_missing_fact_fails_loudly() -> None:
    facts = dict(FACTS)
    del facts["jira_project"]
    with pytest.raises(UndefinedError):
        render_prompt("triage_sentry", facts, sentry_issue="x", summary_path="y")


def test_unknown_template_fails() -> None:
    with pytest.raises(FileNotFoundError):
        render_prompt("nope", FACTS)


def test_fix_prompt_substitutes_and_carries_rules() -> None:
    text = render_prompt("fix", FACTS, ticket_key="APP-7", branch="tedsbot/APP-7", base_branch="main",
                         github_repo="example-org/example-app", test_command="uv run pytest -q", summary_path="/x")
    assert "TICKET_KEY: APP-7" in text and "BRANCH: tedsbot/APP-7" in text and "example-org/example-app" in text
    assert "uv run pytest -q" in text and "customfield_10073" in text and "Code Review" in text
    assert "Draft only" in text and "never merge" in text and "submit_summary" in text
    assert '"status": "draft PR opened"' in text and "no em-dashes" in text
    assert "gh pr list --repo example-org/example-app --head tedsbot/APP-7" in text
    assert "record the summary with status `already open`" in text


def test_fix_prompt_without_test_command_says_tests_cannot_run() -> None:
    text = render_prompt("fix", FACTS, ticket_key="APP-7", branch="b", base_branch="main",
                         github_repo="o/r", test_command="none", summary_path="/x")
    assert "cannot run the tests" in text
    assert "\n\n7. **Commit**" not in text
