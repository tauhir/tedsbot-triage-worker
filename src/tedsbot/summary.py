# ABOUTME: The run summary contract the agent writes and Python validates,
# ABOUTME: with a fallback for missing files and a one-line Slack rendering.
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from claude_agent_sdk import create_sdk_mcp_server, tool
from pydantic import BaseModel, Field, ValidationError

from tedsbot import __version__
from tedsbot.providers.base import McpServer

Recommendation = Literal["🟢", "🟡", "⚪", "🔴"]
RunKind = Literal["triage_sentry", "triage_ticket", "fix"]
Outcome = Literal[
    "new_ticket", "regression", "duplicate", "not_a_bug", "analysed_existing", "insufficient_repro",
]


class RunSummary(BaseModel):
    kind: RunKind
    ticket: str | None = None
    ticket_url: str | None = None
    recommendation: Recommendation | None = None
    status: str | None = None
    pr_url: str | None = None
    headline: str = Field(max_length=300)
    tldr: str | None = Field(default=None, max_length=320)
    outcome: Outcome | None = None
    title: str | None = Field(default=None, max_length=200)
    events: int | None = None
    users: int | None = None
    first_seen: str | None = None
    last_seen: str | None = None
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


_HEADERS: dict[tuple[str, str], str] = {
    ("new_ticket", "🟢"): "New bug found: low-risk fix ready",
    ("new_ticket", "🟡"): "New bug found: needs a developer's decision",
    ("new_ticket", "⚪"): "Not a code bug",
    ("new_ticket", "🔴"): "New ticket: cause not established",
    ("regression", "🟢"): "Regression: a fixed bug is back",
    ("regression", "🟡"): "Regression: a fixed bug is back, needs a decision",
    ("regression", "⚪"): "Regression report: not a code bug",
    ("regression", "🔴"): "Regression: a fixed bug is back, cause not established",
    ("duplicate", "*"): "Known issue seen again",
    ("not_a_bug", "*"): "Known non-bug seen again",
    ("analysed_existing", "🟢"): "Bug report analysed: low-risk fix ready",
    ("analysed_existing", "🟡"): "Bug report analysed: needs a developer's decision",
    ("analysed_existing", "⚪"): "Bug report analysed: not a code bug",
    ("analysed_existing", "🔴"): "Bug report analysed: cause not established",
    ("insufficient_repro", "*"): "Bug report needs more detail",
}


def _next_action(outcome: str | None, tier: str | None, approve_status: str) -> str:
    if outcome in ("duplicate", "not_a_bug"):
        return "No action. The existing ticket covers it, and new occurrences are noted there when the numbers change."
    if outcome == "insufficient_repro":
        return "The reporter answers the questions in the ticket comment."
    if tier == "🟢":
        return f"Review the ticket and move it to {approve_status} to have the bot open a draft PR."
    if tier == "🟡":
        return f"A developer reads the analysis and picks a direction, then moves the ticket to {approve_status}."
    if tier == "⚪":
        return "No code change. The ticket says what to do instead."
    if tier == "🔴":
        return "Someone with context adds what the analysis is missing to the ticket."
    return "See the ticket."


def _plain(text: str) -> str:
    """Slack-safe prose: no em-dashes; the house style is plain sentences."""
    return text.replace(" — ", ", ").replace("—", ", ").replace(" – ", ", ")


def _date(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.day} {d.strftime('%b %Y')}"


def _impact(s: RunSummary) -> str | None:
    parts: list[str] = []
    if s.events is not None:
        parts.append(f"{s.events} event{'s' if s.events != 1 else ''}")
    if s.users is not None:
        parts.append(f"{s.users} user{'s' if s.users != 1 else ''}")
    if first := _date(s.first_seen):
        parts.append(f"first seen {first}")
    if last := _date(s.last_seen):
        parts.append(f"last seen {last}")
    return ", ".join(parts) if parts else None


def slack_line(s: RunSummary, run_dir: Path, approve_status: str = "the approval status") -> str:
    """Render the run as a Slack mrkdwn message: header, ticket, plain account, impact, technical, next step."""
    if not s.ok:
        lines = [f"*⚠️ Triage run failed: {s.kind.replace('_', ' ')} {s.ticket or '?'}*", _plain(s.headline)]
        if s.ticket_url:
            lines.append(s.ticket_url)
        lines.append(f"Run dir: {run_dir}")
        return "\n".join(lines)
    tier = s.recommendation or s.status or "✅"
    header = _HEADERS.get((s.outcome or "", tier)) or _HEADERS.get((s.outcome or "", "*")) or "Triage result"
    ticket = f"<{s.ticket_url}|{s.ticket}>" if s.ticket_url and s.ticket else (s.ticket or "?")
    lines = [f"*{tier} {header}*", f"*{ticket}*" + (f" {_plain(s.title)}" if s.title else "")]
    if s.tldr:
        lines.append(f"*What happened:* {_plain(s.tldr)}")
    if impact := _impact(s):
        lines.append(f"*Impact:* {impact}")
    lines.append(f"*Technical:* {_plain(s.headline)}")
    if s.pr_url:
        lines.append(f"*PR:* {s.pr_url}")
    if s.outcome or s.recommendation:
        lines.append(f"*Next:* {_next_action(s.outcome, s.recommendation, approve_status)}")
    return "\n".join(lines)

SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["triage_sentry", "triage_ticket", "fix"]},
        "ticket": {"type": ["string", "null"], "description": "Ticket key, e.g. APP-123"},
        "ticket_url": {"type": ["string", "null"]},
        "recommendation": {"type": ["string", "null"], "enum": ["🟢", "🟡", "⚪", "🔴", None]},
        "status": {"type": ["string", "null"], "description": "Fix runs only, e.g. 'draft PR opened', 'blocked'"},
        "pr_url": {"type": ["string", "null"]},
        "outcome": {"type": "string", "enum": ["new_ticket", "regression", "duplicate", "not_a_bug", "analysed_existing", "insufficient_repro"],
                    "description": "new_ticket: created a ticket; regression: created a ticket linked to a Done one; duplicate: commented on an open ticket; not_a_bug: commented on a Won't Do ticket; analysed_existing: analysed a reported ticket; insufficient_repro: asked the reporter for details"},
        "title": {"type": ["string", "null"], "maxLength": 200, "description": "The ticket summary as it appears on the board"},
        "events": {"type": ["integer", "null"], "description": "Sentry event count for the issue"},
        "users": {"type": ["integer", "null"], "description": "Sentry affected-user count"},
        "first_seen": {"type": ["string", "null"], "description": "Sentry firstSeen, ISO 8601"},
        "last_seen": {"type": ["string", "null"], "description": "Sentry lastSeen, ISO 8601"},
        "headline": {"type": "string", "maxLength": 300, "description": "One technical line (under 300 characters): the root cause or outcome, with the file or component"},
        "tldr": {"type": "string", "maxLength": 320, "description": "At most two plain-English sentences (under 320 characters) for non-engineers: what broke for users, why, what happens next. No code, no file paths, no identifiers."},
        "ok": {"type": "boolean"},
    },
    "required": ["kind", "headline", "tldr", "outcome", "ok"],
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
