# ABOUTME: Tests knowledge assembly: tier order, per-file headings, missing
# ABOUTME: consumer dir tolerance, and the size warning.
from pathlib import Path

from tedsbot.knowledge import assemble_knowledge


def test_order_is_provider_then_shipped_then_consumer(tmp_path: Path) -> None:
    (tmp_path / "b-team.md").write_text("team b\n")
    (tmp_path / "a-team.md").write_text("# Team A\nteam a\n")
    block = assemble_knowledge(["## Sentry\ns"], tmp_path, warn_kb=64)
    text = block.text
    assert text.index("## Sentry") < text.index("## recommendation-tiers")
    assert text.index("## triage-method") < text.index("# Team A")
    assert text.index("# Team A") < text.index("## b-team")
    assert block.warnings == []


def test_missing_consumer_dir_is_allowed() -> None:
    block = assemble_knowledge([], Path("/nonexistent/dir"), warn_kb=64)
    assert "## triage-method" in block.text
    assert any("knowledge_dir" in w for w in block.warnings)


def test_size_warning(tmp_path: Path) -> None:
    (tmp_path / "big.md").write_text("x" * 70_000)
    block = assemble_knowledge([], tmp_path, warn_kb=64)
    assert block.size_kb > 64
    assert any("exceeds" in w for w in block.warnings)


def test_extra_sections_come_last(tmp_path: Path) -> None:
    block = assemble_knowledge([], tmp_path, warn_kb=64, extra_sections=["## Project CLAUDE.md\nrules"])
    assert block.text.rstrip().endswith("rules")
