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
