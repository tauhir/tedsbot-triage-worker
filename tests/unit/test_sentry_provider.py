# ABOUTME: Unit tests for the Sentry provider: MCP config, prompt facts,
# ABOUTME: pass construction, dedupe/cap logic, and HTTP via respx.
import httpx
import respx

from tedsbot.config import ErrorsConfig, PassConfig, PollConfig
from tedsbot.providers.base import TicketRef
from tedsbot.providers.sentry import SentryErrorSource, build_passes


def _cfg(**poll: object) -> ErrorsConfig:
    return ErrorsConfig(
        kind="sentry", org="example-org", project_id="123", token="tok",
        environment="production", poll=PollConfig(**poll),
    )


def test_mcp_server_uses_npx_and_org() -> None:
    server = SentryErrorSource(_cfg()).mcp_server()
    assert server.name == "sentry"
    assert server.config["command"] == "npx"
    assert "--organization-slug=example-org" in server.config["args"]
    assert server.config["env"]["SENTRY_ACCESS_TOKEN"] == "tok"
    assert server.allowed_tools == ["mcp__sentry__*"]


def test_prompt_facts() -> None:
    facts = SentryErrorSource(_cfg()).prompt_facts()
    assert facts["sentry_org"] == "example-org"
    assert facts["sentry_region_url"] == "https://us.sentry.io"
    assert facts["sentry_environment"] == "production"


def test_knowledge_is_shipped_markdown() -> None:
    text = SentryErrorSource(_cfg()).knowledge()
    assert text.startswith("## Sentry")
    assert "organization slug" in text


def test_build_passes_default_order_and_queries() -> None:
    passes = build_passes(PollConfig())
    labels = [p.label for p in passes]
    assert labels == ["new-error", "escalating", "performance", "chronic"]
    new = passes[0]
    assert "firstSeen:-30m" in new.query and "timesSeen:>=3" in new.query
    assert "level:[error,fatal]" in new.query and new.env_mode == "param"
    perf = passes[2]
    assert "issue.category:[db_query,http_client,frontend,mobile,metric]" in perf.query
    assert perf.env_mode == "check" and "timesSeen:>=10" in perf.query


def test_build_passes_omits_disabled_new_error() -> None:
    passes = build_passes(PollConfig(new_error=PassConfig(enabled=False)))
    assert "new-error" not in [p.label for p in passes]


def test_build_passes_respects_enabled_flags() -> None:
    passes = build_passes(PollConfig(escalating=PassConfig(enabled=False), chronic=PassConfig(enabled=False)))
    assert [p.label for p in passes] == ["new-error", "performance"]


@respx.mock
def test_fetch_issues_scopes_environment_for_param_passes() -> None:
    route = respx.get("https://us.sentry.io/api/0/organizations/example-org/issues/").mock(
        return_value=httpx.Response(200, json=[{"id": "1", "shortId": "APP-1", "title": "boom", "permalink": "https://s/1"}])
    )
    src = SentryErrorSource(_cfg())
    issues = src.fetch_issues(build_passes(PollConfig())[0])
    assert issues[0]["shortId"] == "APP-1"
    assert route.calls[0].request.url.params["environment"] == "production"
    assert route.calls[0].request.headers["Authorization"] == "Bearer tok"


@respx.mock
def test_issue_is_production_fails_closed() -> None:
    respx.get("https://us.sentry.io/api/0/organizations/example-org/issues/9/tags/environment/").mock(
        return_value=httpx.Response(500)
    )
    assert SentryErrorSource(_cfg()).issue_is_production({"id": "9"}) is False


@respx.mock
def test_issue_is_production_fails_closed_on_transport_error() -> None:
    respx.get("https://us.sentry.io/api/0/organizations/example-org/issues/9/tags/environment/").mock(
        side_effect=httpx.ConnectError("boom")
    )
    assert SentryErrorSource(_cfg()).issue_is_production({"id": "9"}) is False


@respx.mock
def test_issue_is_production_fails_closed_on_bad_json() -> None:
    respx.get("https://us.sentry.io/api/0/organizations/example-org/issues/9/tags/environment/").mock(
        return_value=httpx.Response(200, text="not json")
    )
    assert SentryErrorSource(_cfg()).issue_is_production({"id": "9"}) is False


@respx.mock
def test_poll_dedupes_across_passes_and_caps() -> None:
    def _issues(request: httpx.Request) -> httpx.Response:
        q = request.url.params["query"]
        if "firstSeen" in q:
            body = [{"id": "1", "shortId": "APP-1", "title": "a", "permalink": "u1"}]
        elif "escalating" in q:
            body = [{"id": "1", "shortId": "APP-1", "title": "a", "permalink": "u1"},
                    {"id": "2", "shortId": "APP-2", "title": "b", "permalink": "u2"}]
        else:
            body = [{"id": "3", "shortId": "APP-3", "title": "c", "permalink": "u3"}]
        return httpx.Response(200, json=body)

    respx.get("https://us.sentry.io/api/0/organizations/example-org/issues/").mock(side_effect=_issues)
    respx.get(url__regex=r".*/tags/environment/$").mock(
        return_value=httpx.Response(200, json={"topValues": [{"value": "production"}]})
    )
    src = SentryErrorSource(_cfg(max_issues_per_cycle=2))
    out = src.poll()
    assert [c.short_id for c in out] == ["APP-1", "APP-2"]
    assert out[0].pass_label == "new-error"


@respx.mock
def test_poll_performance_pass_filters_by_environment() -> None:
    def _issues(request: httpx.Request) -> httpx.Response:
        q = request.url.params["query"]
        if "issue.category" in q:
            body = [
                {"id": "7", "shortId": "APP-7", "title": "slow", "permalink": "u7"},
                {"id": "8", "shortId": "APP-8", "title": "slow2", "permalink": "u8"},
            ]
        else:
            body = []
        return httpx.Response(200, json=body)

    def _tags(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/issues/7/tags/environment/"):
            return httpx.Response(200, json={"topValues": [{"value": "production"}]})
        return httpx.Response(200, json={"topValues": [{"value": "staging"}]})

    respx.get("https://us.sentry.io/api/0/organizations/example-org/issues/").mock(side_effect=_issues)
    respx.get(url__regex=r".*/tags/environment/$").mock(side_effect=_tags)

    src = SentryErrorSource(_cfg(max_issues_per_cycle=10))
    out = src.poll()
    assert [c.short_id for c in out] == ["APP-7"]
    assert out[0].pass_label == "performance"


def test_already_ticketed_uses_ticket_search() -> None:
    class FakeTickets:
        def search_text(self, text: str) -> list[TicketRef]:
            return [TicketRef(key="APP-9", url="u", status="Open", summary="x")] if text == "APP-1" else []

    src = SentryErrorSource(_cfg())
    assert src.already_ticketed("APP-1", FakeTickets()) is True
    assert src.already_ticketed("APP-2", FakeTickets()) is False
