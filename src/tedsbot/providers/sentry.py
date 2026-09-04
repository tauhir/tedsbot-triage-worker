# ABOUTME: Sentry error-source provider: MCP server config, prompt facts,
# ABOUTME: provider knowledge, and the deterministic poll passes.
from __future__ import annotations

from tedsbot.config import ErrorsConfig
from tedsbot.providers.base import ErrorCandidate, McpServer, Ticketing
from tedsbot.registry import register


class SentryErrorSource:
    def __init__(self, cfg: ErrorsConfig) -> None:
        self.cfg = cfg

    def mcp_server(self) -> McpServer:
        raise NotImplementedError

    def prompt_facts(self) -> dict[str, str]:
        raise NotImplementedError

    def knowledge(self) -> str:
        raise NotImplementedError

    def poll(self) -> list[ErrorCandidate]:
        raise NotImplementedError

    def already_ticketed(self, short_id: str, tickets: Ticketing) -> bool:
        raise NotImplementedError


register("errors", "sentry", SentryErrorSource)
