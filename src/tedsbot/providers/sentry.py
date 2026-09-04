# ABOUTME: Sentry error-source provider: MCP server config, prompt facts,
# ABOUTME: provider knowledge, and the deterministic poll passes.
from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import resources
from typing import Literal

import httpx

from tedsbot.config import ErrorsConfig, PollConfig
from tedsbot.errors import ProviderError
from tedsbot.providers.base import ErrorCandidate, McpServer, Ticketing
from tedsbot.registry import register

log = logging.getLogger(__name__)

PERF_CATEGORIES = "db_query,http_client,frontend,mobile,metric"
FETCH_LIMIT = 25


@dataclass(frozen=True)
class SentryPass:
    label: str
    query: str
    sort: str
    env_mode: Literal["param", "check"]


def build_passes(poll: PollConfig) -> list[SentryPass]:
    levels = ",".join(poll.levels)
    out = [
        SentryPass(
            "new-error",
            f"is:unresolved firstSeen:{poll.new_error.first_seen} "
            f"timesSeen:>={poll.new_error.min_times_seen} level:[{levels}]",
            "new",
            "param",
        )
    ]
    if poll.escalating.enabled:
        out.append(SentryPass(
            "escalating",
            f"is:unresolved is:escalating timesSeen:>={poll.escalating.min_times_seen} level:[{levels}]",
            "freq",
            "param",
        ))
    if poll.performance.enabled:
        out.append(SentryPass(
            "performance",
            f"is:unresolved issue.category:[{PERF_CATEGORIES}] timesSeen:>={poll.performance.min_times_seen}",
            "freq",
            "check",
        ))
    if poll.chronic.enabled:
        out.append(SentryPass(
            "chronic",
            f"is:unresolved timesSeen:>={poll.chronic.min_times_seen} level:[{levels}]",
            "freq",
            "param",
        ))
    return out


class SentryErrorSource:
    def __init__(self, cfg: ErrorsConfig) -> None:
        self.cfg = cfg
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {cfg.token}", "Accept": "application/json"},
            timeout=30,
        )

    def mcp_server(self) -> McpServer:
        return McpServer(
            name="sentry",
            config={
                "command": "npx",
                "args": ["-y", "@sentry/mcp-server@latest", f"--organization-slug={self.cfg.org}"],
                "env": {"SENTRY_ACCESS_TOKEN": self.cfg.token},
            },
            allowed_tools=["mcp__sentry__*"],
        )

    def prompt_facts(self) -> dict[str, str]:
        return {
            "sentry_org": self.cfg.org,
            "sentry_region_url": self.cfg.region_url,
            "sentry_environment": self.cfg.environment,
            "sentry_project_id": self.cfg.project_id,
        }

    def knowledge(self) -> str:
        return resources.files("tedsbot.providers.knowledge").joinpath("sentry.md").read_text()

    def check_auth(self) -> tuple[bool, str]:
        url = self._org_url("")
        try:
            resp = self._client.get(url)
        except httpx.HTTPError as exc:
            return False, f"{url} unreachable: {exc}"
        if resp.status_code == 200:
            return True, url
        return False, f"{url} -> {resp.status_code}"

    def _org_url(self, tail: str) -> str:
        return f"{self.cfg.region_url}/api/0/organizations/{self.cfg.org}/{tail}"

    def fetch_issues(self, sentry_pass: SentryPass) -> list[dict]:
        params: dict[str, str] = {
            "project": self.cfg.project_id,
            "query": sentry_pass.query,
            "sort": sentry_pass.sort,
            "statsPeriod": self.cfg.poll.stats_period,
            "limit": str(FETCH_LIMIT),
        }
        if sentry_pass.env_mode == "param":
            params["environment"] = self.cfg.environment
        resp = self._client.get(self._org_url("issues/"), params=params)
        if resp.status_code != 200:
            raise ProviderError(f"sentry issues search {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        if not isinstance(data, list):
            raise ProviderError(f"unexpected Sentry response: {str(data)[:200]}")
        return data

    def issue_is_production(self, issue: dict) -> bool:
        issue_id = issue.get("id")
        if not issue_id:
            return False
        try:
            resp = self._client.get(self._org_url(f"issues/{issue_id}/tags/environment/"))
            if resp.status_code != 200:
                return False
            values = {v.get("value") for v in resp.json().get("topValues", [])}
            return self.cfg.environment in values
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            log.warning("environment check failed for %s: %s", issue.get("shortId"), exc)
            return False

    def poll(self) -> list[ErrorCandidate]:
        seen: set[str] = set()
        out: list[ErrorCandidate] = []
        cap = self.cfg.poll.max_issues_per_cycle
        for sentry_pass in build_passes(self.cfg.poll):
            for issue in self.fetch_issues(sentry_pass):
                short_id = issue.get("shortId")
                if not short_id or short_id in seen:
                    continue
                if sentry_pass.env_mode == "check" and not self.issue_is_production(issue):
                    continue
                seen.add(short_id)
                out.append(ErrorCandidate(
                    short_id=short_id,
                    issue_id=str(issue.get("id", "")),
                    title=issue.get("title", ""),
                    pass_label=sentry_pass.label,
                    permalink=issue.get("permalink", ""),
                ))
                if len(out) >= cap:
                    return out
        return out

    def already_ticketed(self, short_id: str, tickets: Ticketing) -> bool:
        return bool(tickets.search_text(short_id))


register("errors", "sentry", SentryErrorSource)
