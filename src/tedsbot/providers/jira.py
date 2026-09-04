# ABOUTME: Jira ticketing provider: MCP server config, prompt facts, provider
# ABOUTME: knowledge, and the REST operations Python calls deterministically.
from __future__ import annotations

from importlib import resources
from typing import Any

import httpx

from tedsbot.config import TicketsConfig
from tedsbot.errors import ProviderError
from tedsbot.providers.base import McpServer, TicketRef
from tedsbot.registry import register


def adf_paragraphs(text: str) -> dict[str, Any]:
    paragraphs = [
        {"type": "paragraph", "content": [{"type": "text", "text": line}]}
        for line in text.split("\n")
        if line.strip()
    ]
    return {"type": "doc", "version": 1, "content": paragraphs}


def _adf_text(node: Any) -> str:
    if isinstance(node, dict):
        if node.get("type") == "text":
            return str(node.get("text", ""))
        return "".join(_adf_text(c) for c in node.get("content", []))
    if isinstance(node, list):
        return "".join(_adf_text(c) for c in node)
    return ""


class JiraTicketing:
    def __init__(self, cfg: TicketsConfig) -> None:
        self.cfg = cfg
        self._client = httpx.Client(
            base_url=f"{cfg.url}/rest/api/3",
            headers={"Authorization": f"Bearer {cfg.token}", "Accept": "application/json"},
            timeout=30,
        )

    def mcp_server(self) -> McpServer:
        return McpServer(
            name="atlassian",
            config={
                "command": "uvx",
                "args": ["mcp-atlassian"],
                "env": {
                    "JIRA_URL": self.cfg.url,
                    "ATLASSIAN_OAUTH_CLOUD_ID": self.cfg.cloud_id,
                    "ATLASSIAN_OAUTH_ACCESS_TOKEN": self.cfg.token,
                },
            },
            allowed_tools=["mcp__atlassian__*"],
        )

    def prompt_facts(self) -> dict[str, str]:
        s, f, l = self.cfg.statuses, self.cfg.fields, self.cfg.labels
        return {
            "jira_url": self.cfg.url,
            "jira_project": self.cfg.project,
            "jira_cloud_id": self.cfg.cloud_id,
            "bug_issue_type_id": self.cfg.bug_issue_type_id,
            "qa_notes_field": f.qa_notes,
            "qa_instructions_field": f.qa_instructions,
            "status_intake": s.intake,
            "status_triage_target": s.triage_target,
            "status_fix_approved": s.fix_approved,
            "status_in_progress": s.in_progress,
            "status_code_review": s.code_review,
            "label_from_errors": l.from_errors,
            "label_insufficient_repro": l.insufficient_repro,
        }

    def knowledge(self) -> str:
        return resources.files("tedsbot.providers.knowledge").joinpath("jira.md").read_text()

    def _get(self, path: str, **params: str) -> Any:
        resp = self._client.get(path, params=params)
        if resp.status_code != 200:
            raise ProviderError(f"jira GET {path} {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def _ref(self, issue: dict[str, Any]) -> TicketRef:
        fields = issue.get("fields", {})
        return TicketRef(
            key=issue["key"],
            url=f"{self.cfg.url}/browse/{issue['key']}",
            status=fields.get("status", {}).get("name", ""),
            summary=fields.get("summary", ""),
        )

    def _search(self, jql: str, fields: str = "summary,status,comment") -> list[dict[str, Any]]:
        data = self._get("/search/jql", jql=jql, fields=fields, maxResults="50")
        return list(data.get("issues", []))

    def untriaged_bugs(self, bot_marker: str) -> list[TicketRef]:
        jql = (
            f'project = "{self.cfg.project}" AND issuetype = Bug '
            f'AND status = "{self.cfg.statuses.intake}" ORDER BY created ASC'
        )
        out: list[TicketRef] = []
        for issue in self._search(jql):
            comments = issue.get("fields", {}).get("comment", {}).get("comments", [])
            if any(bot_marker in _adf_text(c.get("body")) for c in comments):
                continue
            out.append(self._ref(issue))
        return out

    def approved_for_fix(self) -> list[TicketRef]:
        jql = (
            f'project = "{self.cfg.project}" AND status = "{self.cfg.statuses.fix_approved}" '
            "ORDER BY updated ASC"
        )
        return [self._ref(i) for i in self._search(jql, fields="summary,status")]

    def status_of(self, key: str) -> str:
        return self._ref(self._get(f"/issue/{key}", fields="summary,status")).status

    def search_text(self, text: str) -> list[TicketRef]:
        escaped = text.replace('"', '\\"')
        jql = f'project = "{self.cfg.project}" AND text ~ "{escaped}"'
        return [self._ref(i) for i in self._search(jql, fields="summary,status")]

    def comment(self, key: str, body: str) -> None:
        resp = self._client.post(f"/issue/{key}/comment", json={"body": adf_paragraphs(body)})
        if resp.status_code not in (200, 201):
            raise ProviderError(f"jira comment on {key} {resp.status_code}: {resp.text[:200]}")

    def statuses_exist(self, names: list[str]) -> list[str]:
        data = self._get(f"/project/{self.cfg.project}/statuses")
        present = {s["name"] for issue_type in data for s in issue_type.get("statuses", [])}
        return [n for n in names if n not in present]


register("tickets", "jira", JiraTicketing)
