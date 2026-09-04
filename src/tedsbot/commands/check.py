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
