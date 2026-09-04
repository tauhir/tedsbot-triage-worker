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
    assert "/run/summary.json" in text
    assert "example-org" in text and "Dev Team Review" in text and "sentry-triage" in text
    assert "NEVER modify repository code" in text
    assert '"kind": "triage_sentry"' in text


def test_triage_ticket_substitutes() -> None:
    text = render_prompt("triage_ticket", FACTS, ticket_key="APP-2", summary_path="/run/summary.json")
    assert "TICKET_KEY: APP-2" in text
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
