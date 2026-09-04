# ABOUTME: Tests the pure option-building half of the runner: prompt assembly,
# ABOUTME: tool allowlists, MCP servers, permission mode, and run directories.
from pathlib import Path

import pytest
import yaml

from tedsbot.config import load_config
from tedsbot.runner import TRIAGE_TOOLS, RunSpec, build_options, new_run_dir


@pytest.fixture
def cfg(tmp_path: Path, config_dict: dict, env_tokens: None):
    p = tmp_path / "tedsbot.yaml"
    p.write_text(yaml.safe_dump(config_dict))
    return load_config(p)


def _spec() -> RunSpec:
    return RunSpec(kind="triage_sentry", prompt_name="triage_sentry",
                   inputs={"sentry_issue": "APP-1"}, max_turns=60, tools=list(TRIAGE_TOOLS), run_id="r1")


def test_new_run_dir_layout(temp_home: Path) -> None:
    d = new_run_dir("triage_sentry", "https://sentry.io/x/APP-1/")
    assert d.is_dir() and d.parent == temp_home / ".tedsbot" / "runs"
    assert d.name.endswith("-triage_sentry-APP-1")


def test_build_options_shape(cfg, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    options, prompt = build_options(cfg, _spec(), run_dir)
    assert options.permission_mode == "dontAsk"
    assert options.setting_sources == []
    assert options.strict_mcp_config is True
    assert Path(options.cwd) == cfg.repo.path
    assert options.model == "claude-opus-5"
    assert options.max_turns == 60
    assert set(options.mcp_servers) == {"sentry", "atlassian", "notify"}
    assert f"Write({run_dir}/summary.json)" in options.allowed_tools
    assert "mcp__sentry__*" in options.allowed_tools and "mcp__atlassian__*" in options.allowed_tools
    assert "mcp__notify__notify_slack" in options.allowed_tools
    assert "Edit" not in options.allowed_tools
    sp = options.system_prompt
    assert sp["type"] == "preset" and sp["preset"] == "claude_code"
    assert sp["exclude_dynamic_sections"] is True
    assert "## triage-method" in sp["append"] and "## Jira" in sp["append"]
    assert "SENTRY_ISSUE: APP-1" in prompt and str(run_dir / "summary.json") in prompt


def test_build_options_passes_only_present_auth_env(cfg, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth")
    options, _ = build_options(cfg, _spec(), tmp_path)
    assert options.env == {"CLAUDE_CODE_OAUTH_TOKEN": "oauth"}


def test_knowledge_dir_and_claude_md_included_for_fix(cfg, tmp_path: Path) -> None:
    (cfg.repo.path / "CLAUDE.md").write_text("# House rules\nno tabs\n")
    spec = RunSpec(kind="fix", prompt_name="triage_sentry", inputs={"sentry_issue": "x"},
                   max_turns=10, tools=["Read"], include_edit_tools=True, run_id="r2")
    options, _ = build_options(cfg, spec, tmp_path)
    assert "no tabs" in options.system_prompt["append"]
