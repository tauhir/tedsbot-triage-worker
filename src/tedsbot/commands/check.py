# ABOUTME: The `tedsbot check` command: validates config and confirms every
# ABOUTME: external dependency is reachable before any credits are spent.
from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

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
    # Milestone 1 probes launch only; the JSON-RPC initialize handshake that
    # would prove the server actually speaks MCP is deferred to milestone 2.
    # Three outcomes: the process exits and its return code says whether it
    # succeeded; it times out because a stdio server waiting on stdin has
    # proven it can launch (treated as reachable); or it never starts at all
    # (missing binary), which is unreachable.
    cmd = [config["command"], *config.get("args", [])]
    env = {**os.environ, **config.get("env", {})}
    try:
        result = subprocess.run(cmd, input=b"", capture_output=True, timeout=20, env=env, check=False)
        return result.returncode == 0
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

    roles: list[tuple[str, Any, Callable[[Any], Any]]] = [
        ("errors", cfg.errors, registry.get_error_source),
        ("tickets", cfg.tickets, registry.get_ticketing),
    ]
    if cfg.logs is not None:
        roles.append(("logs", cfg.logs, registry.get_log_store))
    # A role naming a kind nobody registered is a finding, not a crash: the
    # remaining checks still tell the operator what else is wrong.
    providers: dict[str, Any] = {}
    for role, section, getter in roles:
        try:
            providers[role] = getter(section)
        except ConfigError as exc:
            report.add(f"provider:{role}", False, str(exc))

    for provider in providers.values():
        server = provider.mcp_server()
        report.add(f"mcp:{server.name}", mcp_probe(server.config), " ".join([server.config["command"], *server.config.get("args", [])]))

    if (errors := providers.get("errors")) is not None:
        ok, detail = errors.check_auth()
        report.add("sentry auth", ok, detail)

    report.add("gh auth", gh_probe(), "gh auth status")

    if (tickets := providers.get("tickets")) is not None:
        wanted = list(cfg.tickets.statuses.model_dump().values())
        try:
            missing = tickets.statuses_exist(wanted)
            report.add("ticket statuses", not missing, "all present" if not missing else f"missing: {', '.join(missing)}")
        except (ProviderError, httpx.HTTPError) as exc:
            report.add("ticket statuses", False, str(exc))

    has_auth = any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"))
    report.add("claude auth", has_auth, "ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN")
    return report
