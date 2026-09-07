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
# Anything neither failing nor finished is still running, including a bucket
# gh grows later: reading an unknown value as success would report a green PR
# on a check nobody has looked at.
DONE_BUCKETS = {"pass", "skipping"}


def _is_pending(check: dict) -> bool:
    bucket = check.get("bucket")
    return bucket not in FAILING_BUCKETS and bucket not in DONE_BUCKETS


@dataclass
class CiVerdict:
    state: Literal["passed", "failed", "timeout", "none"]
    failing: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)


def _checks(pr_url: str, run: Runner) -> list[dict] | None:
    result = run(["gh", "pr", "checks", pr_url, "--json", "name,bucket"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        # A pull request with no checks at all is a verdict, not a transport
        # failure: gh says so on stderr and exits non-zero rather than
        # printing an empty list.
        if "no checks reported" in (result.stderr or "").lower():
            return []
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
                empty_polls = 0
                failing = [c["name"] for c in checks if c.get("bucket") in FAILING_BUCKETS]
                pending = [c["name"] for c in checks if _is_pending(c)]
                if not pending:
                    return CiVerdict("failed", failing) if failing else CiVerdict("passed")
        if clock() >= deadline:
            pending = [c["name"] for c in (checks or []) if _is_pending(c)]
            return CiVerdict("timeout", pending=pending)
        sleep(poll_seconds)
