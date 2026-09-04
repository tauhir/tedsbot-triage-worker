# ABOUTME: Jira ticketing provider: MCP server config, prompt facts, provider
# ABOUTME: knowledge, and the deterministic ticket queries/mutations.
from __future__ import annotations

from tedsbot.config import TicketsConfig
from tedsbot.providers.base import McpServer, TicketRef
from tedsbot.registry import register


class JiraTicketing:
    def __init__(self, cfg: TicketsConfig) -> None:
        self.cfg = cfg

    def mcp_server(self) -> McpServer:
        raise NotImplementedError

    def prompt_facts(self) -> dict[str, str]:
        raise NotImplementedError

    def knowledge(self) -> str:
        raise NotImplementedError

    def untriaged_bugs(self, bot_marker: str) -> list[TicketRef]:
        raise NotImplementedError

    def approved_for_fix(self) -> list[TicketRef]:
        raise NotImplementedError

    def status_of(self, key: str) -> str:
        raise NotImplementedError

    def search_text(self, text: str) -> list[TicketRef]:
        raise NotImplementedError

    def comment(self, key: str, body: str) -> None:
        raise NotImplementedError

    def statuses_exist(self, names: list[str]) -> list[str]:
        raise NotImplementedError


register("tickets", "jira", JiraTicketing)
