# ABOUTME: Integration tests for Jira REST operations against recorded cassettes.
# ABOUTME: Re-record with JIRA_URL, ATLASSIAN_API_TOKEN, JIRA_PROJECT set and VCR_RECORD_MODE=once.
import os
from pathlib import Path

import pytest
import vcr

from tedsbot.config import TicketFields, TicketsConfig, TicketStatuses
from tedsbot.providers.jira import JiraTicketing

CASSETTES = Path(__file__).parent / "cassettes"
def _drop_cookies(response: dict) -> dict:
    """Session cookies are not needed for replay and must never be committed."""
    response["headers"].pop("set-cookie", None)
    response["headers"].pop("Set-Cookie", None)
    return response


recorder = vcr.VCR(
    cassette_library_dir=str(CASSETTES),
    filter_headers=["authorization"],
    before_record_response=_drop_cookies,
    decode_compressed_response=True,
    record_mode=os.environ.get("VCR_RECORD_MODE", "none"),
)


def _cfg() -> TicketsConfig:
    return TicketsConfig(
        kind="jira",
        url=os.environ.get("JIRA_URL", "https://example.atlassian.net"),
        cloud_id=os.environ.get("ATLASSIAN_CLOUD_ID", "cid"),
        project=os.environ.get("JIRA_PROJECT", "APP"),
        token=os.environ.get("ATLASSIAN_API_TOKEN", "recorded"),
        bug_issue_type_id="10009",
        fields=TicketFields(qa_notes="customfield_10075", qa_instructions="customfield_10073"),
        statuses=TicketStatuses(intake="To Triage", triage_target="Dev Team Review",
                                fix_approved="Approved For Fix", in_progress="In Progress",
                                code_review="Code Review"),
    )

def _replay_only() -> bool:
    """True unless VCR_RECORD_MODE asks to record; the skip guard only applies on replay."""
    return os.environ.get("VCR_RECORD_MODE", "none") == "none"


@recorder.use_cassette("jira_statuses.yaml")
def test_statuses_exist_finds_configured_statuses() -> None:
    if _replay_only() and not (CASSETTES / "jira_statuses.yaml").exists():
        pytest.skip("cassette not recorded; see module docstring")
    tickets = JiraTicketing(_cfg())
    try:
        missing = tickets.statuses_exist(["To Triage", "Definitely Not A Status"])
    finally:
        tickets.close()
    assert missing == ["Definitely Not A Status"]


@recorder.use_cassette("jira_search.yaml")
def test_search_text_returns_refs() -> None:
    if _replay_only() and not (CASSETTES / "jira_search.yaml").exists():
        pytest.skip("cassette not recorded; see module docstring")
    tickets = JiraTicketing(_cfg())
    try:
        out = tickets.search_text("triage")
    finally:
        tickets.close()
    assert all(t.key and t.url.endswith(t.key) for t in out)
