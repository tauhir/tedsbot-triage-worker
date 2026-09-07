# ABOUTME: Preconditions for a fix run, checked in Python before the agent starts:
# ABOUTME: clean checkout on the base branch, approved ticket, no open PR for the branch.
from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tedsbot.config import Config
from tedsbot.errors import GateError

log = logging.getLogger(__name__)

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


def _quiet_git(path: Path, args: list[str], run: Runner) -> subprocess.CompletedProcess[str]:
    """Run git without raising; the caller decides what a failure means."""
    try:
        return run(["git", "-C", str(path), *args], capture_output=True, text=True, check=False)
    except OSError as exc:
        return subprocess.CompletedProcess(args, 1, stdout="", stderr=str(exc))


def restore_checkout(path: Path, base_branch: str, run: Runner = subprocess.run) -> str | None:
    """Return the checkout to the base branch after a fix run, best effort.

    A run leaves the checkout on the bot branch, which the clean-checkout gate
    would refuse on the next run. This puts it back and fast-forwards it. It
    never raises: the run it follows has already finished, so a failure here is
    logged and, when work would be lost, described in the returned message.

    Args:
        path: The worker's checkout.
        base_branch: The branch the checkout should end up on.
        run: subprocess.run, injectable for tests.

    Returns:
        None when the checkout was clean, whether or not every git command
        succeeded; otherwise a message naming the branch it was left on.
    """
    status = _quiet_git(path, ["status", "--porcelain"], run)
    if status.returncode != 0:
        log.error("git status failed in %s: %s", path, status.stderr.strip())
        return None
    if status.stdout.strip():
        head = _quiet_git(path, ["rev-parse", "--abbrev-ref", "HEAD"], run)
        branch = head.stdout.strip() if head.returncode == 0 else ""
        return f"checkout left on '{branch or '?'}' with uncommitted changes"
    checkout = _quiet_git(path, ["checkout", base_branch], run)
    if checkout.returncode != 0:
        # Pulling while still on the bot branch would merge the base branch
        # into it, so a failed checkout ends the restore.
        log.error("git checkout %s failed in %s: %s", base_branch, path, checkout.stderr.strip())
        return None
    pull = _quiet_git(path, ["pull", "--ff-only", "origin", base_branch], run)
    if pull.returncode != 0:
        log.error("git pull --ff-only origin %s failed in %s: %s", base_branch, path, pull.stderr.strip())
    return None


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
