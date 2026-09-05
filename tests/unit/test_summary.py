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


def _summary(**over):
    base = {
        "kind": "triage_sentry", "ticket": "APP-420", "ticket_url": "https://j/APP-420", "recommendation": "🟡",
        "outcome": "new_ticket", "title": "Saved-filter edit drops the audit entry",
        "headline": "TicketAssignment.__str__ raises DoesNotExist in pre_save (apps/reviews/models.py:1866)",
        "tldr": "An admin edited a saved filter. One history line was lost, nothing else broke.",
        "events": 1, "users": 1, "first_seen": "2026-08-26T09:14:00Z", "last_seen": "2026-08-26T09:14:00Z", "ok": True,
    }
    base.update(over)
    return RunSummary(**base)


def test_slack_message_for_new_yellow_ticket(tmp_path: Path) -> None:
    text = slack_line(_summary(), tmp_path, approve_status="Approved For Fix")
    assert text.splitlines() == [
        "*🟡 New bug found: needs a developer's decision*",
        "*<https://j/APP-420|APP-420>* Saved-filter edit drops the audit entry",
        "*What happened:* An admin edited a saved filter. One history line was lost, nothing else broke.",
        "*Impact:* 1 event, 1 user, first seen 26 Aug 2026, last seen 26 Aug 2026",
        "*Technical:* TicketAssignment.__str__ raises DoesNotExist in pre_save (apps/reviews/models.py:1866)",
        "*Next:* A developer reads the analysis and picks a direction, then moves the ticket to Approved For Fix.",
    ]


def test_slack_message_headers_and_actions_by_outcome(tmp_path: Path) -> None:
    cases = {
        ("new_ticket", "🟢"): ("New bug found: low-risk fix ready", "move it to Approved For Fix"),
        ("new_ticket", "⚪"): ("Not a code bug", "No code change"),
        ("new_ticket", "🔴"): ("New ticket: cause not established", "adds what the analysis is missing"),
        ("regression", "🟢"): ("Regression: a fixed bug is back", "Approved For Fix"),
        ("duplicate", "⚪"): ("Known issue seen again", "No action"),
        ("analysed_existing", "🟡"): ("Bug report analysed: needs a developer's decision", "Approved For Fix"),
        ("insufficient_repro", "🔴"): ("Bug report needs more detail", "reporter"),
    }
    for (outcome, tier), (header, action) in cases.items():
        text = slack_line(_summary(outcome=outcome, recommendation=tier), tmp_path, approve_status="Approved For Fix")
        first, last = text.splitlines()[0], text.splitlines()[-1]
        assert first == f"*{tier} {header}*", (outcome, tier, first)
        assert action in last, (outcome, tier, last)


def test_slack_message_omits_impact_and_title_when_unknown(tmp_path: Path) -> None:
    text = slack_line(_summary(title=None, events=None, users=None, first_seen=None, last_seen=None), tmp_path)
    lines = text.splitlines()
    assert lines[1] == "*<https://j/APP-420|APP-420>*"
    assert not any(line.startswith("*Impact:*") for line in lines)


def test_slack_message_replaces_em_dashes_and_pluralises(tmp_path: Path) -> None:
    text = slack_line(_summary(tldr="Nothing broke — the save went through — one line was lost.", events=3, users=2,
                               first_seen="2026-08-01T00:00:00Z", last_seen="2026-09-04T00:00:00Z"), tmp_path)
    assert "—" not in text
    assert "*What happened:* Nothing broke, the save went through, one line was lost." in text
    assert "*Impact:* 3 events, 2 users, first seen 1 Aug 2026, last seen 4 Sep 2026" in text


def test_slack_message_without_tldr_still_has_header_and_technical(tmp_path: Path) -> None:
    text = slack_line(_summary(tldr=None, outcome=None), tmp_path)
    lines = text.splitlines()
    assert lines[0] == "*🟡 Triage result*"
    assert not any(line.startswith("*What happened:*") for line in lines)
    assert any(line.startswith("*Technical:*") for line in lines)


def test_slack_line_for_failure_has_warning_and_run_dir(tmp_path: Path) -> None:
    s = RunSummary(kind="triage_ticket", ticket="APP-2", ticket_url=None, recommendation=None,
                   status=None, pr_url=None, headline="agent died", ok=False)
    line = slack_line(s, tmp_path)
    assert line.splitlines()[0] == "*⚠️ Triage run failed: triage ticket APP-2*"
    assert "agent died" in line and str(tmp_path) in line and "—" not in line


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
