# ABOUTME: Slack incoming-webhook notifier: posts run summaries from Python and
# ABOUTME: exposes an in-process SDK tool so the agent can post mid-run.
from __future__ import annotations

from typing import Any

import httpx
from claude_agent_sdk import create_sdk_mcp_server, tool

from tedsbot import __version__
from tedsbot.config import NotifyConfig
from tedsbot.errors import ProviderError
from tedsbot.providers.base import McpServer
from tedsbot.registry import register


class SlackWebhookNotifier:
    def __init__(self, cfg: NotifyConfig) -> None:
        self.cfg = cfg
        notifier = self

        @tool("notify_slack", "Post a short status line to the team's Slack channel.", {"text": str})
        async def notify_slack(args: dict[str, Any]) -> dict[str, Any]:
            try:
                notifier.post(str(args["text"]))
            except ProviderError as exc:
                return {"content": [{"type": "text", "text": f"slack post failed: {exc}"}], "is_error": True}
            return {"content": [{"type": "text", "text": "posted"}]}

        self.notify_tool = notify_slack

    def post(self, text: str) -> None:
        resp = httpx.post(self.cfg.url, json={"text": text}, timeout=15)
        if resp.status_code // 100 != 2:
            raise ProviderError(f"slack webhook {resp.status_code}: {resp.text[:200]}")

    def sdk_server(self) -> McpServer:
        server = create_sdk_mcp_server(name="notify", version=__version__, tools=[self.notify_tool])
        return McpServer(name="notify", config=server, allowed_tools=["mcp__notify__notify_slack"])


register("notify", "slack_webhook", SlackWebhookNotifier)
