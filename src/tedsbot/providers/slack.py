# ABOUTME: Slack webhook notifier: posts triage updates and exposes an SDK
# ABOUTME: MCP server for the agent to notify directly.
from __future__ import annotations

from tedsbot.config import NotifyConfig
from tedsbot.providers.base import McpServer
from tedsbot.registry import register


class SlackWebhookNotifier:
    def __init__(self, cfg: NotifyConfig) -> None:
        self.cfg = cfg

    def post(self, text: str) -> None:
        raise NotImplementedError

    def sdk_server(self) -> McpServer:
        raise NotImplementedError


register("notify", "slack_webhook", SlackWebhookNotifier)
