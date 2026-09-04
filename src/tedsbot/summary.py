# ABOUTME: The run summary contract the agent writes and Python validates,
# ABOUTME: with a fallback for missing files and a one-line Slack rendering.
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

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


def read_summary(path: Path, kind: RunKind, fallback_text: str) -> RunSummary:
    try:
        data = json.loads(path.read_text())
        return RunSummary.model_validate(data)
    except (OSError, ValueError, ValidationError):
        return RunSummary(kind=kind, headline=(fallback_text or "no output")[:200], ok=False)


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
