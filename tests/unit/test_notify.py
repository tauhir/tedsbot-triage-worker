# ABOUTME: Tests the Slack webhook notifier: post payload, failure handling,
# ABOUTME: and the in-process SDK tool it exposes to the agent.
import httpx
import pytest
import respx

from tedsbot.config import NotifyConfig
from tedsbot.errors import ProviderError
from tedsbot.providers.slack import SlackWebhookNotifier

URL = "https://hooks.slack.example/T/B/X"


@respx.mock
def test_post_sends_text_json() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, text="ok"))
    SlackWebhookNotifier(NotifyConfig(kind="slack_webhook", url=URL)).post("🟢 APP-1 — fixed")
    assert route.calls[0].request.headers["content-type"] == "application/json"
    assert b"APP-1" in route.calls[0].request.content


@respx.mock
def test_post_raises_on_failure() -> None:
    respx.post(URL).mock(return_value=httpx.Response(500, text="no"))
    with pytest.raises(ProviderError, match="500"):
        SlackWebhookNotifier(NotifyConfig(kind="slack_webhook", url=URL)).post("x")


def test_sdk_server_exposes_notify_tool() -> None:
    server = SlackWebhookNotifier(NotifyConfig(kind="slack_webhook", url=URL)).sdk_server()
    assert server.name == "notify"
    assert server.allowed_tools == ["mcp__notify__notify_slack"]
    assert server.config["type"] == "sdk"


@respx.mock
async def test_sdk_tool_posts_and_returns_text() -> None:
    respx.post(URL).mock(return_value=httpx.Response(200, text="ok"))
    notifier = SlackWebhookNotifier(NotifyConfig(kind="slack_webhook", url=URL))
    result = await notifier.notify_tool.handler({"text": "hello"})
    assert result["content"][0]["text"] == "posted"
