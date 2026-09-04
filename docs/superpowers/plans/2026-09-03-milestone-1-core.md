# tedsbot-triage-worker — Milestone 1 (Core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working `tedsbot` CLI that validates its config (`check`) and runs one-shot triage of a Sentry error or a Jira bug through the Claude Agent SDK, landing a ticket and a Slack notification.

**Architecture:** One Python package. YAML config declares roles (errors, tickets, notify, agent) each with a `kind`; a registry maps `kind` to a provider class that contributes an MCP server config, prompt facts, provider knowledge, and deterministic HTTP operations. The runner assembles a `claude_code`-preset system prompt from three knowledge tiers, runs `query()` with a strict tool allowlist in `dontAsk` mode, and reads a `summary.json` the agent writes into a per-run directory. Python posts the Slack message after the run.

**Tech Stack:** Python 3.12, `uv`, `claude-agent-sdk` 0.2.x, `pydantic` v2, `pyyaml`, `jinja2`, `httpx`, `pytest` + `pytest-asyncio` + `pytest-xdist` + `vcrpy` + `respx`, `ruff`.

**Spec:** `docs/superpowers/specs/2026-09-03-tedsbot-triage-worker-design.md`

## Global Constraints

- Python `>=3.12`. Dependency manager is `uv`; `uv run pytest -n auto` is the test command.
- Every code file starts with exactly two comment lines beginning `ABOUTME: `.
- TDD: write the failing test, run it, implement, run it, commit. No production code without a failing test.
- No mock mode in production code. Unit tests may mock HTTP with `respx`; integration tests use `vcrpy` cassettes; end-to-end tests hit real services and skip without `TEDSBOT_E2E=1`.
- Test output must be pristine: no warnings. `pytest` is configured with `filterwarnings = error`.
- Nothing project-specific in the repo: example values are `example-org`, `example.atlassian.net`, `APP`, `example-org/example-app`.
- Recommendation emojis are exactly `🟢 🟡 ⚪ 🔴`.
- Permission mode for every agent run is `dontAsk`. Setting sources for every agent run are `[]`.
- Model default is `claude-opus-5`.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_0181pu6TuuSzo6MSz5ioe4Wy
  ```
- Never `--no-verify`.

## File structure (Milestone 1)

```
pyproject.toml
CLAUDE.md                          repo conventions for agents working here
README.md                          mission, principles, setup guide
tedsbot.example.yaml
knowledge/
  triage-method.md
  recommendation-tiers.md
  replication-steps.md
src/tedsbot/
  __init__.py                      version string
  cli.py                           argparse; dispatch to commands
  config.py                        pydantic models + load_config()
  errors.py                        ConfigError, GateError, ProviderError
  registry.py                      kind -> provider class
  knowledge.py                     assemble_knowledge()
  summary.py                       RunSummary + read_summary()
  runner.py                        RunSpec, build_options(), run()
  notify.py                        Slack webhook notifier
  commands/
    __init__.py
    check.py                       run_check()
    triage.py                      triage_sentry(), triage_ticket()
  prompts/
    __init__.py                    render_prompt()
    triage_sentry.md.j2
    triage_ticket.md.j2
  providers/
    __init__.py
    base.py                        protocols + dataclasses
    sentry.py
    jira.py
    knowledge/
      sentry.md
      jira.md
tests/
  conftest.py
  unit/
    test_config.py
    test_registry.py
    test_knowledge.py
    test_summary.py
    test_prompts.py
    test_runner_options.py
    test_notify.py
    test_sentry_provider.py
    test_jira_provider.py
    test_cli.py
    test_check.py
    test_triage_commands.py
    test_example_config.py
  integration/
    cassettes/
    test_sentry_poll.py
    test_jira_ops.py
  e2e/
    test_triage_e2e.py
```

---

### Task 1: Project scaffold and CLI skeleton

**Files:**
- Create: `pyproject.toml`, `CLAUDE.md`, `src/tedsbot/__init__.py`, `src/tedsbot/cli.py`, `tests/conftest.py`, `tests/unit/test_cli.py`

**Interfaces:**
- Produces: `tedsbot.__version__: str`; `tedsbot.cli.main(argv: list[str] | None = None) -> int`; `tedsbot.cli.build_parser() -> argparse.ArgumentParser`.

- [ ] **Step 1: Write pyproject.toml**

```toml
[project]
name = "tedsbot-triage-worker"
version = "0.1.0"
description = "Autonomous bug-triage and fix worker on the Claude Agent SDK."
readme = "README.md"
requires-python = ">=3.12"
license = { text = "MIT" }
dependencies = [
    "claude-agent-sdk>=0.2.150,<0.3",
    "pydantic>=2.7,<3",
    "pyyaml>=6.0",
    "jinja2>=3.1",
    "httpx>=0.27",
]

[project.scripts]
tedsbot = "tedsbot.cli:main"

[dependency-groups]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "pytest-xdist>=3.6",
    "vcrpy>=6.0",
    "respx>=0.21",
    "ruff>=0.5",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tedsbot"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
filterwarnings = ["error"]
markers = ["e2e: real-service tests, require TEDSBOT_E2E=1"]

[tool.ruff]
line-length = 88
target-version = "py312"
```

- [ ] **Step 2: Write CLAUDE.md**

```markdown
# tedsbot-triage-worker — conventions

- Every code file starts with two lines beginning `# ABOUTME: `.
- Strict TDD: failing test first, minimal code, green, refactor, commit.
- No mock mode in production code. Unit tests may mock HTTP with respx;
  integration tests use vcrpy cassettes; e2e tests are real and skip
  without `TEDSBOT_E2E=1`.
- Test output must be pristine. `filterwarnings = error` is on.
- Run tests with `uv run pytest -n auto`.
- Nothing project-specific in this repo. Example values are `example-org`,
  `example.atlassian.net`, `APP`.
- Never commit with `--no-verify`.
- Design spec: `docs/superpowers/specs/2026-09-03-tedsbot-triage-worker-design.md`.
```

- [ ] **Step 3: Write the failing CLI test**

`tests/conftest.py`:
```python
# ABOUTME: Shared pytest fixtures for the tedsbot test suite.
# ABOUTME: Provides a temporary HOME and a minimal valid config dict.
import os
from pathlib import Path

import pytest


@pytest.fixture
def temp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    repo = tmp_path / "checkout"
    repo.mkdir()
    os.system(f"git -C {repo} init -q -b main")
    (repo / "README.md").write_text("fixture\n")
    os.system(f"git -C {repo} add -A && git -C {repo} -c user.email=t@t -c user.name=t commit -q -m init")
    return repo


@pytest.fixture
def config_dict(checkout: Path) -> dict:
    return {
        "repo": {"path": str(checkout), "base_branch": "main", "github": "example-org/example-app"},
        "errors": {
            "kind": "sentry",
            "org": "example-org",
            "project_id": "123",
            "region_url": "https://us.sentry.io",
            "environment": "production",
            "token": "${SENTRY_AUTH_TOKEN}",
        },
        "tickets": {
            "kind": "jira",
            "url": "https://example.atlassian.net",
            "cloud_id": "00000000-0000-0000-0000-000000000000",
            "project": "APP",
            "token": "${ATLASSIAN_API_TOKEN}",
            "bug_issue_type_id": "10009",
            "fields": {"qa_notes": "customfield_10075", "qa_instructions": "customfield_10073"},
            "statuses": {
                "intake": "To Triage",
                "triage_target": "Dev Team Review",
                "fix_approved": "Approved For Fix",
                "in_progress": "In Progress",
                "code_review": "Code Review",
            },
            "labels": {"from_errors": "sentry-triage", "insufficient_repro": "insufficient-repro"},
        },
        "notify": {"kind": "slack_webhook", "url": "${SLACK_WEBHOOK_URL}"},
        "agent": {"model": "claude-opus-5", "max_turns": {"triage": 60, "fix": 150}},
    }


@pytest.fixture
def env_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTRY_AUTH_TOKEN", "sentry-token")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "atlassian-token")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/T/B/X")
```

`tests/unit/test_cli.py`:
```python
# ABOUTME: Tests the argparse CLI surface: version, help, subcommand names.
# ABOUTME: Command behaviour is tested in the per-command test modules.
import pytest

from tedsbot import __version__
from tedsbot.cli import build_parser, main


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_parser_has_expected_subcommands() -> None:
    parser = build_parser()
    subparsers = next(a for a in parser._actions if a.dest == "command")
    assert set(subparsers.choices) == {"check", "triage", "fix", "worker"}


def test_triage_has_sentry_and_ticket() -> None:
    parser = build_parser()
    ns = parser.parse_args(["triage", "sentry", "APP-1"])
    assert ns.command == "triage" and ns.triage_kind == "sentry" and ns.target == "APP-1"
    ns = parser.parse_args(["triage", "ticket", "APP-2"])
    assert ns.triage_kind == "ticket" and ns.target == "APP-2"


def test_no_command_prints_help_and_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "usage:" in capsys.readouterr().err
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd /home/tauhir/tedsbot-triage-worker && uv sync && uv run pytest tests/unit/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tedsbot'`

- [ ] **Step 5: Write the package and CLI skeleton**

`src/tedsbot/__init__.py`:
```python
# ABOUTME: Package marker for tedsbot, the triage/fix worker on the Claude Agent SDK.
# ABOUTME: Exposes the package version used by the CLI and the run transcript.
__version__ = "0.1.0"
```

`src/tedsbot/cli.py`:
```python
# ABOUTME: argparse entry point for the tedsbot CLI.
# ABOUTME: Parses subcommands and dispatches to the command modules.
from __future__ import annotations

import argparse
import sys

from tedsbot import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tedsbot", description="Triage and fix worker.")
    parser.add_argument("--version", action="version", version=f"tedsbot {__version__}")
    parser.add_argument("-c", "--config", default="tedsbot.yaml", help="Path to config YAML.")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("check", help="Validate config and connectivity.")

    triage = sub.add_parser("triage", help="Run one triage analysis.")
    triage_sub = triage.add_subparsers(dest="triage_kind", required=True)
    for kind, help_text in (("sentry", "Sentry issue id or URL"), ("ticket", "Ticket key")):
        p = triage_sub.add_parser(kind)
        p.add_argument("target", help=help_text)

    fix = sub.add_parser("fix", help="Implement an approved ticket as a draft PR.")
    fix.add_argument("target", help="Ticket key")

    worker = sub.add_parser("worker", help="Poll and launch runs in a loop.")
    worker.add_argument("--once", action="store_true", help="Run one cycle and exit.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    if ns.command is None:
        parser.print_help(sys.stderr)
        return 2
    return _dispatch(ns)


def _dispatch(ns: argparse.Namespace) -> int:
    # Command modules are wired in later tasks; unknown commands report clearly.
    print(f"{ns.command}: not implemented yet", file=sys.stderr)
    return 1
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_cli.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock CLAUDE.md src/tedsbot/__init__.py src/tedsbot/cli.py tests/conftest.py tests/unit/test_cli.py
git commit -m "feat: project scaffold and CLI skeleton"
```

---

### Task 2: Errors and config models

**Files:**
- Create: `src/tedsbot/errors.py`, `src/tedsbot/config.py`, `tests/unit/test_config.py`

**Interfaces:**
- Produces:
  - `tedsbot.errors.ConfigError(Exception)`, `GateError`, `ProviderError`.
  - `tedsbot.config.Config` (pydantic `BaseModel`) with fields `repo: RepoConfig`, `errors: ErrorsConfig`, `tickets: TicketsConfig`, `logs: LogsConfig | None`, `notify: NotifyConfig`, `agent: AgentConfig`, `worker: WorkerConfig`.
  - `RepoConfig(path: Path, base_branch: str, github: str)`.
  - `ErrorsConfig(kind: str, **provider fields, poll: PollConfig)`; `PollConfig` with `new_error: PassConfig`, `escalating: PassConfig`, `performance: PassConfig`, `chronic: PassConfig`, `levels: list[str]`, `stats_period: str`, `max_issues_per_cycle: int`; `PassConfig(enabled: bool = True, first_seen: str | None = None, min_times_seen: int = 3)`.
  - `TicketsConfig(kind, url, cloud_id, project, token, bug_issue_type_id, fields: TicketFields, statuses: TicketStatuses, labels: TicketLabels)`.
  - `NotifyConfig(kind: str, url: str)`, `LogsConfig(kind: str, url: str, token: str)`.
  - `AgentConfig(model: str = "claude-opus-5", max_turns: MaxTurns, knowledge_dir: Path | None, knowledge_size_warn_kb: int = 64)`; `MaxTurns(triage: int = 60, fix: int = 150)`.
  - `WorkerConfig(interval_seconds: int = 900, branch_prefix: str = "tedsbot/")`.
  - `load_config(path: Path) -> Config`; `expand_env(value: str) -> str` raising `ConfigError` naming the missing variable.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_config.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tedsbot.config'`

- [ ] **Step 3: Write errors.py and config.py**

`src/tedsbot/errors.py`:
```python
# ABOUTME: Exception types raised by tedsbot: config problems, gate refusals,
# ABOUTME: and provider (HTTP) failures. Commands map these to exit codes.


class ConfigError(Exception):
    """Config file is missing, malformed, or references something that does not exist."""


class GateError(Exception):
    """A precondition for a run was not met; the agent was not started."""


class ProviderError(Exception):
    """A provider's deterministic operation failed (HTTP error, bad response)."""
```

`src/tedsbot/config.py`:
```python
# ABOUTME: Pydantic config models and the YAML loader with ${VAR} env expansion.
# ABOUTME: Validation fails fast and names the offending key before any agent run.
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from tedsbot.errors import ConfigError

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")
KNOWN_KINDS: dict[str, set[str]] = {
    "errors": {"sentry"},
    "tickets": {"jira"},
    "logs": {"grafana"},
    "notify": {"slack_webhook"},
}


def expand_env(value: str) -> str:
    def _sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in os.environ:
            raise ConfigError(f"environment variable {name} is not set")
        return os.environ[name]

    return _ENV_RE.sub(_sub, value)


def _expand_tree(node: Any) -> Any:
    if isinstance(node, str):
        return expand_env(node)
    if isinstance(node, dict):
        return {k: _expand_tree(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_expand_tree(v) for v in node]
    return node


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RepoConfig(_Strict):
    path: Path
    base_branch: str = "main"
    github: str


class PassConfig(_Strict):
    enabled: bool = True
    first_seen: str | None = None
    min_times_seen: int = 3


class PollConfig(_Strict):
    new_error: PassConfig = Field(default_factory=lambda: PassConfig(first_seen="-30m"))
    escalating: PassConfig = Field(default_factory=PassConfig)
    performance: PassConfig = Field(default_factory=lambda: PassConfig(min_times_seen=10))
    chronic: PassConfig = Field(default_factory=PassConfig)
    levels: list[str] = Field(default_factory=lambda: ["error", "fatal"])
    stats_period: str = "14d"
    max_issues_per_cycle: int = 5


class ErrorsConfig(_Strict):
    kind: str
    org: str
    project_id: str
    region_url: str = "https://us.sentry.io"
    environment: str = "production"
    token: str
    poll: PollConfig = Field(default_factory=PollConfig)


class TicketFields(_Strict):
    qa_notes: str
    qa_instructions: str


class TicketStatuses(_Strict):
    intake: str
    triage_target: str
    fix_approved: str
    in_progress: str
    code_review: str


class TicketLabels(_Strict):
    from_errors: str = "sentry-triage"
    insufficient_repro: str = "insufficient-repro"


class TicketsConfig(_Strict):
    kind: str
    url: str
    cloud_id: str
    project: str
    token: str
    bug_issue_type_id: str
    fields: TicketFields
    statuses: TicketStatuses
    labels: TicketLabels = Field(default_factory=TicketLabels)


class LogsConfig(_Strict):
    kind: str
    url: str
    token: str


class NotifyConfig(_Strict):
    kind: str
    url: str


class MaxTurns(_Strict):
    triage: int = 60
    fix: int = 150


class AgentConfig(_Strict):
    model: str = "claude-opus-5"
    max_turns: MaxTurns = Field(default_factory=MaxTurns)
    knowledge_dir: Path | None = None
    knowledge_size_warn_kb: int = 64


class WorkerConfig(_Strict):
    interval_seconds: int = 900
    branch_prefix: str = "tedsbot/"


class Config(_Strict):
    repo: RepoConfig
    errors: ErrorsConfig
    tickets: TicketsConfig
    logs: LogsConfig | None = None
    notify: NotifyConfig
    agent: AgentConfig = Field(default_factory=AgentConfig)
    worker: WorkerConfig = Field(default_factory=WorkerConfig)

    @field_validator("repo")
    @classmethod
    def _checkout_exists(cls, repo: RepoConfig) -> RepoConfig:
        if not (repo.path / ".git").exists():
            raise ValueError(f"repo.path {repo.path} is not a git checkout")
        return repo


def _check_kinds(data: dict[str, Any]) -> None:
    for role, kinds in KNOWN_KINDS.items():
        section = data.get(role)
        if section is None:
            continue
        kind = section.get("kind")
        if kind not in kinds:
            raise ConfigError(f"{role}.kind must be one of {sorted(kinds)}, got {kind!r}")


def load_config(path: Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"config file {path} must be a mapping at top level")
    data = _expand_tree(raw)
    _check_kinds(data)
    agent = data.setdefault("agent", {})
    if agent.get("knowledge_dir"):
        agent["knowledge_dir"] = str((path.parent / agent["knowledge_dir"]).resolve())
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        raise ConfigError(f"{loc}: {first['msg']}") from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: 9 passed. If `test_missing_checkout_is_rejected` fails on the match, the pydantic error location is `repo` not `repo.path`; change the validator to raise `ValueError("repo.path ...")` as written and the match on `repo.path` holds because the message contains it.

- [ ] **Step 5: Commit**

```bash
git add src/tedsbot/errors.py src/tedsbot/config.py tests/unit/test_config.py
git commit -m "feat: config models, loader, env expansion"
```

---

### Task 3: Provider protocols and registry

**Files:**
- Create: `src/tedsbot/providers/__init__.py`, `src/tedsbot/providers/base.py`, `src/tedsbot/registry.py`, `tests/unit/test_registry.py`

**Interfaces:**
- Produces:
  - `providers.base.McpServer` dataclass: `name: str`, `config: dict[str, Any]`, `allowed_tools: list[str]`.
  - `providers.base.ErrorCandidate` dataclass: `short_id: str`, `issue_id: str`, `title: str`, `pass_label: str`, `permalink: str`.
  - `providers.base.TicketRef` dataclass: `key: str`, `url: str`, `status: str`, `summary: str`.
  - Protocols `ErrorSource`, `Ticketing`, `LogStore`, `Notifier` as in the spec (methods listed in the code below).
  - `registry.get_error_source(cfg: ErrorsConfig) -> ErrorSource`, `get_ticketing(cfg: TicketsConfig) -> Ticketing`, `get_notifier(cfg: NotifyConfig) -> Notifier`, `get_log_store(cfg: LogsConfig) -> LogStore`; each raises `ConfigError` on unknown kind.
  - `registry.register(role: str, kind: str, factory: Callable)` used by provider modules at import.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_registry.py`:
```python
# ABOUTME: Tests the provider registry: kind lookup, unknown kinds, and that
# ABOUTME: the shipped providers register themselves on import.
import pytest

from tedsbot import registry
from tedsbot.config import ErrorsConfig, NotifyConfig, TicketsConfig, TicketFields, TicketStatuses
from tedsbot.errors import ConfigError
from tedsbot.providers.base import ErrorSource, Notifier, Ticketing


def _errors(kind: str = "sentry") -> ErrorsConfig:
    return ErrorsConfig(kind=kind, org="example-org", project_id="1", token="t")


def _tickets(kind: str = "jira") -> TicketsConfig:
    return TicketsConfig(
        kind=kind, url="https://example.atlassian.net", cloud_id="c", project="APP", token="t",
        bug_issue_type_id="10009",
        fields=TicketFields(qa_notes="customfield_1", qa_instructions="customfield_2"),
        statuses=TicketStatuses(intake="To Triage", triage_target="Dev Team Review",
                                fix_approved="Approved For Fix", in_progress="In Progress",
                                code_review="Code Review"),
    )


def test_sentry_registered() -> None:
    src = registry.get_error_source(_errors())
    assert isinstance(src, ErrorSource)


def test_jira_registered() -> None:
    assert isinstance(registry.get_ticketing(_tickets()), Ticketing)


def test_slack_registered() -> None:
    assert isinstance(registry.get_notifier(NotifyConfig(kind="slack_webhook", url="https://x")), Notifier)


def test_unknown_kind_raises() -> None:
    with pytest.raises(ConfigError, match="rollbar"):
        registry.get_error_source(_errors("rollbar"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tedsbot.registry'`

- [ ] **Step 3: Write base.py, registry.py, providers/__init__.py**

`src/tedsbot/providers/__init__.py`:
```python
# ABOUTME: Provider package. Importing it registers every shipped provider
# ABOUTME: so the registry can resolve a config `kind` to a class.
from tedsbot.providers import jira, sentry, slack  # noqa: F401  (registration side effect)
```

Note: `jira`, `sentry`, `slack` modules are created in Tasks 4 to 6. For this task create three stub modules that only call `register(...)` with a minimal class; the tests here only assert protocol membership. Stub for `sentry.py` (replace fully in Task 4):

```python
# ABOUTME: Sentry error-source provider: MCP server config, prompt facts,
# ABOUTME: provider knowledge, and the deterministic poll passes.
from __future__ import annotations

from tedsbot.config import ErrorsConfig
from tedsbot.providers.base import ErrorCandidate, McpServer, Ticketing
from tedsbot.registry import register


class SentryErrorSource:
    def __init__(self, cfg: ErrorsConfig) -> None:
        self.cfg = cfg

    def mcp_server(self) -> McpServer:
        raise NotImplementedError

    def prompt_facts(self) -> dict[str, str]:
        raise NotImplementedError

    def knowledge(self) -> str:
        raise NotImplementedError

    def poll(self) -> list[ErrorCandidate]:
        raise NotImplementedError

    def already_ticketed(self, short_id: str, tickets: Ticketing) -> bool:
        raise NotImplementedError


register("errors", "sentry", SentryErrorSource)
```

Stub `jira.py` with class `JiraTicketing(cfg: TicketsConfig)` and methods `mcp_server, prompt_facts, knowledge, untriaged_bugs, approved_for_fix, status_of, search_text, comment, statuses_exist` all raising `NotImplementedError`, registered as `("tickets", "jira")`. Stub `slack.py` with class `SlackWebhookNotifier(cfg: NotifyConfig)` and methods `post, sdk_server` raising `NotImplementedError`, registered as `("notify", "slack_webhook")`.

`src/tedsbot/providers/base.py`:
```python
# ABOUTME: Protocols and dataclasses every provider implements: what it
# ABOUTME: contributes to the agent run and what Python can call directly.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class McpServer:
    name: str
    config: dict[str, Any]
    allowed_tools: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ErrorCandidate:
    short_id: str
    issue_id: str
    title: str
    pass_label: str
    permalink: str


@dataclass(frozen=True)
class TicketRef:
    key: str
    url: str
    status: str
    summary: str


@runtime_checkable
class Ticketing(Protocol):
    def mcp_server(self) -> McpServer: ...
    def prompt_facts(self) -> dict[str, str]: ...
    def knowledge(self) -> str: ...
    def untriaged_bugs(self, bot_marker: str) -> list[TicketRef]: ...
    def approved_for_fix(self) -> list[TicketRef]: ...
    def status_of(self, key: str) -> str: ...
    def search_text(self, text: str) -> list[TicketRef]: ...
    def comment(self, key: str, body: str) -> None: ...
    def statuses_exist(self, names: list[str]) -> list[str]: ...


@runtime_checkable
class ErrorSource(Protocol):
    def mcp_server(self) -> McpServer: ...
    def prompt_facts(self) -> dict[str, str]: ...
    def knowledge(self) -> str: ...
    def poll(self) -> list[ErrorCandidate]: ...
    def already_ticketed(self, short_id: str, tickets: Ticketing) -> bool: ...


@runtime_checkable
class LogStore(Protocol):
    def mcp_server(self) -> McpServer: ...
    def prompt_facts(self) -> dict[str, str]: ...
    def knowledge(self) -> str: ...


@runtime_checkable
class Notifier(Protocol):
    def post(self, text: str) -> None: ...
    def sdk_server(self) -> McpServer: ...
```

`src/tedsbot/registry.py`:
```python
# ABOUTME: Maps a config role + kind to a provider factory. Provider modules
# ABOUTME: call register() at import; commands call the get_* helpers.
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tedsbot.errors import ConfigError

_REGISTRY: dict[tuple[str, str], Callable[[Any], Any]] = {}


def register(role: str, kind: str, factory: Callable[[Any], Any]) -> None:
    _REGISTRY[(role, kind)] = factory


def _resolve(role: str, cfg: Any) -> Any:
    import tedsbot.providers  # noqa: F401  (ensure shipped providers registered)

    factory = _REGISTRY.get((role, cfg.kind))
    if factory is None:
        known = sorted(k for r, k in _REGISTRY if r == role)
        raise ConfigError(f"{role}.kind {cfg.kind!r} is not registered; known: {known}")
    return factory(cfg)


def get_error_source(cfg: Any) -> Any:
    return _resolve("errors", cfg)


def get_ticketing(cfg: Any) -> Any:
    return _resolve("tickets", cfg)


def get_log_store(cfg: Any) -> Any:
    return _resolve("logs", cfg)


def get_notifier(cfg: Any) -> Any:
    return _resolve("notify", cfg)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_registry.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/tedsbot/providers src/tedsbot/registry.py tests/unit/test_registry.py
git commit -m "feat: provider protocols and registry with stub providers"
```

---

### Task 4: Sentry provider

**Files:**
- Replace: `src/tedsbot/providers/sentry.py`
- Create: `src/tedsbot/providers/knowledge/sentry.md`, `tests/unit/test_sentry_provider.py`, `tests/integration/test_sentry_poll.py`, `tests/integration/cassettes/` (recorded)

**Interfaces:**
- Consumes: `ErrorsConfig`, `McpServer`, `ErrorCandidate`, `Ticketing.search_text`.
- Produces: `SentryErrorSource(cfg)` implementing `ErrorSource`; module-level `build_passes(poll: PollConfig) -> list[SentryPass]` where `SentryPass` is a dataclass `label: str, query: str, sort: str, env_mode: Literal["param", "check"]`; `SentryErrorSource.fetch_issues(sentry_pass) -> list[dict]`; `SentryErrorSource.issue_is_production(issue: dict) -> bool`.

- [ ] **Step 1: Write the failing unit tests**

`tests/unit/test_sentry_provider.py`:
```python
# ABOUTME: Unit tests for the Sentry provider: MCP config, prompt facts,
# ABOUTME: pass construction, dedupe/cap logic, and HTTP via respx.
import httpx
import pytest
import respx

from tedsbot.config import ErrorsConfig, PassConfig, PollConfig
from tedsbot.providers.base import TicketRef
from tedsbot.providers.sentry import SentryErrorSource, build_passes


def _cfg(**poll: object) -> ErrorsConfig:
    return ErrorsConfig(
        kind="sentry", org="example-org", project_id="123", token="tok",
        environment="production", poll=PollConfig(**poll),
    )


def test_mcp_server_uses_npx_and_org() -> None:
    server = SentryErrorSource(_cfg()).mcp_server()
    assert server.name == "sentry"
    assert server.config["command"] == "npx"
    assert "--organization-slug=example-org" in server.config["args"]
    assert server.config["env"]["SENTRY_ACCESS_TOKEN"] == "tok"
    assert server.allowed_tools == ["mcp__sentry__*"]


def test_prompt_facts() -> None:
    facts = SentryErrorSource(_cfg()).prompt_facts()
    assert facts["sentry_org"] == "example-org"
    assert facts["sentry_region_url"] == "https://us.sentry.io"
    assert facts["sentry_environment"] == "production"


def test_knowledge_is_shipped_markdown() -> None:
    text = SentryErrorSource(_cfg()).knowledge()
    assert text.startswith("## Sentry")
    assert "organization slug" in text


def test_build_passes_default_order_and_queries() -> None:
    passes = build_passes(PollConfig())
    labels = [p.label for p in passes]
    assert labels == ["new-error", "escalating", "performance", "chronic"]
    new = passes[0]
    assert "firstSeen:-30m" in new.query and "timesSeen:>=3" in new.query
    assert "level:[error,fatal]" in new.query and new.env_mode == "param"
    perf = passes[2]
    assert "issue.category:[db_query,http_client,frontend,mobile,metric]" in perf.query
    assert perf.env_mode == "check" and "timesSeen:>=10" in perf.query


def test_build_passes_respects_enabled_flags() -> None:
    passes = build_passes(PollConfig(escalating=PassConfig(enabled=False), chronic=PassConfig(enabled=False)))
    assert [p.label for p in passes] == ["new-error", "performance"]


@respx.mock
def test_fetch_issues_scopes_environment_for_param_passes() -> None:
    route = respx.get("https://us.sentry.io/api/0/organizations/example-org/issues/").mock(
        return_value=httpx.Response(200, json=[{"id": "1", "shortId": "APP-1", "title": "boom", "permalink": "https://s/1"}])
    )
    src = SentryErrorSource(_cfg())
    issues = src.fetch_issues(build_passes(PollConfig())[0])
    assert issues[0]["shortId"] == "APP-1"
    assert route.calls[0].request.url.params["environment"] == "production"
    assert route.calls[0].request.headers["Authorization"] == "Bearer tok"


@respx.mock
def test_issue_is_production_fails_closed() -> None:
    respx.get("https://us.sentry.io/api/0/organizations/example-org/issues/9/tags/environment/").mock(
        return_value=httpx.Response(500)
    )
    assert SentryErrorSource(_cfg()).issue_is_production({"id": "9"}) is False


@respx.mock
def test_poll_dedupes_across_passes_and_caps() -> None:
    def _issues(request: httpx.Request) -> httpx.Response:
        q = request.url.params["query"]
        if "firstSeen" in q:
            body = [{"id": "1", "shortId": "APP-1", "title": "a", "permalink": "u1"}]
        elif "escalating" in q:
            body = [{"id": "1", "shortId": "APP-1", "title": "a", "permalink": "u1"},
                    {"id": "2", "shortId": "APP-2", "title": "b", "permalink": "u2"}]
        else:
            body = [{"id": "3", "shortId": "APP-3", "title": "c", "permalink": "u3"}]
        return httpx.Response(200, json=body)

    respx.get("https://us.sentry.io/api/0/organizations/example-org/issues/").mock(side_effect=_issues)
    respx.get(url__regex=r".*/tags/environment/$").mock(
        return_value=httpx.Response(200, json={"topValues": [{"value": "production"}]})
    )
    src = SentryErrorSource(_cfg(max_issues_per_cycle=2))
    out = src.poll()
    assert [c.short_id for c in out] == ["APP-1", "APP-2"]
    assert out[0].pass_label == "new-error"


def test_already_ticketed_uses_ticket_search() -> None:
    class FakeTickets:
        def search_text(self, text: str) -> list[TicketRef]:
            return [TicketRef(key="APP-9", url="u", status="Open", summary="x")] if text == "APP-1" else []

    src = SentryErrorSource(_cfg())
    assert src.already_ticketed("APP-1", FakeTickets()) is True
    assert src.already_ticketed("APP-2", FakeTickets()) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_sentry_provider.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_passes'`

- [ ] **Step 3: Write the provider and its knowledge file**

`src/tedsbot/providers/knowledge/sentry.md`:
```markdown
## Sentry

- The Sentry MCP token cannot list organizations; always pass the
  organization slug explicitly (it is in the run facts as `sentry_org`).
- Environment names are case-sensitive in Sentry searches. Use the value
  in `sentry_environment` exactly.
- Performance and N+1 issues have no `level`; searches filtered by level
  never return them.
- The issues API does not expand the `issue.category:performance` alias;
  use the explicit category list.
- First-seen and last-seen on the issue are authoritative for the
  timeline. Reconcile them with git history before naming a root cause.
```

`src/tedsbot/providers/sentry.py`:
```python
# ABOUTME: Sentry error-source provider: MCP server config, prompt facts,
# ABOUTME: provider knowledge, and the deterministic poll passes.
from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import resources
from typing import Literal

import httpx

from tedsbot.config import ErrorsConfig, PollConfig
from tedsbot.errors import ProviderError
from tedsbot.providers.base import ErrorCandidate, McpServer, Ticketing
from tedsbot.registry import register

log = logging.getLogger(__name__)

PERF_CATEGORIES = "db_query,http_client,frontend,mobile,metric"
FETCH_LIMIT = 25


@dataclass(frozen=True)
class SentryPass:
    label: str
    query: str
    sort: str
    env_mode: Literal["param", "check"]


def build_passes(poll: PollConfig) -> list[SentryPass]:
    levels = ",".join(poll.levels)
    out = [
        SentryPass(
            "new-error",
            f"is:unresolved firstSeen:{poll.new_error.first_seen} "
            f"timesSeen:>={poll.new_error.min_times_seen} level:[{levels}]",
            "new",
            "param",
        )
    ]
    if poll.escalating.enabled:
        out.append(SentryPass(
            "escalating",
            f"is:unresolved is:escalating timesSeen:>={poll.escalating.min_times_seen} level:[{levels}]",
            "freq",
            "param",
        ))
    if poll.performance.enabled:
        out.append(SentryPass(
            "performance",
            f"is:unresolved issue.category:[{PERF_CATEGORIES}] timesSeen:>={poll.performance.min_times_seen}",
            "freq",
            "check",
        ))
    if poll.chronic.enabled:
        out.append(SentryPass(
            "chronic",
            f"is:unresolved timesSeen:>={poll.chronic.min_times_seen} level:[{levels}]",
            "freq",
            "param",
        ))
    return out


class SentryErrorSource:
    def __init__(self, cfg: ErrorsConfig) -> None:
        self.cfg = cfg
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {cfg.token}", "Accept": "application/json"},
            timeout=30,
        )

    def mcp_server(self) -> McpServer:
        return McpServer(
            name="sentry",
            config={
                "command": "npx",
                "args": ["-y", "@sentry/mcp-server@latest", f"--organization-slug={self.cfg.org}"],
                "env": {"SENTRY_ACCESS_TOKEN": self.cfg.token},
            },
            allowed_tools=["mcp__sentry__*"],
        )

    def prompt_facts(self) -> dict[str, str]:
        return {
            "sentry_org": self.cfg.org,
            "sentry_region_url": self.cfg.region_url,
            "sentry_environment": self.cfg.environment,
            "sentry_project_id": self.cfg.project_id,
        }

    def knowledge(self) -> str:
        return resources.files("tedsbot.providers.knowledge").joinpath("sentry.md").read_text()

    def _org_url(self, tail: str) -> str:
        return f"{self.cfg.region_url}/api/0/organizations/{self.cfg.org}/{tail}"

    def fetch_issues(self, sentry_pass: SentryPass) -> list[dict]:
        params: dict[str, str] = {
            "project": self.cfg.project_id,
            "query": sentry_pass.query,
            "sort": sentry_pass.sort,
            "statsPeriod": self.cfg.poll.stats_period,
            "limit": str(FETCH_LIMIT),
        }
        if sentry_pass.env_mode == "param":
            params["environment"] = self.cfg.environment
        resp = self._client.get(self._org_url("issues/"), params=params)
        if resp.status_code != 200:
            raise ProviderError(f"sentry issues search {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        if not isinstance(data, list):
            raise ProviderError(f"unexpected Sentry response: {str(data)[:200]}")
        return data

    def issue_is_production(self, issue: dict) -> bool:
        issue_id = issue.get("id")
        if not issue_id:
            return False
        try:
            resp = self._client.get(self._org_url(f"issues/{issue_id}/tags/environment/"))
            if resp.status_code != 200:
                return False
            values = {v.get("value") for v in resp.json().get("topValues", [])}
            return self.cfg.environment in values
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            log.warning("environment check failed for %s: %s", issue.get("shortId"), exc)
            return False

    def poll(self) -> list[ErrorCandidate]:
        seen: set[str] = set()
        out: list[ErrorCandidate] = []
        cap = self.cfg.poll.max_issues_per_cycle
        for sentry_pass in build_passes(self.cfg.poll):
            for issue in self.fetch_issues(sentry_pass):
                short_id = issue.get("shortId")
                if not short_id or short_id in seen:
                    continue
                if sentry_pass.env_mode == "check" and not self.issue_is_production(issue):
                    continue
                seen.add(short_id)
                out.append(ErrorCandidate(
                    short_id=short_id,
                    issue_id=str(issue.get("id", "")),
                    title=issue.get("title", ""),
                    pass_label=sentry_pass.label,
                    permalink=issue.get("permalink", ""),
                ))
                if len(out) >= cap:
                    return out
        return out

    def already_ticketed(self, short_id: str, tickets: Ticketing) -> bool:
        return bool(tickets.search_text(short_id))


register("errors", "sentry", SentryErrorSource)
```

Also add `src/tedsbot/providers/knowledge/__init__.py` (two ABOUTME lines, empty otherwise) so `importlib.resources` can find the package, and add to `pyproject.toml` under `[tool.hatch.build.targets.wheel]`: nothing extra is needed because `.md` files inside the package directory are included by hatchling.

- [ ] **Step 4: Run unit tests to verify they pass**

Run: `uv run pytest tests/unit/test_sentry_provider.py -v`
Expected: 9 passed

- [ ] **Step 5: Write the integration test with a VCR cassette**

`tests/integration/test_sentry_poll.py`:
```python
# ABOUTME: Integration test for Sentry polling against a recorded cassette.
# ABOUTME: Re-record with SENTRY_AUTH_TOKEN, SENTRY_ORG, SENTRY_PROJECT_ID set and --record-mode=once.
import os
from pathlib import Path

import pytest
import vcr

from tedsbot.config import ErrorsConfig
from tedsbot.providers.sentry import SentryErrorSource

CASSETTES = Path(__file__).parent / "cassettes"
recorder = vcr.VCR(
    cassette_library_dir=str(CASSETTES),
    filter_headers=["authorization"],
    record_mode=os.environ.get("VCR_RECORD_MODE", "none"),
)


@recorder.use_cassette("sentry_poll.yaml")
def test_poll_returns_candidates_with_pass_labels() -> None:
    cfg = ErrorsConfig(
        kind="sentry",
        org=os.environ.get("SENTRY_ORG", "example-org"),
        project_id=os.environ.get("SENTRY_PROJECT_ID", "123"),
        token=os.environ.get("SENTRY_AUTH_TOKEN", "recorded"),
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
    )
    out = SentryErrorSource(cfg).poll()
    assert all(c.short_id and c.pass_label for c in out)
    assert len(out) <= cfg.poll.max_issues_per_cycle
```

Record the cassette once against a real Sentry org (any org the token can read), then scrub the org slug and project id in the cassette file to `example-org` / `123` with `sed`, and set the test defaults to match. Commit the scrubbed cassette.

Run to record: `SENTRY_AUTH_TOKEN=... SENTRY_ORG=... SENTRY_PROJECT_ID=... VCR_RECORD_MODE=once uv run pytest tests/integration/test_sentry_poll.py -v`
Then scrub: `sed -i 's/<real-org>/example-org/g; s/<real-project-id>/123/g' tests/integration/cassettes/sentry_poll.yaml`
Then verify replay: `uv run pytest tests/integration/test_sentry_poll.py -v` → 1 passed

- [ ] **Step 6: Commit**

```bash
git add src/tedsbot/providers/sentry.py src/tedsbot/providers/knowledge tests/unit/test_sentry_provider.py tests/integration
git commit -m "feat: sentry provider with poll passes and MCP config"
```

---

### Task 5: Jira provider

**Files:**
- Replace: `src/tedsbot/providers/jira.py`
- Create: `src/tedsbot/providers/knowledge/jira.md`, `tests/unit/test_jira_provider.py`, `tests/integration/test_jira_ops.py`

**Interfaces:**
- Consumes: `TicketsConfig`, `McpServer`, `TicketRef`.
- Produces: `JiraTicketing(cfg)` implementing `Ticketing`. REST base is `{cfg.url}/rest/api/3`. Auth header is `Authorization: Bearer {token}`. `untriaged_bugs(bot_marker)` returns Bugs in `statuses.intake` whose comments do not contain `bot_marker`. `approved_for_fix()` returns tickets in `statuses.fix_approved`. `statuses_exist(names)` returns the subset of names not found on the project.

- [ ] **Step 1: Write the failing unit tests**

`tests/unit/test_jira_provider.py`:
```python
# ABOUTME: Unit tests for the Jira provider: MCP config, prompt facts, JQL
# ABOUTME: construction, and REST operations via respx.
import httpx
import pytest
import respx

from tedsbot.config import TicketFields, TicketLabels, TicketStatuses, TicketsConfig
from tedsbot.providers.jira import JiraTicketing

BASE = "https://example.atlassian.net/rest/api/3"


def _cfg() -> TicketsConfig:
    return TicketsConfig(
        kind="jira", url="https://example.atlassian.net", cloud_id="cid", project="APP",
        token="tok", bug_issue_type_id="10009",
        fields=TicketFields(qa_notes="customfield_10075", qa_instructions="customfield_10073"),
        statuses=TicketStatuses(intake="To Triage", triage_target="Dev Team Review",
                                fix_approved="Approved For Fix", in_progress="In Progress",
                                code_review="Code Review"),
        labels=TicketLabels(),
    )


def _issue(key: str, status: str, comments: list[str] | None = None) -> dict:
    return {
        "key": key,
        "fields": {
            "summary": f"summary {key}",
            "status": {"name": status},
            "comment": {"comments": [{"body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": c}]}]}} for c in (comments or [])]},
        },
    }


def test_mcp_server_uses_uvx_mcp_atlassian() -> None:
    server = JiraTicketing(_cfg()).mcp_server()
    assert server.name == "atlassian"
    assert server.config["command"] == "uvx" and server.config["args"] == ["mcp-atlassian"]
    env = server.config["env"]
    assert env["JIRA_URL"] == "https://example.atlassian.net"
    assert env["ATLASSIAN_OAUTH_CLOUD_ID"] == "cid"
    assert env["ATLASSIAN_OAUTH_ACCESS_TOKEN"] == "tok"
    assert server.allowed_tools == ["mcp__atlassian__*"]


def test_prompt_facts_cover_ids_statuses_labels() -> None:
    facts = JiraTicketing(_cfg()).prompt_facts()
    assert facts["jira_url"] == "https://example.atlassian.net"
    assert facts["jira_project"] == "APP"
    assert facts["jira_cloud_id"] == "cid"
    assert facts["bug_issue_type_id"] == "10009"
    assert facts["qa_notes_field"] == "customfield_10075"
    assert facts["qa_instructions_field"] == "customfield_10073"
    assert facts["status_triage_target"] == "Dev Team Review"
    assert facts["status_code_review"] == "Code Review"
    assert facts["label_from_errors"] == "sentry-triage"
    assert facts["label_insufficient_repro"] == "insufficient-repro"


def test_knowledge_mentions_adf_and_transitions() -> None:
    text = JiraTicketing(_cfg()).knowledge()
    assert "Atlassian Document Format" in text and "transitions" in text


@respx.mock
def test_untriaged_bugs_filters_by_bot_marker() -> None:
    respx.get(f"{BASE}/search/jql").mock(return_value=httpx.Response(200, json={
        "issues": [_issue("APP-1", "To Triage"), _issue("APP-2", "To Triage", ["[tedsbot] analysis"])]
    }))
    out = JiraTicketing(_cfg()).untriaged_bugs("[tedsbot]")
    assert [t.key for t in out] == ["APP-1"]
    assert out[0].url == "https://example.atlassian.net/browse/APP-1"


@respx.mock
def test_approved_for_fix_jql() -> None:
    route = respx.get(f"{BASE}/search/jql").mock(return_value=httpx.Response(200, json={"issues": [_issue("APP-5", "Approved For Fix")]}))
    out = JiraTicketing(_cfg()).approved_for_fix()
    assert out[0].key == "APP-5"
    assert 'status = "Approved For Fix"' in route.calls[0].request.url.params["jql"]


@respx.mock
def test_status_of() -> None:
    respx.get(f"{BASE}/issue/APP-3").mock(return_value=httpx.Response(200, json=_issue("APP-3", "Done")))
    assert JiraTicketing(_cfg()).status_of("APP-3") == "Done"


@respx.mock
def test_search_text_escapes_quotes() -> None:
    route = respx.get(f"{BASE}/search/jql").mock(return_value=httpx.Response(200, json={"issues": []}))
    JiraTicketing(_cfg()).search_text('APP-1 "quoted"')
    assert 'text ~ "APP-1 \\"quoted\\""' in route.calls[0].request.url.params["jql"]


@respx.mock
def test_comment_posts_adf() -> None:
    route = respx.post(f"{BASE}/issue/APP-1/comment").mock(return_value=httpx.Response(201, json={}))
    JiraTicketing(_cfg()).comment("APP-1", "hello\nworld")
    body = route.calls[0].request.content
    assert b'"type": "doc"' in body and b"hello" in body and b"world" in body


@respx.mock
def test_statuses_exist_reports_missing() -> None:
    respx.get(f"{BASE}/project/APP/statuses").mock(return_value=httpx.Response(200, json=[
        {"name": "Bug", "statuses": [{"name": "To Triage"}, {"name": "Done"}]}
    ]))
    missing = JiraTicketing(_cfg()).statuses_exist(["To Triage", "Dev Team Review"])
    assert missing == ["Dev Team Review"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_jira_provider.py -v`
Expected: FAIL with `NotImplementedError` / assertion errors from the stub

- [ ] **Step 3: Write the provider and its knowledge file**

`src/tedsbot/providers/knowledge/jira.md`:
```markdown
## Jira

- Rich-text custom fields (QA Notes, QA Instructions) require an
  Atlassian Document Format object, not a plain string. Minimal skeleton:
  `{"type":"doc","version":1,"content":[{"type":"paragraph","content":[{"type":"text","text":"..."}]}]}`.
  The `contentFormat` parameter converts the system description only.
- Editing a custom field replaces it; resend the full document.
- Always fetch available transitions live before transitioning, and match
  on the target status name (`to.name`), not the transition label. Labels
  and target names differ on some workflows.
- Never move a ticket backwards. If it is already at or past the target
  status, leave it.
- Comments are written as ADF too. Write real line breaks as separate
  paragraphs, never literal `\n` escape sequences.
- Ticket summaries describe the user-visible symptom in plain language,
  with the exception type in trailing parentheses.
```

`src/tedsbot/providers/jira.py`:
```python
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
```

- [ ] **Step 4: Run unit tests to verify they pass**

Run: `uv run pytest tests/unit/test_jira_provider.py -v`
Expected: 10 passed

- [ ] **Step 5: Integration test with cassette**

`tests/integration/test_jira_ops.py`:
```python
# ABOUTME: Integration tests for Jira REST operations against recorded cassettes.
# ABOUTME: Re-record with JIRA_URL, ATLASSIAN_API_TOKEN, JIRA_PROJECT set and VCR_RECORD_MODE=once.
import os
from pathlib import Path

import vcr

from tedsbot.config import TicketFields, TicketStatuses, TicketsConfig
from tedsbot.providers.jira import JiraTicketing

CASSETTES = Path(__file__).parent / "cassettes"
recorder = vcr.VCR(
    cassette_library_dir=str(CASSETTES),
    filter_headers=["authorization"],
    record_mode=os.environ.get("VCR_RECORD_MODE", "none"),
)


def _cfg() -> TicketsConfig:
    return TicketsConfig(
        kind="jira",
        url=os.environ.get("JIRA_URL", "https://example.atlassian.net"),
        cloud_id=os.environ.get("ATLASSIAN_CLOUD_ID", "cid"),
        project=os.environ.get("JIRA_PROJECT", "APP"),
        token=os.environ.get("ATLASSIAN_API_TOKEN", "recorded"),
        bug_issue_type_id="10009",
        fields=TicketFields(qa_notes="customfield_10075", qa_instructions="customfield_10073"),
        statuses=TicketStatuses(intake="To Triage", triage_target="Dev Team Review",
                                fix_approved="Approved For Fix", in_progress="In Progress",
                                code_review="Code Review"),
    )


@recorder.use_cassette("jira_statuses.yaml")
def test_statuses_exist_finds_configured_statuses() -> None:
    missing = JiraTicketing(_cfg()).statuses_exist(["To Triage", "Definitely Not A Status"])
    assert missing == ["Definitely Not A Status"]


@recorder.use_cassette("jira_search.yaml")
def test_search_text_returns_refs() -> None:
    out = JiraTicketing(_cfg()).search_text("triage")
    assert all(t.key and t.url.endswith(t.key) for t in out)
```

Record against a real site, then scrub the hostname and project key to `example.atlassian.net` / `APP` with `sed` and commit the cassettes. Verify replay passes.

- [ ] **Step 6: Commit**

```bash
git add src/tedsbot/providers/jira.py src/tedsbot/providers/knowledge/jira.md tests/unit/test_jira_provider.py tests/integration
git commit -m "feat: jira provider with REST ops, MCP config, ADF helpers"
```

---

### Task 6: Slack notifier

**Files:**
- Replace: `src/tedsbot/providers/slack.py`
- Create: `tests/unit/test_notify.py`

**Interfaces:**
- Consumes: `NotifyConfig`, `McpServer`.
- Produces: `SlackWebhookNotifier(cfg)` with `post(text: str) -> None` (raises `ProviderError` on non-2xx) and `sdk_server() -> McpServer` whose `config` is the object returned by `create_sdk_mcp_server(name="notify", version=__version__, tools=[...])` and whose `allowed_tools == ["mcp__notify__notify_slack"]`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_notify.py`:
```python
# ABOUTME: Tests the Slack webhook notifier: post payload, failure handling,
# ABOUTME: and the in-process SDK tool it exposes to the agent.
import httpx
import pytest
import respx

from tedsbot.config import NotifyConfig
from tedsbot.errors import ProviderError
from tedsbot.providers.slack import SlackWebhookNotifier

URL = "https://hooks.slack.example/T/B/X"


@respx.mock
def test_post_sends_text_json() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, text="ok"))
    SlackWebhookNotifier(NotifyConfig(kind="slack_webhook", url=URL)).post("🟢 APP-1 — fixed")
    assert route.calls[0].request.headers["content-type"] == "application/json"
    assert b"APP-1" in route.calls[0].request.content


@respx.mock
def test_post_raises_on_failure() -> None:
    respx.post(URL).mock(return_value=httpx.Response(500, text="no"))
    with pytest.raises(ProviderError, match="500"):
        SlackWebhookNotifier(NotifyConfig(kind="slack_webhook", url=URL)).post("x")


def test_sdk_server_exposes_notify_tool() -> None:
    server = SlackWebhookNotifier(NotifyConfig(kind="slack_webhook", url=URL)).sdk_server()
    assert server.name == "notify"
    assert server.allowed_tools == ["mcp__notify__notify_slack"]
    assert server.config["type"] == "sdk"


@respx.mock
async def test_sdk_tool_posts_and_returns_text() -> None:
    respx.post(URL).mock(return_value=httpx.Response(200, text="ok"))
    notifier = SlackWebhookNotifier(NotifyConfig(kind="slack_webhook", url=URL))
    result = await notifier.notify_tool.handler({"text": "hello"})
    assert result["content"][0]["text"] == "posted"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_notify.py -v`
Expected: FAIL with `NotImplementedError` from the stub

- [ ] **Step 3: Write the notifier**

`src/tedsbot/providers/slack.py`:
```python
# ABOUTME: Slack incoming-webhook notifier: posts run summaries from Python and
# ABOUTME: exposes an in-process SDK tool so the agent can post mid-run.
from __future__ import annotations

from typing import Any

import httpx
from claude_agent_sdk import create_sdk_mcp_server, tool

from tedsbot import __version__
from tedsbot.config import NotifyConfig
from tedsbot.errors import ProviderError
from tedsbot.providers.base import McpServer
from tedsbot.registry import register


class SlackWebhookNotifier:
    def __init__(self, cfg: NotifyConfig) -> None:
        self.cfg = cfg
        notifier = self

        @tool("notify_slack", "Post a short status line to the team's Slack channel.", {"text": str})
        async def notify_slack(args: dict[str, Any]) -> dict[str, Any]:
            try:
                notifier.post(str(args["text"]))
            except ProviderError as exc:
                return {"content": [{"type": "text", "text": f"slack post failed: {exc}"}], "is_error": True}
            return {"content": [{"type": "text", "text": "posted"}]}

        self.notify_tool = notify_slack

    def post(self, text: str) -> None:
        resp = httpx.post(self.cfg.url, json={"text": text}, timeout=15)
        if resp.status_code // 100 != 2:
            raise ProviderError(f"slack webhook {resp.status_code}: {resp.text[:200]}")

    def sdk_server(self) -> McpServer:
        server = create_sdk_mcp_server(name="notify", version=__version__, tools=[self.notify_tool])
        return McpServer(name="notify", config=server, allowed_tools=["mcp__notify__notify_slack"])


register("notify", "slack_webhook", SlackWebhookNotifier)
```

If `server.config["type"]` is not `"sdk"` in the object returned by `create_sdk_mcp_server` on the installed version, inspect it with `python -c "from claude_agent_sdk import create_sdk_mcp_server; print(create_sdk_mcp_server(name='x', version='1', tools=[]))"` and adjust the assertion to the real discriminator key. The `@tool` decorator returns an object with a `.handler` attribute in 0.2.x; if the attribute name differs, print `dir(self.notify_tool)` and adjust the test.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_notify.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/tedsbot/providers/slack.py tests/unit/test_notify.py
git commit -m "feat: slack webhook notifier with in-process SDK tool"
```

---

### Task 7: Knowledge assembly and shipped methodology

**Files:**
- Create: `src/tedsbot/knowledge.py`, `knowledge/triage-method.md`, `knowledge/recommendation-tiers.md`, `knowledge/replication-steps.md`, `tests/unit/test_knowledge.py`

**Interfaces:**
- Produces: `knowledge.assemble_knowledge(provider_sections: list[str], consumer_dir: Path | None, warn_kb: int, extra_sections: list[str] = ()) -> KnowledgeBlock` where `KnowledgeBlock` is a dataclass `text: str`, `size_kb: float`, `warnings: list[str]`. Order: provider sections, then worker-shipped files (sorted by name), then consumer files (sorted), then extra sections. Worker-shipped files are located via `importlib.resources` from the package `tedsbot.shipped_knowledge`, so move the `knowledge/` directory content into `src/tedsbot/shipped_knowledge/` (with an `__init__.py`) and keep a top-level `knowledge/README.md` pointing there. Each file section is prefixed with `## <file stem>` when the file does not already begin with a heading.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_knowledge.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_knowledge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tedsbot.knowledge'`

- [ ] **Step 3: Write the shipped knowledge files and the assembler**

`src/tedsbot/shipped_knowledge/__init__.py`: two ABOUTME lines only.

`src/tedsbot/shipped_knowledge/triage-method.md`:
```markdown
## triage-method

1. **Fetch the error or ticket.** Extract exception type, message, stack
   trace, top in-app frame and its callers; or the reporter's steps,
   expected vs actual, and where in the product it happens.
2. **Read the code** behind the implicated frames or feature. Understand
   what state makes it fail.
3. **Check recent history.** `git log --since="14 days ago" -p -- <files>`
   on the implicated files. A recent change touching the failing line is
   the strongest signal.
4. **Reconcile the timeline.** The code history and the error's first-seen
   and last-seen must tell one story. Trace when the failing code and any
   guards appeared with `git log -S '<exact code>' -- <file>`. Never
   characterise a commit without reading its diff for the cited lines
   (`git show <hash> -- <file>`). If first-seen predates the suspect
   change, the error has more than one chapter; report the chapters you
   can verify and flag any remaining discrepancy instead of smoothing it.
5. **Dedupe against the ticketing system** by exception message and by the
   error label:
   - Open match: comment the new occurrence stats and STOP (⚪ duplicate).
   - Closed as Won't Do: comment stats, respect the decision, STOP (⚪).
   - Closed as Done: this is a regression; create a NEW ticket linked
     "relates to" the old one and cover what un-fixed it.
   - No match: continue.
6. **Write the analysis** in this exact structure:
   - Line 1: the recommendation tier.
   - Root cause: what fails and why, citing `file:line`.
   - Evidence: frames read, commits examined (hashes), event frequency and
     first-seen.
   - Replication steps (see replication-steps).
   - Suggested fix: files to change and how; a sketch, not a diff.
   - Link to the source error.
7. **Land it**: create or comment the ticket, populate the QA notes field
   with the tier line plus a 2–3 sentence root-cause summary, transition
   to the triage target status. Never move a ticket past that status.
8. **Write the run summary file** at the path given in the run
   instructions.

Rules: honesty over confidence; cite evidence for every claim; never edit,
commit, or push any repository file during triage.
```

`src/tedsbot/shipped_knowledge/recommendation-tiers.md`:
```markdown
## recommendation-tiers

Every analysis opens with exactly one of:

- 🟢 low-risk fix — root cause is clear and the fix is small and contained
- 🟡 needs review — plausible root cause but the fix has design implications
- ⚪ not a code bug — config, data, third-party outage, expected behaviour,
  or a duplicate
- 🔴 insufficient context — could not establish a credible root cause

A wrong confident analysis costs more than an honest shrug. Use 🔴.
```

`src/tedsbot/shipped_knowledge/replication-steps.md`:
```markdown
## replication-steps

Replication steps are a numbered user journey a tester can follow without
reading code: which role to log in as, the navigation path, the action
that triggers the error, what the user observes (or that the failure is
silent), and where the error is visible (browser console, error tracker,
server log). Derive them from the event's URL and user context and the
code path. Mark any inferred step "(inferred)".
```

`knowledge/README.md` (top level):
```markdown
Shipped triage methodology lives in `src/tedsbot/shipped_knowledge/` so it
installs with the package. Put your team's own knowledge in the directory
named by `agent.knowledge_dir` in your config.
```

`src/tedsbot/knowledge.py`:
```python
# ABOUTME: Assembles the three knowledge tiers (provider, shipped, consumer)
# ABOUTME: into one markdown block for the system prompt, with size warnings.
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path


@dataclass
class KnowledgeBlock:
    text: str
    size_kb: float
    warnings: list[str] = field(default_factory=list)


def _section(stem: str, body: str) -> str:
    body = body.strip()
    if body.startswith("#"):
        return body
    return f"## {stem}\n\n{body}"


def _shipped_sections() -> list[str]:
    pkg = resources.files("tedsbot.shipped_knowledge")
    files = sorted(p for p in pkg.iterdir() if p.name.endswith(".md"))
    return [_section(Path(p.name).stem, p.read_text()) for p in files]


def _consumer_sections(consumer_dir: Path | None, warnings: list[str]) -> list[str]:
    if consumer_dir is None:
        return []
    if not consumer_dir.is_dir():
        warnings.append(f"knowledge_dir {consumer_dir} does not exist; continuing without it")
        return []
    return [_section(p.stem, p.read_text()) for p in sorted(consumer_dir.glob("*.md"))]


def assemble_knowledge(
    provider_sections: Sequence[str],
    consumer_dir: Path | None,
    warn_kb: int,
    extra_sections: Sequence[str] = (),
) -> KnowledgeBlock:
    warnings: list[str] = []
    parts = [s.strip() for s in provider_sections]
    parts += _shipped_sections()
    parts += _consumer_sections(consumer_dir, warnings)
    parts += [s.strip() for s in extra_sections]
    text = "\n\n".join(p for p in parts if p)
    size_kb = len(text.encode()) / 1024
    if size_kb > warn_kb:
        warnings.append(f"knowledge block is {size_kb:.0f} KB, exceeds {warn_kb} KB")
    return KnowledgeBlock(text=text, size_kb=size_kb, warnings=warnings)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_knowledge.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/tedsbot/knowledge.py src/tedsbot/shipped_knowledge knowledge/README.md tests/unit/test_knowledge.py
git commit -m "feat: three-tier knowledge assembly and shipped methodology"
```

---

### Task 8: Prompt templates

**Files:**
- Create: `src/tedsbot/prompts/__init__.py`, `src/tedsbot/prompts/triage_sentry.md.j2`, `src/tedsbot/prompts/triage_ticket.md.j2`, `tests/unit/test_prompts.py`

**Interfaces:**
- Produces: `prompts.render_prompt(name: str, facts: dict[str, str], **inputs: str) -> str`. Templates are rendered with `jinja2.Environment(undefined=StrictUndefined)` so a missing fact fails loudly. Template names: `"triage_sentry"`, `"triage_ticket"`. Required inputs: `triage_sentry` needs `sentry_issue`, `summary_path`; `triage_ticket` needs `ticket_key`, `summary_path`. Both templates need every key from `SentryErrorSource.prompt_facts()` and `JiraTicketing.prompt_facts()`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_prompts.py`:
```python
# ABOUTME: Tests prompt rendering: required facts are substituted, missing
# ABOUTME: facts fail loudly, and each template carries its hard rules.
import pytest
from jinja2 import UndefinedError

from tedsbot.prompts import render_prompt

FACTS = {
    "sentry_org": "example-org", "sentry_region_url": "https://us.sentry.io",
    "sentry_environment": "production", "sentry_project_id": "123",
    "jira_url": "https://example.atlassian.net", "jira_project": "APP", "jira_cloud_id": "cid",
    "bug_issue_type_id": "10009", "qa_notes_field": "customfield_10075",
    "qa_instructions_field": "customfield_10073", "status_intake": "To Triage",
    "status_triage_target": "Dev Team Review", "status_fix_approved": "Approved For Fix",
    "status_in_progress": "In Progress", "status_code_review": "Code Review",
    "label_from_errors": "sentry-triage", "label_insufficient_repro": "insufficient-repro",
}


def test_triage_sentry_substitutes_facts_and_inputs() -> None:
    text = render_prompt("triage_sentry", FACTS, sentry_issue="APP-1", summary_path="/run/summary.json")
    assert "SENTRY_ISSUE: APP-1" in text
    assert "/run/summary.json" in text
    assert "example-org" in text and "Dev Team Review" in text and "sentry-triage" in text
    assert "NEVER modify repository code" in text


def test_triage_ticket_substitutes() -> None:
    text = render_prompt("triage_ticket", FACTS, ticket_key="APP-2", summary_path="/run/summary.json")
    assert "TICKET_KEY: APP-2" in text
    assert "insufficient-repro" in text and "customfield_10075" in text


def test_missing_fact_fails_loudly() -> None:
    facts = dict(FACTS)
    del facts["jira_project"]
    with pytest.raises(UndefinedError):
        render_prompt("triage_sentry", facts, sentry_issue="x", summary_path="y")


def test_unknown_template_fails() -> None:
    with pytest.raises(FileNotFoundError):
        render_prompt("nope", FACTS)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_prompts.py -v`
Expected: FAIL with `ImportError: cannot import name 'render_prompt'`

- [ ] **Step 3: Write the renderer and templates**

`src/tedsbot/prompts/__init__.py`:
```python
# ABOUTME: Renders the run-type prompt templates with provider facts and run
# ABOUTME: inputs. Missing variables raise so a bad config never reaches the agent.
from __future__ import annotations

from importlib import resources

from jinja2 import Environment, StrictUndefined

_env = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)


def render_prompt(name: str, facts: dict[str, str], **inputs: str) -> str:
    path = resources.files("tedsbot.prompts").joinpath(f"{name}.md.j2")
    if not path.is_file():
        raise FileNotFoundError(f"no prompt template named {name!r}")
    template = _env.from_string(path.read_text())
    return template.render(**facts, **inputs)
```

`src/tedsbot/prompts/triage_sentry.md.j2`:
```markdown
# Triage a new production error

You are the triage analyst running unattended. You analyse a
newly-fingerprinted production error and turn it into a structured ticket
a human can approve. You NEVER modify repository code in this run —
analysis only. Follow the triage-method, recommendation-tiers, and
replication-steps sections of your knowledge exactly.

## Run inputs

- SENTRY_ISSUE: {{ sentry_issue }}
- Write the run summary to: {{ summary_path }}

## Facts for this project

- Sentry org `{{ sentry_org }}` (region `{{ sentry_region_url }}`), project id `{{ sentry_project_id }}`, environment `{{ sentry_environment }}`.
- Ticketing: Jira site `{{ jira_url }}`, cloud id `{{ jira_cloud_id }}`, project `{{ jira_project }}`, Bug issue type id `{{ bug_issue_type_id }}`.
- QA Notes field: `{{ qa_notes_field }}` (ADF).
- Label for error-originated tickets: `{{ label_from_errors }}`.
- Target status after triage: **{{ status_triage_target }}**. Fetch transitions live and match on the target status name.

## Procedure

1. Fetch the error and its latest event with the Sentry tools.
2. Read the code behind the top in-app frames in this checkout.
3. Check recent history and reconcile the timeline per triage-method.
4. Dedupe against Jira (search the exception message and the label `{{ label_from_errors }}`); branch per triage-method step 5.
5. Write the analysis per triage-method step 6.
6. Create a Bug in `{{ jira_project }}`: summary in plain language naming the page/feature and the symptom, exception type in trailing parentheses; description = the full analysis as markdown; label `{{ label_from_errors }}`; populate `{{ qa_notes_field }}` with the tier line plus a 2–3 sentence root-cause summary.
7. Transition the ticket to **{{ status_triage_target }}**.
8. Write the run summary as JSON to `{{ summary_path }}`:

```json
{"kind": "triage_sentry", "ticket": "{{ jira_project }}-NNN", "ticket_url": "{{ jira_url }}/browse/{{ jira_project }}-NNN", "recommendation": "🟢", "status": null, "pr_url": null, "headline": "one-line root cause", "ok": true}
```

For a duplicate or a respected Won't Do, set recommendation "⚪", ticket to the existing key, and a headline that names it.

## Rules

- Honesty over confidence; 🔴 beats a wrong confident analysis.
- Cite `file:line`, commit hashes, and event counts for every claim.
- Do not edit, commit, or push any repository file. The only file you write is the summary.
- Do not transition any ticket beyond **{{ status_triage_target }}**; approval is a human action.
```

`src/tedsbot/prompts/triage_ticket.md.j2`:
```markdown
# Triage a team-reported bug

You are the triage analyst running unattended. A teammate logged a Bug;
you analyse it and attach a root-cause assessment a human can act on. You
NEVER modify repository code in this run — analysis only. Follow the
triage-method, recommendation-tiers, and replication-steps sections of
your knowledge exactly.

## Run inputs

- TICKET_KEY: {{ ticket_key }}
- Write the run summary to: {{ summary_path }}

## Facts for this project

- Jira site `{{ jira_url }}`, cloud id `{{ jira_cloud_id }}`, project `{{ jira_project }}`.
- QA Notes field: `{{ qa_notes_field }}` (ADF).
- Insufficient-repro label: `{{ label_insufficient_repro }}`.
- Target status after triage: **{{ status_triage_target }}**. Never move a ticket backwards; skip the transition if it is already there or further along.
- Error tracker: Sentry org `{{ sentry_org }}`, environment `{{ sentry_environment }}`.

## Procedure

1. Read the ticket: description, comments, attachment metadata.
2. Quality gate. A triagable report needs concrete reproduction steps, expected vs actual behaviour, and roughly where in the product it happens. If any are missing, do NOT spelunk the codebase on guesswork: comment asking for the specific missing items by name, add the label `{{ label_insufficient_repro }}`, write the summary with recommendation "🔴" and headline "insufficient repro — asked reporter for details", and STOP.
3. Cross-check Sentry for errors matching the reported behaviour (message text, view or endpoint, timeframe). A match converts "where does this live" into "why did this throw"; link it.
4. Analyse per triage-method steps 2–4 (use a 14-day history window).
5. Write the analysis as a ticket comment, prefixed with the marker `[tedsbot]` on its first line, per triage-method step 6.
6. Populate `{{ qa_notes_field }}` with the tier line plus a 2–3 sentence root-cause summary.
7. Transition to **{{ status_triage_target }}** if not already at or past it.
8. Write the run summary as JSON to `{{ summary_path }}`:

```json
{"kind": "triage_ticket", "ticket": "{{ ticket_key }}", "ticket_url": "{{ jira_url }}/browse/{{ ticket_key }}", "recommendation": "🟡", "status": null, "pr_url": null, "headline": "one-line root cause", "ok": true}
```

## Rules

- Honesty over confidence; 🔴 beats a wrong confident analysis.
- Cite `file:line`, commit hashes, and Sentry links for every claim.
- Do not edit, commit, or push any repository file. The only file you write is the summary.
- Do not transition any ticket beyond **{{ status_triage_target }}**.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_prompts.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/tedsbot/prompts tests/unit/test_prompts.py
git commit -m "feat: triage prompt templates with strict rendering"
```

---

### Task 9: Run summary model

**Files:**
- Create: `src/tedsbot/summary.py`, `tests/unit/test_summary.py`

**Interfaces:**
- Produces: `summary.RunSummary` (pydantic) with fields exactly as the spec: `kind: Literal["triage_sentry","triage_ticket","fix"]`, `ticket: str | None`, `ticket_url: str | None`, `recommendation: Literal["🟢","🟡","⚪","🔴"] | None`, `status: str | None`, `pr_url: str | None`, `headline: str`, `ok: bool`. `summary.read_summary(path: Path, kind: str, fallback_text: str) -> RunSummary` returns the parsed file or a fallback with `ok=False` and `headline=fallback_text[:200]`. `summary.slack_line(s: RunSummary, run_dir: Path) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_summary.py`:
```python
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
    assert s.ok is False and len(s.headline) == 200


def test_slack_line_for_success(tmp_path: Path) -> None:
    s = RunSummary(kind="triage_sentry", ticket="APP-1", ticket_url="https://j/APP-1",
                   recommendation="🟡", status=None, pr_url=None, headline="race in save", ok=True)
    assert slack_line(s, tmp_path) == "🟡 APP-1 — race in save\nhttps://j/APP-1"


def test_slack_line_for_failure_has_warning_and_run_dir(tmp_path: Path) -> None:
    s = RunSummary(kind="fix", ticket="APP-2", ticket_url=None, recommendation=None,
                   status=None, pr_url=None, headline="agent died", ok=False)
    line = slack_line(s, tmp_path)
    assert line.startswith("⚠️ fix APP-2 — agent died") and str(tmp_path) in line
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_summary.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tedsbot.summary'`

- [ ] **Step 3: Write summary.py**

```python
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


def read_summary(path: Path, kind: str, fallback_text: str) -> RunSummary:
    try:
        data = json.loads(path.read_text())
        return RunSummary.model_validate(data)
    except (OSError, ValueError, ValidationError):
        return RunSummary(kind=kind, headline=(fallback_text or "no output")[:200], ok=False)  # type: ignore[arg-type]


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_summary.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/tedsbot/summary.py tests/unit/test_summary.py
git commit -m "feat: run summary contract with fallback and slack line"
```

---

### Task 10: Runner — options assembly and run loop

**Files:**
- Create: `src/tedsbot/runner.py`, `tests/unit/test_runner_options.py`

**Interfaces:**
- Consumes: `Config`, providers via registry, `assemble_knowledge`, `render_prompt`, `read_summary`, `slack_line`.
- Produces:
  - `runner.RunSpec` dataclass: `kind: RunKind`, `prompt_name: str`, `inputs: dict[str, str]`, `max_turns: int`, `tools: list[str]`, `include_edit_tools: bool = False`, `run_id: str`.
  - `runner.new_run_dir(kind: str, target: str, home: Path | None = None) -> Path` creating `~/.tedsbot/runs/<UTC timestamp>-<kind>-<safe target>/`.
  - `runner.build_options(cfg: Config, spec: RunSpec, run_dir: Path) -> tuple[ClaudeAgentOptions, str]` returning the options and the rendered user prompt. The system prompt is `{"type":"preset","preset":"claude_code","append": <knowledge + "## Run directory" note>, "exclude_dynamic_sections": True}`. `permission_mode="dontAsk"`, `setting_sources=[]`, `cwd=cfg.repo.path`, `add_dirs=[run_dir]`, `model=cfg.agent.model`, `max_turns=spec.max_turns`, `mcp_servers` = every provider's server (name → config) plus the notifier SDK server, `allowed_tools` = `spec.tools + provider allowed tools + [f"Write({run_dir}/summary.json)"]`, `strict_mcp_config=True`. `env` carries `CLAUDE_CODE_OAUTH_TOKEN` and `ANTHROPIC_API_KEY` only if set in the process environment.
  - `TRIAGE_TOOLS = ["Read", "Grep", "Glob", "Bash(git log:*)", "Bash(git show:*)", "Bash(git blame:*)", "Bash(git diff:*)"]`.
  - `async runner.run(cfg: Config, spec: RunSpec, run_dir: Path) -> RunSummary`: runs `query()`, appends every message as JSON to `<run_dir>/transcript.jsonl` (via `dataclasses.asdict` where possible, else `repr`), captures final text from `ResultMessage.result`, reads the summary, posts `slack_line` through the notifier (catching `ProviderError` and logging), returns the summary. Exceptions from `query()` are caught, logged to the transcript, and produce an `ok=False` summary.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_runner_options.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_runner_options.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tedsbot.runner'`

- [ ] **Step 3: Write runner.py**

```python
# ABOUTME: Builds ClaudeAgentOptions from config and a RunSpec, runs the agent,
# ABOUTME: records the transcript, reads the summary, and notifies.
from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from tedsbot import registry
from tedsbot.config import Config
from tedsbot.errors import ProviderError
from tedsbot.knowledge import assemble_knowledge
from tedsbot.prompts import render_prompt
from tedsbot.summary import RunKind, RunSummary, read_summary, slack_line

log = logging.getLogger(__name__)

TRIAGE_TOOLS = [
    "Read", "Grep", "Glob",
    "Bash(git log:*)", "Bash(git show:*)", "Bash(git blame:*)", "Bash(git diff:*)",
]
AUTH_ENV = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")


@dataclass
class RunSpec:
    kind: RunKind
    prompt_name: str
    inputs: dict[str, str]
    max_turns: int
    tools: list[str]
    run_id: str
    include_edit_tools: bool = False
    extra_facts: dict[str, str] = field(default_factory=dict)


def new_run_dir(kind: str, target: str, home: Path | None = None) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", target).strip("-")[-40:]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = (home or Path.home()) / ".tedsbot" / "runs"
    run_dir = base / f"{stamp}-{kind}-{safe}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _project_claude_md(repo: Path) -> str | None:
    for candidate in (repo / "CLAUDE.md", repo / ".claude" / "CLAUDE.md"):
        if candidate.is_file():
            return f"## Project CLAUDE.md\n\n{candidate.read_text()}"
    return None


def build_options(cfg: Config, spec: RunSpec, run_dir: Path) -> tuple[ClaudeAgentOptions, str]:
    errors = registry.get_error_source(cfg.errors)
    tickets = registry.get_ticketing(cfg.tickets)
    notifier = registry.get_notifier(cfg.notify)
    providers = [errors, tickets]
    if cfg.logs is not None:
        providers.append(registry.get_log_store(cfg.logs))

    extra = []
    if spec.include_edit_tools and (claude_md := _project_claude_md(cfg.repo.path)):
        extra.append(claude_md)
    knowledge = assemble_knowledge(
        [p.knowledge() for p in providers], cfg.agent.knowledge_dir,
        cfg.agent.knowledge_size_warn_kb, extra_sections=extra,
    )
    for warning in knowledge.warnings:
        log.warning(warning)

    facts: dict[str, str] = {}
    for p in providers:
        facts.update(p.prompt_facts())
    facts.update(spec.extra_facts)
    summary_path = run_dir / "summary.json"
    prompt = render_prompt(spec.prompt_name, facts, summary_path=str(summary_path), **spec.inputs)

    mcp_servers: dict[str, Any] = {}
    allowed = list(spec.tools)
    for server in [p.mcp_server() for p in providers] + [notifier.sdk_server()]:
        mcp_servers[server.name] = server.config
        allowed.extend(server.allowed_tools)
    allowed.append(f"Write({summary_path})")

    append = (
        f"{knowledge.text}\n\n## Run directory\n\n"
        f"Your run directory is `{run_dir}`. The only file you may write is `{summary_path}`."
    )
    env = {k: os.environ[k] for k in AUTH_ENV if k in os.environ}
    options = ClaudeAgentOptions(
        system_prompt={
            "type": "preset", "preset": "claude_code",
            "append": append, "exclude_dynamic_sections": True,
        },
        permission_mode="dontAsk",
        setting_sources=[],
        strict_mcp_config=True,
        cwd=cfg.repo.path,
        add_dirs=[run_dir],
        model=cfg.agent.model,
        max_turns=spec.max_turns,
        mcp_servers=mcp_servers,
        allowed_tools=allowed,
        env=env,
    )
    return options, prompt


def _jsonable(message: Any) -> Any:
    if dataclasses.is_dataclass(message):
        try:
            return dataclasses.asdict(message)
        except TypeError:
            pass
    return {"repr": repr(message)}


async def run(cfg: Config, spec: RunSpec, run_dir: Path) -> RunSummary:
    options, prompt = build_options(cfg, spec, run_dir)
    (run_dir / "prompt.md").write_text(prompt)
    transcript = run_dir / "transcript.jsonl"
    final_text = ""
    with transcript.open("a") as fh:
        try:
            async for message in query(prompt=prompt, options=options):
                fh.write(json.dumps({"type": type(message).__name__, "data": _jsonable(message)}, default=str) + "\n")
                if isinstance(message, ResultMessage):
                    final_text = str(message.result or "")
        except Exception as exc:  # the SDK raises after yielding an error result
            log.exception("agent run failed")
            fh.write(json.dumps({"type": "exception", "data": repr(exc)}) + "\n")
            final_text = final_text or f"agent run failed: {exc}"
    summary = read_summary(run_dir / "summary.json", spec.kind, final_text)
    (run_dir / "summary.resolved.json").write_text(summary.model_dump_json(indent=2))
    try:
        registry.get_notifier(cfg.notify).post(slack_line(summary, run_dir))
    except ProviderError as exc:
        log.error("notification failed: %s", exc)
    return summary
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_runner_options.py -v`
Expected: 4 passed. If `ClaudeAgentOptions` rejects `strict_mcp_config` or `exclude_dynamic_sections` on the installed version, run `uv run python -c "import claude_agent_sdk, dataclasses; print([f.name for f in dataclasses.fields(claude_agent_sdk.ClaudeAgentOptions)])"` and adjust to the real field names; both exist in 0.2.152.

- [ ] **Step 5: Commit**

```bash
git add src/tedsbot/runner.py tests/unit/test_runner_options.py
git commit -m "feat: runner builds SDK options, records transcript, notifies"
```

---

### Task 11: `check` command

**Files:**
- Create: `src/tedsbot/commands/__init__.py`, `src/tedsbot/commands/check.py`, `tests/unit/test_check.py`
- Modify: `src/tedsbot/cli.py` (`_dispatch`)

**Interfaces:**
- Consumes: `load_config`, registry, `Ticketing.statuses_exist`, `McpServer`.
- Produces: `commands.check.run_check(config_path: Path, *, mcp_probe: Callable[[dict], bool] | None = None, gh_probe: Callable[[], bool] | None = None) -> CheckReport`; `CheckReport` dataclass `results: list[tuple[str, bool, str]]` and `ok: bool`. Default `mcp_probe` spawns the stdio server command with `subprocess.run([...], input=b"", timeout=20)` and treats a process that starts (returncode in {0} or is killed by timeout after starting) as reachable; default `gh_probe` runs `gh auth status` and returns `returncode == 0`. Checks, in order: config loads; checkout is a git repo on any branch; each provider MCP server reachable; `gh auth status`; ticket statuses exist; `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` present.
- `cli._dispatch` calls `run_check` for `check`, prints one line per result as `[ok] name — detail` / `[FAIL] name — detail`, returns 0 or 1.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_check.py`:
```python
# ABOUTME: Tests the check command with injected probes so no real servers or
# ABOUTME: gh are needed; asserts every check line and the overall verdict.
from pathlib import Path

import httpx
import pytest
import respx
import yaml

from tedsbot.cli import main
from tedsbot.commands.check import run_check


@pytest.fixture
def config_path(tmp_path: Path, config_dict: dict, env_tokens: None) -> Path:
    p = tmp_path / "tedsbot.yaml"
    p.write_text(yaml.safe_dump(config_dict))
    return p


@respx.mock
def test_all_green(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    respx.get("https://example.atlassian.net/rest/api/3/project/APP/statuses").mock(
        return_value=httpx.Response(200, json=[{"name": "Bug", "statuses": [
            {"name": n} for n in ["To Triage", "Dev Team Review", "Approved For Fix", "In Progress", "Code Review"]]}])
    )
    report = run_check(config_path, mcp_probe=lambda c: True, gh_probe=lambda: True)
    assert report.ok
    names = [r[0] for r in report.results]
    assert names == ["config", "checkout", "mcp:sentry", "mcp:atlassian", "gh auth", "ticket statuses", "claude auth"]


@respx.mock
def test_missing_status_and_gh_fail(config_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    respx.get("https://example.atlassian.net/rest/api/3/project/APP/statuses").mock(
        return_value=httpx.Response(200, json=[{"name": "Bug", "statuses": [{"name": "To Triage"}]}])
    )
    report = run_check(config_path, mcp_probe=lambda c: True, gh_probe=lambda: False)
    assert not report.ok
    failed = {r[0]: r[2] for r in report.results if not r[1]}
    assert "gh auth" in failed and "Dev Team Review" in failed["ticket statuses"]


def test_config_failure_short_circuits(tmp_path: Path) -> None:
    report = run_check(tmp_path / "absent.yaml", mcp_probe=lambda c: True, gh_probe=lambda: True)
    assert not report.ok and [r[0] for r in report.results] == ["config"]


def test_cli_check_exit_code(config_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr("tedsbot.commands.check._default_mcp_probe", lambda c: True)
    monkeypatch.setattr("tedsbot.commands.check._default_gh_probe", lambda: False)
    with respx.mock:
        respx.get("https://example.atlassian.net/rest/api/3/project/APP/statuses").mock(
            return_value=httpx.Response(200, json=[]))
        code = main(["-c", str(config_path), "check"])
    out = capsys.readouterr().out
    assert code == 1 and "[FAIL] gh auth" in out and "[ok] config" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_check.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tedsbot.commands'`

- [ ] **Step 3: Write the command and wire the CLI**

`src/tedsbot/commands/__init__.py`: two ABOUTME lines only.

`src/tedsbot/commands/check.py`:
```python
# ABOUTME: The `tedsbot check` command: validates config and confirms every
# ABOUTME: external dependency is reachable before any credits are spent.
from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from tedsbot import registry
from tedsbot.config import load_config
from tedsbot.errors import ConfigError, ProviderError


@dataclass
class CheckReport:
    results: list[tuple[str, bool, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.results)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.results.append((name, ok, detail))


def _default_mcp_probe(config: dict) -> bool:
    cmd = [config["command"], *config.get("args", [])]
    env = {**os.environ, **config.get("env", {})}
    try:
        subprocess.run(cmd, input=b"", capture_output=True, timeout=20, env=env, check=False)
        return True
    except subprocess.TimeoutExpired:
        return True  # a stdio server that waits on stdin has started successfully
    except (OSError, FileNotFoundError):
        return False


def _default_gh_probe() -> bool:
    try:
        return subprocess.run(["gh", "auth", "status"], capture_output=True, check=False).returncode == 0
    except OSError:
        return False


def run_check(
    config_path: Path,
    *,
    mcp_probe: Callable[[dict], bool] | None = None,
    gh_probe: Callable[[], bool] | None = None,
) -> CheckReport:
    mcp_probe = mcp_probe or _default_mcp_probe
    gh_probe = gh_probe or _default_gh_probe
    report = CheckReport()
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        report.add("config", False, str(exc))
        return report
    report.add("config", True, str(config_path))

    head = subprocess.run(["git", "-C", str(cfg.repo.path), "rev-parse", "--abbrev-ref", "HEAD"],
                          capture_output=True, text=True, check=False)
    report.add("checkout", head.returncode == 0, f"{cfg.repo.path} on {head.stdout.strip() or '?'}")

    providers = [registry.get_error_source(cfg.errors), registry.get_ticketing(cfg.tickets)]
    if cfg.logs is not None:
        providers.append(registry.get_log_store(cfg.logs))
    for provider in providers:
        server = provider.mcp_server()
        report.add(f"mcp:{server.name}", mcp_probe(server.config), " ".join([server.config["command"], *server.config.get("args", [])]))

    report.add("gh auth", gh_probe(), "gh auth status")

    tickets = providers[1]
    wanted = list(cfg.tickets.statuses.model_dump().values())
    try:
        missing = tickets.statuses_exist(wanted)
        report.add("ticket statuses", not missing, "all present" if not missing else f"missing: {', '.join(missing)}")
    except ProviderError as exc:
        report.add("ticket statuses", False, str(exc))

    has_auth = any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"))
    report.add("claude auth", has_auth, "ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN")
    return report
```

Replace `_dispatch` in `src/tedsbot/cli.py`:
```python
def _dispatch(ns: argparse.Namespace) -> int:
    from pathlib import Path

    config_path = Path(ns.config)
    if ns.command == "check":
        from tedsbot.commands.check import run_check

        report = run_check(config_path)
        for name, ok, detail in report.results:
            print(f"[{'ok' if ok else 'FAIL'}] {name} — {detail}")
        return 0 if report.ok else 1
    print(f"{ns.command}: not implemented yet", file=sys.stderr)
    return 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_check.py tests/unit/test_cli.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/tedsbot/commands src/tedsbot/cli.py tests/unit/test_check.py
git commit -m "feat: check command validates config and connectivity"
```

---

### Task 12: `triage sentry` and `triage ticket` commands

**Files:**
- Create: `src/tedsbot/commands/triage.py`, `tests/unit/test_triage_commands.py`
- Modify: `src/tedsbot/cli.py` (`_dispatch`)

**Interfaces:**
- Consumes: `RunSpec`, `TRIAGE_TOOLS`, `new_run_dir`, `runner.run`, `load_config`.
- Produces: `commands.triage.build_sentry_spec(cfg: Config, target: str) -> RunSpec`, `build_ticket_spec(cfg: Config, key: str) -> RunSpec`, `async commands.triage.triage(cfg, spec, *, run_fn=runner.run, home: Path | None = None) -> RunSummary`. CLI: `triage sentry X` and `triage ticket X` load config, build the spec, `asyncio.run(triage(...))`, print `slack_line`, return `0` if `summary.ok` else `1`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_triage_commands.py`:
```python
# ABOUTME: Tests the triage command wiring with an injected run function so
# ABOUTME: no agent is started: spec shape, run dir creation, exit codes.
from pathlib import Path

import pytest
import yaml

from tedsbot.cli import main
from tedsbot.commands.triage import build_sentry_spec, build_ticket_spec, triage
from tedsbot.config import load_config
from tedsbot.runner import TRIAGE_TOOLS
from tedsbot.summary import RunSummary


@pytest.fixture
def cfg(tmp_path: Path, config_dict: dict, env_tokens: None):
    p = tmp_path / "tedsbot.yaml"
    p.write_text(yaml.safe_dump(config_dict))
    return load_config(p)


def test_sentry_spec(cfg) -> None:
    spec = build_sentry_spec(cfg, "APP-1")
    assert spec.kind == "triage_sentry" and spec.prompt_name == "triage_sentry"
    assert spec.inputs == {"sentry_issue": "APP-1"} and spec.max_turns == 60
    assert spec.tools == TRIAGE_TOOLS and not spec.include_edit_tools


def test_ticket_spec(cfg) -> None:
    spec = build_ticket_spec(cfg, "APP-2")
    assert spec.kind == "triage_ticket" and spec.inputs == {"ticket_key": "APP-2"}


async def test_triage_creates_run_dir_and_returns_summary(cfg, temp_home: Path) -> None:
    seen: dict = {}

    async def fake_run(c, spec, run_dir):
        seen["run_dir"] = run_dir
        return RunSummary(kind=spec.kind, headline="ok", ok=True)

    summary = await triage(cfg, build_sentry_spec(cfg, "APP-1"), run_fn=fake_run)
    assert summary.ok and seen["run_dir"].parent == temp_home / ".tedsbot" / "runs"


def test_cli_exit_codes(tmp_path: Path, config_dict: dict, env_tokens: None, temp_home: Path,
                        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "tedsbot.yaml"
    p.write_text(yaml.safe_dump(config_dict))

    async def failing(c, spec, run_dir):
        return RunSummary(kind=spec.kind, headline="agent died", ok=False)

    monkeypatch.setattr("tedsbot.commands.triage._run", failing)
    assert main(["-c", str(p), "triage", "ticket", "APP-9"]) == 1
    assert "agent died" in capsys.readouterr().out

    async def passing(c, spec, run_dir):
        return RunSummary(kind=spec.kind, ticket="APP-9", headline="fine", recommendation="🟢", ok=True)

    monkeypatch.setattr("tedsbot.commands.triage._run", passing)
    assert main(["-c", str(p), "triage", "sentry", "APP-9"]) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_triage_commands.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tedsbot.commands.triage'`

- [ ] **Step 3: Write the command and wire the CLI**

`src/tedsbot/commands/triage.py`:
```python
# ABOUTME: The `tedsbot triage` commands: build a RunSpec for a Sentry issue or
# ABOUTME: a ticket, create the run directory, and hand off to the runner.
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from tedsbot import runner
from tedsbot.config import Config
from tedsbot.runner import TRIAGE_TOOLS, RunSpec, new_run_dir
from tedsbot.summary import RunSummary, slack_line

RunFn = Callable[[Config, RunSpec, Path], Awaitable[RunSummary]]
_run: RunFn = runner.run


def build_sentry_spec(cfg: Config, target: str) -> RunSpec:
    return RunSpec(kind="triage_sentry", prompt_name="triage_sentry",
                   inputs={"sentry_issue": target}, max_turns=cfg.agent.max_turns.triage,
                   tools=list(TRIAGE_TOOLS), run_id=target)


def build_ticket_spec(cfg: Config, key: str) -> RunSpec:
    return RunSpec(kind="triage_ticket", prompt_name="triage_ticket",
                   inputs={"ticket_key": key}, max_turns=cfg.agent.max_turns.triage,
                   tools=list(TRIAGE_TOOLS), run_id=key)


async def triage(cfg: Config, spec: RunSpec, *, run_fn: RunFn | None = None, home: Path | None = None) -> RunSummary:
    run_dir = new_run_dir(spec.kind, spec.run_id, home)
    return await (run_fn or _run)(cfg, spec, run_dir)


def main_triage(cfg: Config, kind: str, target: str) -> int:
    spec = build_sentry_spec(cfg, target) if kind == "sentry" else build_ticket_spec(cfg, target)
    summary = asyncio.run(triage(cfg, spec, run_fn=_run))
    print(slack_line(summary, Path.home() / ".tedsbot" / "runs"))
    return 0 if summary.ok else 1
```

In `src/tedsbot/cli.py` `_dispatch`, add before the fallthrough:
```python
    if ns.command == "triage":
        from tedsbot.commands.triage import main_triage
        from tedsbot.config import load_config
        from tedsbot.errors import ConfigError

        try:
            cfg = load_config(config_path)
        except ConfigError as exc:
            print(f"config error: {exc}", file=sys.stderr)
            return 2
        return main_triage(cfg, ns.triage_kind, ns.target)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit -v`
Expected: all unit tests pass

- [ ] **Step 5: Commit**

```bash
git add src/tedsbot/commands/triage.py src/tedsbot/cli.py tests/unit/test_triage_commands.py
git commit -m "feat: triage sentry and triage ticket commands"
```

---

### Task 13: Example config, README with setup guide

**Files:**
- Create: `tedsbot.example.yaml`, `README.md`, `tests/unit/test_example_config.py`

**Interfaces:**
- Produces: an example config that validates through `load_config` when the referenced env vars are set and `repo.path` is patched to a real checkout.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_example_config.py`:
```python
# ABOUTME: Guards the shipped example config: it must validate once its env
# ABOUTME: vars are set and its checkout path points at a real repo.
from pathlib import Path

import yaml

from tedsbot.config import load_config

EXAMPLE = Path(__file__).resolve().parents[2] / "tedsbot.example.yaml"


def test_example_config_validates(tmp_path: Path, checkout: Path, env_tokens: None, monkeypatch) -> None:
    monkeypatch.setenv("GRAFANA_SERVICE_ACCOUNT_TOKEN", "g")
    data = yaml.safe_load(EXAMPLE.read_text())
    data["repo"]["path"] = str(checkout)
    p = tmp_path / "tedsbot.yaml"
    p.write_text(yaml.safe_dump(data))
    cfg = load_config(p)
    assert cfg.tickets.project == "APP" and cfg.errors.org == "example-org"
    assert "example" in cfg.tickets.url
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_example_config.py -v`
Expected: FAIL with `FileNotFoundError` for `tedsbot.example.yaml`

- [ ] **Step 3: Write the example config**

`tedsbot.example.yaml`: the YAML from the spec's Configuration section verbatim, with a leading comment block:

```yaml
# tedsbot config. Copy to tedsbot.yaml, fill in, run `tedsbot check`.
# Secrets are never written here: use ${ENV_VAR} and export the variable.
```

followed by the exact spec YAML (repo, errors, tickets, logs, notify, agent, worker). Keep `logs:` present so the example exercises the optional role.

- [ ] **Step 4: Write README.md**

Sections and content:

```markdown
# tedsbot-triage-worker

Autonomous bug-triage and fix worker on the Claude Agent SDK. Point it at
a checkout, an error source, and a ticketing system; it root-causes
production errors and team-reported bugs into tickets a human can approve,
and implements approved fixes as draft pull requests.

Powered by Claude. Not affiliated with Anthropic.

## Mission

Run an autonomous triage worker on the Claude credentials you already have.
Humans stay in the loop at exactly two places: approving a fix, and
reviewing the pull request.

## Guiding principles

1. Bring your own credentials. Never brokers login for anyone.
2. Roles, not brands. Error source, ticketing, logs, notifier; providers fill them.
3. Determinism where it matters. Polling, dedupe, gates, summaries, notifications are plain Python.
4. Honesty over confidence. 🔴 beats a wrong confident analysis.
5. Human gates are hard gates. Triage never edits code. Fix only runs on approved tickets, draft PRs only.
6. Knowledge lives in files, not prompts.
7. Nothing project-specific in this repo.

## How it works

    error source ──poll──▶ triage sentry ─┐
    ticketing ───poll──▶ triage ticket ──┼─▶ ticket in "Dev Team Review" ──human approves──▶ fix ──▶ draft PR ──human reviews
                                          └─▶ Slack line per run

Triage runs are read-only: Read, Grep, Glob, git history, plus the
provider tools. Every run writes `~/.tedsbot/runs/<id>/summary.json`,
`prompt.md`, and `transcript.jsonl`.

## Setup guide

### 1. Prerequisites
- Python 3.12+, [uv](https://docs.astral.sh/uv/)
- Node.js 18+ (the Sentry MCP server runs with `npx`)
- [GitHub CLI](https://cli.github.com) (`gh`)
- A local checkout of the repository you want triaged, with full history (`git fetch --unshallow` if it was a shallow clone)

### 2. Install
    uv tool install tedsbot-triage-worker
or from a clone:
    git clone https://github.com/tauhir/tedsbot-triage-worker && cd tedsbot-triage-worker && uv sync

### 3. Credentials
Export these in the shell (or the service unit) that runs tedsbot.

**Claude.** One of:
- `ANTHROPIC_API_KEY` from the Claude Console. This is the documented, supported path; usage is metered.
- `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`, which bills your own Claude subscription (Pro, Max, Team, Enterprise). Anthropic's Agent SDK documentation states: "Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK." tedsbot does not offer login; it passes your own token through. Whether that fits your plan's terms is your call.

**GitHub.** `gh auth login` on the host, or export `GH_TOKEN` (a PAT or a GitHub App installation token). PRs are authored by whichever identity you choose.

**Sentry.** `SENTRY_AUTH_TOKEN`: an auth token with `event:read`, `project:read`, `org:read`.

**Atlassian.** `ATLASSIAN_API_TOKEN`: a service token with browse, comment, create-issue, edit-issue, and transition permissions on the project.

**Grafana (optional).** `GRAFANA_SERVICE_ACCOUNT_TOKEN` for a service account with Viewer on the relevant data sources.

**Slack.** `SLACK_WEBHOOK_URL`: an incoming webhook for the channel that should see run results.

### 4. Ticketing prerequisites
The statuses you name under `tickets.statuses` must exist on the project's workflow, and the custom fields under `tickets.fields` must exist on the Bug issue type. Find field IDs with the Jira REST API (`GET /rest/api/3/field`) and status names from the board's workflow. A dedicated bot account for the token is recommended so triage comments are clearly machine-authored.

### 5. Error-source prerequisites
Turn on Sentry's inbound filters (legacy browsers, web crawlers, health checks, localhost) so noise never becomes an event. Confirm the exact spelling and case of the environment name; Sentry searches are case-sensitive.

### 6. Configure
    cp tedsbot.example.yaml tedsbot.yaml
Edit every value. Put your team's knowledge (transition map, deploy topology, known noise, replication conventions) as markdown files in the directory named by `agent.knowledge_dir`.

### 7. Verify
    tedsbot check
Every line must read `[ok]`. Nothing has spent credits yet.

### 8. First run
    tedsbot triage sentry <issue-id-or-url>
Read the Slack line, the ticket, and `~/.tedsbot/runs/<id>/transcript.jsonl`.

### 9. Deploy
- **systemd**: a unit running `tedsbot worker` with the env vars in an `EnvironmentFile`. (Milestone 2.)
- **cron**: `*/15 * * * * tedsbot -c /etc/tedsbot/tedsbot.yaml worker --once`. (Milestone 2.)
- **GitHub Action**: composite wrapper. (Milestone 3.)

## Extending: writing a provider
Implement one of the protocols in `src/tedsbot/providers/base.py`, ship a knowledge markdown file next to it, and call `register(role, kind, YourClass)` at import. Add the module to `providers/__init__.py`. Your `kind` becomes selectable in the YAML.

## Operating
Each run directory holds `prompt.md` (what the agent was told), `transcript.jsonl` (every message), `summary.json` (what the agent wrote), and `summary.resolved.json` (what Python accepted). A 🔴 means the agent could not establish a credible root cause; read the transcript before deciding whether the ticket needs more context or the knowledge directory needs a note.

## Policy and billing
Each run consumes Claude tokens under whichever credential you configured. Set `agent.max_turns` to cap a runaway run. See Credentials above for the subscription-token note.

## License
MIT
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_example_config.py -v`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add tedsbot.example.yaml README.md tests/unit/test_example_config.py
git commit -m "docs: README with setup guide; ship example config"
```

---

### Task 14: End-to-end triage test and full-suite pass

**Files:**
- Create: `tests/e2e/test_triage_e2e.py`
- Modify: `tests/conftest.py` (e2e skip marker)

**Interfaces:**
- Consumes: the CLI via `subprocess`.

- [ ] **Step 1: Add the e2e skip to conftest.py**

Append to `tests/conftest.py`:
```python
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("TEDSBOT_E2E") == "1":
        return
    skip = pytest.mark.skip(reason="set TEDSBOT_E2E=1 with real credentials to run")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip)
```

- [ ] **Step 2: Write the e2e test**

`tests/e2e/test_triage_e2e.py`:
```python
# ABOUTME: Real end-to-end triage run against a sandbox ticketing project.
# ABOUTME: Spends credits; runs only with TEDSBOT_E2E=1 and TEDSBOT_E2E_CONFIG set.
import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


def _latest_run_dir() -> Path:
    runs = Path.home() / ".tedsbot" / "runs"
    return sorted(runs.iterdir())[-1]


def test_triage_sentry_lands_ticket_and_summary() -> None:
    config = os.environ["TEDSBOT_E2E_CONFIG"]
    issue = os.environ["TEDSBOT_E2E_SENTRY_ISSUE"]
    proc = subprocess.run(["uv", "run", "tedsbot", "-c", config, "triage", "sentry", issue],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    summary = json.loads((_latest_run_dir() / "summary.resolved.json").read_text())
    assert summary["ok"] is True
    assert summary["recommendation"] in ("🟢", "🟡", "⚪", "🔴")
    assert summary["ticket"] and summary["ticket_url"]


def test_triage_ticket_comments_and_summary() -> None:
    config = os.environ["TEDSBOT_E2E_CONFIG"]
    key = os.environ["TEDSBOT_E2E_TICKET"]
    proc = subprocess.run(["uv", "run", "tedsbot", "-c", config, "triage", "ticket", key],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    summary = json.loads((_latest_run_dir() / "summary.resolved.json").read_text())
    assert summary["ok"] is True and summary["ticket"] == key
```

- [ ] **Step 3: Run the whole suite without e2e credentials**

Run: `uv run pytest -n auto -v`
Expected: all unit and integration tests pass; the two e2e tests report `SKIPPED`; zero warnings.

- [ ] **Step 4: Run ruff**

Run: `uv run ruff check src tests && uv run ruff format --check src tests`
Expected: clean. Fix any findings and re-run the suite.

- [ ] **Step 5: Commit and push**

```bash
git add tests/conftest.py tests/e2e/test_triage_e2e.py
git commit -m "test: e2e triage runs gated on TEDSBOT_E2E"
git push origin main
```

---

## Self-review against the spec

- **Runtime shape**: `check`, `triage sentry`, `triage ticket` covered (Tasks 11, 12). `fix` and `worker` are Milestone 2 by design; the CLI parser already reserves them (Task 1).
- **Authentication**: env pass-through in Task 10; README section in Task 13.
- **Configuration**: Task 2 matches the spec YAML field for field, including `logs` optional and `worker` defaults.
- **Provider model**: protocols in Task 3; sentry (4), jira (5), slack (6). Grafana is Milestone 2.
- **Knowledge**: three tiers plus CLAUDE.md for fix runs (Tasks 7, 10). `setting_sources=[]` honoured (Task 10).
- **Prompts**: both triage templates (Task 8), facts-driven, no project constants.
- **Run contract**: Task 9 model, Task 10 `Write(<run_dir>/summary.json)` allow rule, transcript, fallback.
- **Tool allowlists / dontAsk**: Task 10.
- **Gates**: triage gates are structural (allowlist). The post-run status check ("warn if ticket moved past target") is not in this milestone; it lands with the worker loop in Milestone 2 where `status_of` is already implemented (Task 5).
- **Notifications**: Task 6 and Task 10.
- **Testing**: unit (every task), integration (Tasks 4, 5), e2e (Task 14).
- **README**: Task 13 with the ordered setup guide.
