# ABOUTME: Preconditions for a fix run, checked in Python before the agent starts:
# ABOUTME: clean checkout on the base branch, approved ticket, no open PR for the branch.
from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tedsbot.config import Config
from tedsbot.errors import GateError

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def _git(path: Path, *args: str, run: Runner) -> str:
    result = run(["git", "-C", str(path), *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise GateError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def checkout_is_clean_on(path: Path, base_branch: str, run: Runner = subprocess.run) -> None:
    if _git(path, "status", "--porcelain", run=run):
        raise GateError(f"checkout {path} has uncommitted changes")
    branch = _git(path, "rev-parse", "--abbrev-ref", "HEAD", run=run)
    if branch != base_branch:
        raise GateError(f"checkout {path} is on '{branch}', expected '{base_branch}'")


def ticket_is_in(status_of: Callable[[str], str], key: str, expected: str) -> None:
    actual = status_of(key)
    if actual != expected:
        raise GateError(f"{key} is in '{actual}', expected '{expected}'")


def no_open_pr_for(github_repo: str, branch: str, run: Runner = subprocess.run) -> None:
    cmd = ["gh", "pr", "list", "--repo", github_repo, "--head", branch, "--state", "open", "--json", "number,url"]
    result = run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise GateError(f"gh pr list failed: {result.stderr.strip()}")
    open_prs: list[dict[str, Any]] = json.loads(result.stdout or "[]")
    if open_prs:
        raise GateError(f"open PR already exists for {branch}: {open_prs[0].get('url')}")


def run_fix_gates(cfg: Config, status_of: Callable[[str], str], key: str, branch: str, run: Runner = subprocess.run) -> None:
    checkout_is_clean_on(cfg.repo.path, cfg.repo.base_branch, run=run)
    ticket_is_in(status_of, key, cfg.tickets.statuses.fix_approved)
    no_open_pr_for(cfg.repo.github, branch, run=run)
