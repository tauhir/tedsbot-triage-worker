# ABOUTME: Watches a pull request's CI after the fix agent opens it, by polling
# ABOUTME: `gh pr checks`, and reports passed, failed, none, or timeout.
from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

Runner = Callable[..., "subprocess.CompletedProcess[str]"]
FAILING_BUCKETS = {"fail", "cancel"}
PENDING_BUCKETS = {"pending"}


@dataclass
class CiVerdict:
    state: Literal["passed", "failed", "timeout", "none"]
    failing: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)


def _checks(pr_url: str, run: Runner) -> list[dict] | None:
    result = run(["gh", "pr", "checks", pr_url, "--json", "name,bucket"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    try:
        return list(json.loads(result.stdout or "[]"))
    except ValueError:
        return None


def watch_ci(
    pr_url: str,
    wait_minutes: int,
    poll_seconds: int,
    run: Runner = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> CiVerdict:
    deadline = clock() + wait_minutes * 60
    empty_polls = 0
    while True:
        checks = _checks(pr_url, run)
        if checks is not None:
            if not checks:
                empty_polls += 1
                if empty_polls >= 2:
                    return CiVerdict("none")
            else:
                failing = [c["name"] for c in checks if c.get("bucket") in FAILING_BUCKETS]
                pending = [c["name"] for c in checks if c.get("bucket") in PENDING_BUCKETS]
                if not pending:
                    return CiVerdict("failed", failing) if failing else CiVerdict("passed")
        if clock() >= deadline:
            pending = [c["name"] for c in (checks or []) if c.get("bucket") in PENDING_BUCKETS]
            return CiVerdict("timeout", pending=pending)
        sleep(poll_seconds)
