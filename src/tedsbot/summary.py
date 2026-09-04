# ABOUTME: The run summary contract the agent writes and Python validates,
# ABOUTME: with a fallback for missing files and a one-line Slack rendering.
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from claude_agent_sdk import create_sdk_mcp_server, tool
from pydantic import BaseModel, ValidationError

from tedsbot import __version__
from tedsbot.providers.base import McpServer

Recommendation = Literal["🟢", "🟡", "⚪", "🔴"]
RunKind = Literal["triage_sentry", "triage_ticket", "fix"]


class RunSummary(BaseModel):
    kind: RunKind
    ticket: str | None = None
    ticket_url: str | None = None
    recommendation: Recommendation | None = None
    status: str | None = None
    pr_url: str | None = None
    headline: str
    ok: bool


FALLBACK_HEADLINE_MAX = 160
_MARKDOWN_EDGES = re.compile(r"^[#>*_`\s]+|[*_`\s]+$")


def fallback_headline(text: str) -> str:
    """First meaningful line of the agent's final text, without markdown, cut at a word."""
    for raw in (text or "").splitlines():
        line = _MARKDOWN_EDGES.sub("", raw.strip())
        line = line.replace("**", "").replace("`", "")
        if line:
            break
    else:
        return "no output"
    if len(line) <= FALLBACK_HEADLINE_MAX:
        return line
    cut = line[: FALLBACK_HEADLINE_MAX - 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip() + "…"


def _first_match(pattern: str | None, text: str) -> str | None:
    if not pattern or not text:
        return None
    m = re.search(pattern, text)
    return m.group(0) if m else None


def read_summary(
    path: Path,
    kind: RunKind,
    fallback_text: str,
    ticket_pattern: str | None = None,
    ticket_url_base: str | None = None,
) -> RunSummary:
    try:
        data = json.loads(path.read_text())
        return RunSummary.model_validate(data)
    except (OSError, ValueError, ValidationError):
        ticket = _first_match(ticket_pattern, fallback_text)
        return RunSummary(
            kind=kind,
            ticket=ticket,
            ticket_url=f"{ticket_url_base}/{ticket}" if ticket and ticket_url_base else None,
            headline=fallback_headline(fallback_text),
            ok=False,
        )


def slack_line(s: RunSummary, run_dir: Path) -> str:
    if not s.ok:
        return f"⚠️ {s.kind.replace('_', ' ')} {s.ticket or '?'} — {s.headline}\nrun dir: {run_dir}"
    lead = s.recommendation or s.status or "✅"
    parts = [f"{lead} {s.ticket or '?'} — {s.headline}"]
    if s.ticket_url:
        parts.append(s.ticket_url)
    if s.pr_url:
        parts.append(s.pr_url)
    return "\n".join(parts)


SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["triage_sentry", "triage_ticket", "fix"]},
        "ticket": {"type": ["string", "null"], "description": "Ticket key, e.g. APP-123"},
        "ticket_url": {"type": ["string", "null"]},
        "recommendation": {"type": ["string", "null"], "enum": ["🟢", "🟡", "⚪", "🔴", None]},
        "status": {"type": ["string", "null"], "description": "Fix runs only, e.g. 'draft PR opened', 'blocked'"},
        "pr_url": {"type": ["string", "null"]},
        "headline": {"type": "string", "description": "One line: the root cause or outcome"},
        "ok": {"type": "boolean"},
    },
    "required": ["kind", "headline", "ok"],
}


class SummaryServer(McpServer):
    """The in-process MCP server that receives the run summary, plus its tool for tests."""

    tool: Any


def build_summary_server(run_dir: Path) -> SummaryServer:
    """Build the in-process tool the agent calls to record its run summary.

    The agent has no file-write permission; this tool validates the payload
    against RunSummary, writes <run_dir>/summary.json, and returns validation
    errors to the agent so it can correct and resubmit.
    """
    target = run_dir / "summary.json"

    @tool(
        "submit_summary",
        "Record the run summary. Call exactly once at the end of the run (again to correct it). "
        "Fields: kind, ticket, ticket_url, recommendation (🟢 🟡 ⚪ 🔴), status, pr_url, headline, ok.",
        SUMMARY_SCHEMA,
    )
    async def submit_summary(args: dict[str, Any]) -> dict[str, Any]:
        try:
            summary = RunSummary.model_validate(args)
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
            return {"content": [{"type": "text", "text": f"summary rejected: {problems}"}], "is_error": True}
        target.write_text(summary.model_dump_json(indent=2))
        return {"content": [{"type": "text", "text": f"recorded {target}"}]}

    server = create_sdk_mcp_server(name="run", version=__version__, tools=[submit_summary])
    built = SummaryServer(name="run", config=server, allowed_tools=["mcp__run__submit_summary"])
    object.__setattr__(built, "tool", submit_summary)
    return built
