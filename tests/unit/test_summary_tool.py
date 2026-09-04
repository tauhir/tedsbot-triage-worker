# ABOUTME: Tests the in-process submit_summary tool: it validates the RunSummary
# ABOUTME: schema, writes summary.json into the run directory, and reports errors.
import json
from pathlib import Path

from tedsbot.summary import build_summary_server


async def test_valid_submission_writes_summary_json(tmp_path: Path) -> None:
    server = build_summary_server(tmp_path)
    assert server.name == "run" and server.allowed_tools == ["mcp__run__submit_summary"]
    result = await server.tool.handler({"kind": "triage_sentry", "ticket": "APP-1", "ticket_url": "https://j/APP-1",
                                        "recommendation": "🟢", "headline": "null deref",
                                        "tldr": "The admin chart page crashed on load; a small fix is ready to review.", "ok": True})
    assert result.get("is_error") is not True and "recorded" in result["content"][0]["text"]
    data = json.loads((tmp_path / "summary.json").read_text())
    assert data["ticket"] == "APP-1" and data["status"] is None and data["pr_url"] is None
    assert data["tldr"].startswith("The admin chart page crashed")


async def test_invalid_submission_returns_error_and_writes_nothing(tmp_path: Path) -> None:
    server = build_summary_server(tmp_path)
    result = await server.tool.handler({"kind": "triage_sentry", "recommendation": "X", "headline": "h", "ok": True})
    assert result["is_error"] is True and "recommendation" in result["content"][0]["text"]
    assert not (tmp_path / "summary.json").exists()


async def test_resubmission_overwrites(tmp_path: Path) -> None:
    server = build_summary_server(tmp_path)
    await server.tool.handler({"kind": "fix", "headline": "first", "ok": False})
    await server.tool.handler({"kind": "fix", "headline": "second", "ok": True, "status": "draft PR opened"})
    assert json.loads((tmp_path / "summary.json").read_text())["headline"] == "second"
