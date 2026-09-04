# ABOUTME: Unit tests for the Jira provider: MCP config, prompt facts, JQL
# ABOUTME: construction, and REST operations via respx.
import httpx
import pytest
import respx

from tedsbot.config import TicketFields, TicketLabels, TicketsConfig, TicketStatuses
from tedsbot.errors import ProviderError
from tedsbot.providers.jira import JiraTicketing

BASE = "https://example.atlassian.net/rest/api/3"


def _cfg() -> TicketsConfig:
    return TicketsConfig(
        kind="jira", url="https://example.atlassian.net", cloud_id="cid", project="APP",
        token="tok", bug_issue_type_id="10009",
        fields=TicketFields(qa_notes="customfield_10075", qa_instructions="customfield_10073"),
        statuses=TicketStatuses(intake="To Triage", triage_target="Dev Team Review",
                                fix_approved="Approved For Fix", in_progress="In Progress",
                                code_review="Code Review"),
        labels=TicketLabels(),
    )


def _issue(key: str, status: str, comments: list[str] | None = None) -> dict:
    return {
        "key": key,
        "fields": {
            "summary": f"summary {key}",
            "status": {"name": status},
            "comment": {"comments": [{"body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": c}]}]}} for c in (comments or [])]},
        },
    }


def test_mcp_server_uses_uvx_mcp_atlassian() -> None:
    server = JiraTicketing(_cfg()).mcp_server()
    assert server.name == "atlassian"
    assert server.config["command"] == "uvx" and server.config["args"] == ["mcp-atlassian"]
    env = server.config["env"]
    assert env["JIRA_URL"] == "https://example.atlassian.net"
    assert env["ATLASSIAN_OAUTH_CLOUD_ID"] == "cid"
    assert env["ATLASSIAN_OAUTH_ACCESS_TOKEN"] == "tok"
    assert server.allowed_tools == ["mcp__atlassian__*"]


def test_prompt_facts_cover_ids_statuses_labels() -> None:
    facts = JiraTicketing(_cfg()).prompt_facts()
    assert facts["jira_url"] == "https://example.atlassian.net"
    assert facts["jira_project"] == "APP"
    assert facts["jira_cloud_id"] == "cid"
    assert facts["bug_issue_type_id"] == "10009"
    assert facts["qa_notes_field"] == "customfield_10075"
    assert facts["qa_instructions_field"] == "customfield_10073"
    assert facts["status_triage_target"] == "Dev Team Review"
    assert facts["status_code_review"] == "Code Review"
    assert facts["label_from_errors"] == "sentry-triage"
    assert facts["label_insufficient_repro"] == "insufficient-repro"


def test_knowledge_mentions_adf_and_transitions() -> None:
    text = JiraTicketing(_cfg()).knowledge()
    assert "Atlassian Document Format" in text and "transitions" in text


@respx.mock
def test_untriaged_bugs_filters_by_bot_marker() -> None:
    route = respx.get(f"{BASE}/search/jql").mock(return_value=httpx.Response(200, json={
        "issues": [_issue("APP-1", "To Triage"), _issue("APP-2", "To Triage", ["[tedsbot] analysis"])]
    }))
    out = JiraTicketing(_cfg()).untriaged_bugs("[tedsbot]")
    assert [t.key for t in out] == ["APP-1"]
    assert out[0].url == "https://example.atlassian.net/browse/APP-1"
    jql = route.calls[0].request.url.params["jql"]
    assert "issuetype = Bug" in jql
    assert 'status = "To Triage"' in jql


@respx.mock
def test_approved_for_fix_jql() -> None:
    route = respx.get(f"{BASE}/search/jql").mock(return_value=httpx.Response(200, json={"issues": [_issue("APP-5", "Approved For Fix")]}))
    out = JiraTicketing(_cfg()).approved_for_fix()
    assert out[0].key == "APP-5"
    assert 'status = "Approved For Fix"' in route.calls[0].request.url.params["jql"]


@respx.mock
def test_status_of() -> None:
    respx.get(f"{BASE}/issue/APP-3").mock(return_value=httpx.Response(200, json=_issue("APP-3", "Done")))
    assert JiraTicketing(_cfg()).status_of("APP-3") == "Done"


@respx.mock
def test_search_text_escapes_quotes() -> None:
    route = respx.get(f"{BASE}/search/jql").mock(return_value=httpx.Response(200, json={"issues": []}))
    JiraTicketing(_cfg()).search_text('APP-1 "quoted"')
    assert 'text ~ "APP-1 \\"quoted\\""' in route.calls[0].request.url.params["jql"]


@respx.mock
def test_comment_posts_adf() -> None:
    route = respx.post(f"{BASE}/issue/APP-1/comment").mock(return_value=httpx.Response(201, json={}))
    JiraTicketing(_cfg()).comment("APP-1", "hello\nworld")
    body = route.calls[0].request.content
    assert b'"type":"doc"' in body and b"hello" in body and b"world" in body


@respx.mock
def test_statuses_exist_reports_missing() -> None:
    respx.get(f"{BASE}/project/APP/statuses").mock(return_value=httpx.Response(200, json=[
        {"name": "Bug", "statuses": [{"name": "To Triage"}, {"name": "Done"}]}
    ]))
    missing = JiraTicketing(_cfg()).statuses_exist(["To Triage", "Dev Team Review"])
    assert missing == ["Dev Team Review"]


@respx.mock
def test_search_follows_next_page_token() -> None:
    def _responder(request: httpx.Request) -> httpx.Response:
        if "nextPageToken" not in request.url.params:
            return httpx.Response(200, json={
                "issues": [_issue("APP-1", "Approved For Fix")],
                "nextPageToken": "t2",
                "isLast": False,
            })
        assert request.url.params["nextPageToken"] == "t2"
        return httpx.Response(200, json={"issues": [_issue("APP-2", "Approved For Fix")], "isLast": True})

    route = respx.get(f"{BASE}/search/jql").mock(side_effect=_responder)
    out = JiraTicketing(_cfg()).approved_for_fix()
    assert [t.key for t in out] == ["APP-1", "APP-2"]
    assert route.call_count == 2


@respx.mock
def test_comment_rejects_empty_body() -> None:
    route = respx.post(f"{BASE}/issue/APP-1/comment").mock(return_value=httpx.Response(201, json={}))
    with pytest.raises(ProviderError, match="empty"):
        JiraTicketing(_cfg()).comment("APP-1", "   \n   ")
    assert route.called is False
