# ABOUTME: Tests config loading: YAML parsing, ${VAR} expansion, validation errors.
# ABOUTME: Every failure path must name the offending key or variable.
from pathlib import Path

import pytest
import yaml

from tedsbot.config import Config, expand_env, load_config
from tedsbot.errors import ConfigError


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "tedsbot.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


def test_expand_env_replaces_known_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOK", "abc")
    assert expand_env("Bearer ${TOK}") == "Bearer abc"


def test_expand_env_missing_variable_names_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOPE", raising=False)
    with pytest.raises(ConfigError, match="NOPE"):
        expand_env("${NOPE}")


def test_load_valid_config(tmp_path: Path, config_dict: dict, env_tokens: None) -> None:
    cfg = load_config(_write(tmp_path, config_dict))
    assert isinstance(cfg, Config)
    assert cfg.errors.token == "sentry-token"
    assert cfg.tickets.token == "atlassian-token"
    assert cfg.notify.url == "https://hooks.slack.example/T/B/X"
    assert cfg.agent.model == "claude-opus-5"
    assert cfg.agent.max_turns.triage == 60
    assert cfg.worker.interval_seconds == 900
    assert cfg.logs is None


def test_poll_defaults(tmp_path: Path, config_dict: dict, env_tokens: None) -> None:
    cfg = load_config(_write(tmp_path, config_dict))
    poll = cfg.errors.poll
    assert poll.new_error.first_seen == "-30m"
    assert poll.new_error.min_times_seen == 3
    assert poll.performance.min_times_seen == 10
    assert poll.levels == ["error", "fatal"]
    assert poll.stats_period == "14d"
    assert poll.max_issues_per_cycle == 5


def test_unknown_kind_is_rejected(tmp_path: Path, config_dict: dict, env_tokens: None) -> None:
    config_dict["errors"]["kind"] = "rollbar"
    with pytest.raises(ConfigError, match="errors.kind"):
        load_config(_write(tmp_path, config_dict))


def test_missing_checkout_is_rejected(tmp_path: Path, config_dict: dict, env_tokens: None) -> None:
    config_dict["repo"]["path"] = str(tmp_path / "nowhere")
    with pytest.raises(ConfigError, match="repo.path"):
        load_config(_write(tmp_path, config_dict))


def test_missing_env_var_is_rejected(tmp_path: Path, config_dict: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SENTRY_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "x")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "x")
    with pytest.raises(ConfigError, match="SENTRY_AUTH_TOKEN"):
        load_config(_write(tmp_path, config_dict))


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.yaml")


def test_knowledge_dir_resolved_relative_to_config(tmp_path: Path, config_dict: dict, env_tokens: None) -> None:
    (tmp_path / "docs").mkdir()
    config_dict["agent"]["knowledge_dir"] = "./docs"
    cfg = load_config(_write(tmp_path, config_dict))
    assert cfg.agent.knowledge_dir == (tmp_path / "docs").resolve()
