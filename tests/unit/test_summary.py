# ABOUTME: Tests RunSummary parsing, fallback on missing/invalid files, and
# ABOUTME: the one-line Slack rendering.
import json
from pathlib import Path

from tedsbot.summary import RunSummary, read_summary, slack_line


def test_reads_valid_summary(tmp_path: Path) -> None:
    p = tmp_path / "summary.json"
    p.write_text(json.dumps({"kind": "triage_sentry", "ticket": "APP-1", "ticket_url": "u",
                             "recommendation": "🟢", "status": None, "pr_url": None,
                             "headline": "null deref", "ok": True}))
    s = read_summary(p, "triage_sentry", "agent text")
    assert s.ok and s.ticket == "APP-1" and s.recommendation == "🟢"


def test_missing_file_falls_back(tmp_path: Path) -> None:
    s = read_summary(tmp_path / "summary.json", "triage_ticket", "the agent said this")
    assert s.ok is False and s.kind == "triage_ticket"
    assert s.headline.startswith("the agent said this")


def test_invalid_json_falls_back(tmp_path: Path) -> None:
    p = tmp_path / "summary.json"
    p.write_text("{not json")
    s = read_summary(p, "fix", "x" * 500)
    assert s.ok is False and len(s.headline) <= 160 and s.headline.endswith("…")


def test_schema_invalid_json_falls_back(tmp_path: Path) -> None:
    p = tmp_path / "summary.json"
    p.write_text(json.dumps({"kind": "triage_sentry", "recommendation": "X", "headline": "h", "ok": True}))
    s = read_summary(p, "triage_sentry", "agent text")
    assert s.ok is False and s.headline.startswith("agent text")


def test_slack_line_for_success(tmp_path: Path) -> None:
    s = RunSummary(kind="triage_sentry", ticket="APP-1", ticket_url="https://j/APP-1",
                   recommendation="🟡", status=None, pr_url=None, headline="race in save",
                   tldr="Two people saving the same review at once could lose one edit.", ok=True)
    assert slack_line(s, tmp_path) == (
        "🟡 APP-1 — Two people saving the same review at once could lose one edit.\n"
        "Technical: race in save\nhttps://j/APP-1"
    )


def test_slack_line_without_tldr_uses_headline_alone(tmp_path: Path) -> None:
    s = RunSummary(kind="triage_sentry", ticket="APP-1", ticket_url="https://j/APP-1",
                   recommendation="🟢", headline="null deref", ok=True)
    assert slack_line(s, tmp_path) == "🟢 APP-1 — null deref\nhttps://j/APP-1"


def test_slack_line_for_failure_has_warning_and_run_dir(tmp_path: Path) -> None:
    s = RunSummary(kind="triage_ticket", ticket="APP-2", ticket_url=None, recommendation=None,
                   status=None, pr_url=None, headline="agent died", ok=False)
    line = slack_line(s, tmp_path)
    assert line.startswith("⚠️ triage ticket APP-2 — agent died") and str(tmp_path) in line


def test_fallback_headline_is_first_meaningful_line_without_markdown(tmp_path: Path) -> None:
    text = (
        "Triage is complete through ticket creation; the final summary-file write is blocked.\n\n"
        "## What I found — ⚪ not a code bug\n\n**APP-419** is `FieldError: ...`"
    )
    s = read_summary(tmp_path / "missing.json", "triage_sentry", text)
    assert s.headline == "Triage is complete through ticket creation; the final summary-file write is blocked."


def test_fallback_headline_skips_leading_markdown_and_cuts_at_word_boundary(tmp_path: Path) -> None:
    text = "## What I found — ⚪ not a code bug\n\n**APP-419** is " + "word " * 60
    s = read_summary(tmp_path / "missing.json", "triage_sentry", text)
    assert s.headline.startswith("What I found — ⚪ not a code bug")
    s2 = read_summary(tmp_path / "missing.json", "triage_sentry", "**APP-419** is " + "word " * 60)
    assert len(s2.headline) <= 160 and s2.headline.endswith("…") and not s2.headline.endswith(" …")


def test_fallback_recovers_ticket_key_from_text(tmp_path: Path) -> None:
    text = "Landed APP-419 in Dev Team Review but could not write the summary."
    s = read_summary(tmp_path / "missing.json", "triage_sentry", text, ticket_pattern=r"\bAPP-\d+\b", ticket_url_base="https://example.atlassian.net/browse")
    assert s.ticket == "APP-419" and s.ticket_url == "https://example.atlassian.net/browse/APP-419"
    assert s.recommendation is None and s.ok is False
