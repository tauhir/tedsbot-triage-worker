# tedsbot-triage-worker — Milestone 2a (Fix stage) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `tedsbot fix <KEY>` turns a human-approved ticket into a draft pull request: Python gates, an agent run that implements and tests the change, a CI watch that hands red results back, and a Slack message per stage.

**Architecture:** Same runner and summary contract as triage. New: a `fix` config section, a `gates` module (pure functions over git and `gh`), a `ci` module (poll `gh pr checks`), a `fix` prompt template, a `commands/fix.py` orchestrator, fix-status headers in the Slack renderer, and the post-triage status re-read. `gh` is driven through `subprocess.run`, injected so tests never call the real binary.

**Tech Stack:** as milestone 1 (Python 3.12, uv, claude-agent-sdk 0.2.x, pydantic v2, jinja2, httpx, pytest + respx + vcrpy, ruff).

**Spec:** `docs/superpowers/specs/2026-09-03-tedsbot-triage-worker-design.md` including the 2026-09-07 addendum.

## Global Constraints

- Every code file starts with exactly two `# ABOUTME: ` lines; `.j2`, YAML and Markdown are exempt.
- Strict TDD: failing test, run it, minimal code, run it, commit. Test output pristine (`filterwarnings = error`). `uv run pytest -n auto` and `uv run ruff check src tests` green before every commit.
- No mock mode in production code; tests inject `subprocess.run`-shaped callables and fake `run_fn`s. Never call the real `gh` or start a real agent in unit tests.
- Nothing project-specific: example values `example-org`, `example.atlassian.net`, `APP`, `example-org/example-app`, cloud id `cid`.
- Permission mode `dontAsk`; `setting_sources=[]`; `strict_mcp_config=True`. The agent submits its summary through `submit_summary`; it never gets a path-scoped Write rule.
- Fix-run tools: `Read, Edit, Write, Grep, Glob, Bash(git:*), Bash(gh:*)`, plus `Bash(<test_command>:*)` when configured, plus provider MCP wildcards and the notifier and run servers.
- Fix summary `status` is exactly one of `draft PR opened`, `blocked`, `already open`, `gate refused`, `CI green`, `CI red, handed back`.
- Commit trailers: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_0181pu6TuuSzo6MSz5ioe4Wy`. Never `--no-verify`.
- Existing interfaces this plan builds on (do not change their shapes): `RunSpec(kind, prompt_name, inputs, max_turns, tools, run_id, include_edit_tools=False, extra_facts={})`; `runner.run(cfg, spec, run_dir) -> RunSummary`; `new_run_dir(kind, target, home=None)`; `RunSummary` fields `kind, ticket, ticket_url, recommendation, status, pr_url, headline, tldr, outcome, title, events, users, first_seen, last_seen, ok`; `slack_line(summary, run_dir, approve_status)`; `Ticketing.status_of(key)`, `Ticketing.comment(key, body)`; `registry.get_ticketing(cfg.tickets)`, `registry.get_notifier(cfg.notify)` with `.post(text)`; fixtures `checkout`, `config_dict`, `env_tokens`, `temp_home` in `tests/conftest.py`.

---

### Task 1: `fix` config section

**Files:**
- Modify: `src/tedsbot/config.py`, `tedsbot.example.yaml`, `tests/unit/test_config.py`, `tests/unit/test_example_config.py`, `tests/conftest.py`

**Interfaces:**
- Produces: `FixConfig(branch_prefix: str = "tedsbot/", test_command: str | None = None, ci_wait_minutes: int = 0, ci_poll_seconds: int = 30)`; `Config.fix: FixConfig` with a default. `WorkerConfig` loses `branch_prefix` (it moves to `fix`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_config.py`:
```python
def test_fix_defaults(tmp_path: Path, config_dict: dict, env_tokens: None) -> None:
    cfg = load_config(_write(tmp_path, config_dict))
    assert cfg.fix.branch_prefix == "tedsbot/"
    assert cfg.fix.test_command is None
    assert cfg.fix.ci_wait_minutes == 0 and cfg.fix.ci_poll_seconds == 30


def test_fix_section_is_configurable(tmp_path: Path, config_dict: dict, env_tokens: None) -> None:
    config_dict["fix"] = {"branch_prefix": "bot/", "test_command": "uv run pytest -q", "ci_wait_minutes": 20, "ci_poll_seconds": 15}
    cfg = load_config(_write(tmp_path, config_dict))
    assert cfg.fix.branch_prefix == "bot/" and cfg.fix.test_command == "uv run pytest -q"
    assert cfg.fix.ci_wait_minutes == 20 and cfg.fix.ci_poll_seconds == 15


def test_worker_branch_prefix_is_rejected(tmp_path: Path, config_dict: dict, env_tokens: None) -> None:
    config_dict["worker"] = {"branch_prefix": "x/"}
    with pytest.raises(ConfigError, match="worker.branch_prefix"):
        load_config(_write(tmp_path, config_dict))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_config.py -q -k "fix or worker_branch"`
Expected: FAIL (`AttributeError: 'Config' object has no attribute 'fix'`; the third passes only if `worker.branch_prefix` is already gone, so it fails now with no error raised).

- [ ] **Step 3: Implement**

In `src/tedsbot/config.py`, replace `WorkerConfig` and add `FixConfig`:
```python
class WorkerConfig(_Strict):
    interval_seconds: int = 900


class FixConfig(_Strict):
    branch_prefix: str = "tedsbot/"
    test_command: str | None = None
    ci_wait_minutes: int = 0
    ci_poll_seconds: int = 30
```
Add `fix: FixConfig = Field(default_factory=FixConfig)` to `Config` after `agent`. In `tedsbot.example.yaml`, move `branch_prefix` from `worker:` into a new block:
```yaml
fix:
  branch_prefix: tedsbot/            # fix branches are <prefix><TICKET-KEY>
  # test_command: uv run pytest -q   # when set, the agent runs it and reports the real result
  ci_wait_minutes: 0                 # >0: after the PR opens, wait for CI and hand red results back
  ci_poll_seconds: 30
```
Update `tests/unit/test_example_config.py` to assert `cfg.fix.branch_prefix == "tedsbot/"`. `tests/conftest.py`'s `config_dict` has no `worker` key; leave it.

- [ ] **Step 4: Run tests**

Run: `uv run pytest -n auto -q` → all green; `uv run ruff check src tests` clean.

- [ ] **Step 5: Commit**

`git commit -m "feat: fix config section (branch prefix, test command, CI wait)"` with trailers.

---

### Task 2: Gates module

**Files:**
- Create: `src/tedsbot/gates.py`, `tests/unit/test_gates.py`

**Interfaces:**
- Produces:
  - `gates.Runner = Callable[..., subprocess.CompletedProcess[str]]` (the shape of `subprocess.run`).
  - `gates.checkout_is_clean_on(path: Path, base_branch: str, run: Runner = subprocess.run) -> None`, raises `GateError` naming the problem (`"checkout has uncommitted changes"`, `"checkout is on 'x', expected 'main'"`).
  - `gates.ticket_is_in(status_of: Callable[[str], str], key: str, expected: str) -> None`, raises `GateError(f"{key} is in '{actual}', expected '{expected}'")`.
  - `gates.no_open_pr_for(github_repo: str, branch: str, run: Runner = subprocess.run) -> None`, runs `gh pr list --repo <slug> --head <branch> --state open --json number,url` and raises `GateError(f"open PR already exists for {branch}: {url}")` when the JSON list is non-empty; raises `GateError("gh pr list failed: <stderr>")` on non-zero exit.
  - `gates.run_fix_gates(cfg: Config, status_of, key: str, branch: str, run: Runner = subprocess.run) -> None` calling the three in order: checkout, ticket, PR.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_gates.py`:
```python
# ABOUTME: Tests the fix-run gates: clean checkout on the base branch, ticket in the
# ABOUTME: approved status, and no open PR for the branch (gh is injected, never real).
import json
import subprocess
from pathlib import Path

import pytest

from tedsbot.errors import GateError
from tedsbot.gates import checkout_is_clean_on, no_open_pr_for, ticket_is_in


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True, capture_output=True)


def test_clean_checkout_on_base_passes(checkout: Path) -> None:
    checkout_is_clean_on(checkout, "main")


def test_dirty_checkout_is_refused(checkout: Path) -> None:
    (checkout / "scratch.txt").write_text("x")
    with pytest.raises(GateError, match="uncommitted"):
        checkout_is_clean_on(checkout, "main")


def test_wrong_branch_is_refused(checkout: Path) -> None:
    _git(checkout, "checkout", "-q", "-b", "feature")
    with pytest.raises(GateError, match="on 'feature', expected 'main'"):
        checkout_is_clean_on(checkout, "main")


def test_ticket_status_gate() -> None:
    ticket_is_in(lambda key: "Approved For Fix", "APP-1", "Approved For Fix")
    with pytest.raises(GateError, match="APP-1 is in 'Backlog', expected 'Approved For Fix'"):
        ticket_is_in(lambda key: "Backlog", "APP-1", "Approved For Fix")


def _fake_gh(stdout: str, returncode: int = 0, stderr: str = ""):
    calls: list[list[str]] = []

    def run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_no_open_pr_passes_and_queries_the_branch() -> None:
    run = _fake_gh("[]")
    no_open_pr_for("example-org/example-app", "tedsbot/APP-1", run=run)
    assert run.calls[0][:3] == ["gh", "pr", "list"] and "--head" in run.calls[0] and "tedsbot/APP-1" in run.calls[0]
    assert "--repo" in run.calls[0] and "example-org/example-app" in run.calls[0]


def test_open_pr_is_refused_with_its_url() -> None:
    run = _fake_gh(json.dumps([{"number": 7, "url": "https://github.com/example-org/example-app/pull/7"}]))
    with pytest.raises(GateError, match="pull/7"):
        no_open_pr_for("example-org/example-app", "tedsbot/APP-1", run=run)


def test_gh_failure_is_a_gate_error() -> None:
    with pytest.raises(GateError, match="gh pr list failed"):
        no_open_pr_for("example-org/example-app", "tedsbot/APP-1", run=_fake_gh("", 1, "not logged in"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_gates.py -q` → `ModuleNotFoundError: No module named 'tedsbot.gates'`.

- [ ] **Step 3: Implement `src/tedsbot/gates.py`**

```python
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
```

- [ ] **Step 4: Run tests** → 7 passed; full suite green; ruff clean.

- [ ] **Step 5: Commit** `feat: fix-run gates (checkout, ticket status, open PR)`.

---

### Task 3: CI watch module

**Files:**
- Create: `src/tedsbot/ci.py`, `tests/unit/test_ci.py`

**Interfaces:**
- Produces: `ci.CiVerdict` dataclass `state: Literal["passed", "failed", "timeout", "none"]`, `failing: list[str]`, `pending: list[str]`; `ci.watch_ci(pr_url: str, wait_minutes: int, poll_seconds: int, run: Runner = subprocess.run, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> CiVerdict`. It runs `gh pr checks <pr_url> --json name,bucket` each poll; `bucket` values: `pass`, `fail`, `pending`, `skipping`, `cancel`. `fail` or `cancel` count as failing. Returns `passed` when nothing is pending and nothing failing; `failed` as soon as any check has failed and none are pending (or immediately if `fail` present and you choose to wait for the rest: wait for the rest, so the comment names all failures); `none` when the check list is empty at the first poll and stays empty for two polls; `timeout` when the wait expires with checks pending. A non-zero `gh` exit is retried until the deadline, then `timeout`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_ci.py`:
```python
# ABOUTME: Tests the CI watch: polling gh pr checks with injected gh, sleep and clock,
# ABOUTME: and the verdicts passed, failed, none, and timeout.
import json
import subprocess

from tedsbot.ci import watch_ci


def _gh_sequence(*payloads):
    payloads = list(payloads)

    def run(cmd, **kwargs):
        body = payloads.pop(0) if len(payloads) > 1 else payloads[0]
        if isinstance(body, int):
            return subprocess.CompletedProcess(cmd, body, stdout="", stderr="boom")
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(body), stderr="")

    return run


def _clock(step: float = 10.0):
    now = [0.0]

    def clock():
        now[0] += step
        return now[0]

    return clock


def test_all_pass_after_pending() -> None:
    run = _gh_sequence([{"name": "tests", "bucket": "pending"}], [{"name": "tests", "bucket": "pass"}, {"name": "lint", "bucket": "skipping"}])
    v = watch_ci("https://github.com/x/y/pull/1", wait_minutes=5, poll_seconds=1, run=run, sleep=lambda s: None, clock=_clock())
    assert v.state == "passed" and v.failing == [] and v.pending == []


def test_failure_waits_for_the_rest_then_names_all_failures() -> None:
    run = _gh_sequence(
        [{"name": "tests", "bucket": "fail"}, {"name": "lint", "bucket": "pending"}],
        [{"name": "tests", "bucket": "fail"}, {"name": "lint", "bucket": "cancel"}],
    )
    v = watch_ci("u", wait_minutes=5, poll_seconds=1, run=run, sleep=lambda s: None, clock=_clock())
    assert v.state == "failed" and v.failing == ["tests", "lint"]


def test_no_checks_is_none() -> None:
    v = watch_ci("u", wait_minutes=5, poll_seconds=1, run=_gh_sequence([]), sleep=lambda s: None, clock=_clock())
    assert v.state == "none"


def test_timeout_with_pending_checks() -> None:
    run = _gh_sequence([{"name": "tests", "bucket": "pending"}])
    v = watch_ci("u", wait_minutes=1, poll_seconds=1, run=run, sleep=lambda s: None, clock=_clock(step=20.0))
    assert v.state == "timeout" and v.pending == ["tests"]


def test_gh_errors_are_retried_until_deadline() -> None:
    v = watch_ci("u", wait_minutes=1, poll_seconds=1, run=_gh_sequence(1), sleep=lambda s: None, clock=_clock(step=20.0))
    assert v.state == "timeout"
```

- [ ] **Step 2: Run tests** → `ModuleNotFoundError: No module named 'tedsbot.ci'`.

- [ ] **Step 3: Implement `src/tedsbot/ci.py`**

```python
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
```

- [ ] **Step 4: Run tests** → 5 passed; suite green; ruff clean.

- [ ] **Step 5: Commit** `feat: CI watch over gh pr checks`.

---

### Task 4: Fix-run Slack rendering and summary tweaks

**Files:**
- Modify: `src/tedsbot/summary.py`, `tests/unit/test_summary.py`, `tests/unit/test_summary_tool.py`

**Interfaces:**
- `FixStatus = Literal["draft PR opened", "blocked", "already open", "gate refused", "CI green", "CI red, handed back"]`; `RunSummary.status: str | None` stays a string (fallbacks write free text) but `SUMMARY_SCHEMA["properties"]["status"]` gains the `enum` of those six values plus null.
- `SUMMARY_SCHEMA["required"]` becomes `["kind", "headline", "tldr", "ok"]` (outcome is triage-only).
- `slack_line` for `kind == "fix"` renders: header from `_FIX_HEADERS[status] = (emoji, header, next)`; ticket line; What happened; `*PR:* <url>` when present; Technical; Next.

`_FIX_HEADERS`:
```python
_FIX_HEADERS: dict[str, tuple[str, str, str]] = {
    "draft PR opened": ("🔧", "Draft PR opened: ready for review", "Review the PR. Merge and QA stay with a human."),
    "CI green": ("✅", "Fix passed CI: ready for review", "Review the PR. Merge and QA stay with a human."),
    "CI red, handed back": ("❌", "Fix failed CI: handed back", "A developer reads the failing checks on the PR and the ticket comment, then fixes or closes it."),
    "blocked": ("⏸", "Fix blocked: needs a decision", "Answer the question in the ticket comment, then re-approve."),
    "already open": ("↩", "Fix already in progress", "No action. The existing PR is linked on the ticket."),
    "gate refused": ("🚫", "Fix not started: precondition failed", "Fix the precondition named above and re-run."),
}
```

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_summary.py`)

```python
def test_slack_message_for_fix_run_draft_pr(tmp_path: Path) -> None:
    s = RunSummary(kind="fix", ticket="APP-7", ticket_url="https://j/APP-7", status="draft PR opened",
                   pr_url="https://github.com/example-org/example-app/pull/12", title="Chart filter crashes on load",
                   headline="Guard querySelectorAll against a null container in charts.js:41; test added",
                   tldr="The admin chart page no longer crashes when the filter box is empty. A pull request is ready for review.", ok=True)
    assert slack_line(s, tmp_path, approve_status="Approved For Fix").splitlines() == [
        "*🔧 Draft PR opened: ready for review*",
        "*<https://j/APP-7|APP-7>* Chart filter crashes on load",
        "*What happened:* The admin chart page no longer crashes when the filter box is empty. A pull request is ready for review.",
        "*PR:* https://github.com/example-org/example-app/pull/12",
        "*Technical:* Guard querySelectorAll against a null container in charts.js:41; test added",
        "*Next:* Review the PR. Merge and QA stay with a human.",
    ]


def test_slack_message_for_fix_statuses(tmp_path: Path) -> None:
    expectations = {
        "CI green": ("✅", "Fix passed CI"), "CI red, handed back": ("❌", "handed back"),
        "blocked": ("⏸", "needs a decision"), "already open": ("↩", "already in progress"), "gate refused": ("🚫", "precondition failed"),
    }
    for status, (emoji, phrase) in expectations.items():
        s = RunSummary(kind="fix", ticket="APP-7", status=status, headline="h", tldr="t", ok=True)
        first = slack_line(s, tmp_path).splitlines()[0]
        assert first.startswith(f"*{emoji} ") and phrase in first, status
```
And in `tests/unit/test_summary_tool.py`:
```python
async def test_fix_submission_without_outcome_is_accepted(tmp_path: Path) -> None:
    server = build_summary_server(tmp_path)
    result = await server.tool.handler({"kind": "fix", "ticket": "APP-7", "status": "draft PR opened", "pr_url": "https://g/pull/1",
                                        "headline": "h", "tldr": "t", "ok": True})
    assert result.get("is_error") is not True


async def test_fix_submission_with_unknown_status_is_rejected(tmp_path: Path) -> None:
    server = build_summary_server(tmp_path)
    result = await server.tool.handler({"kind": "fix", "status": "done-ish", "headline": "h", "tldr": "t", "ok": True})
    assert result["is_error"] is True and "status" in result["content"][0]["text"]
```

- [ ] **Step 2: Run tests** → the fix-status tests fail (header reads "Triage result" / status accepted).

- [ ] **Step 3: Implement** in `summary.py`: add `FixStatus`, `FIX_STATUSES = list(get_args(FixStatus))`, `_FIX_HEADERS`; validate `status` against `FIX_STATUSES` when `kind == "fix"` via a pydantic `model_validator(mode="after")` that raises `ValueError(f"status must be one of {FIX_STATUSES}")` (fallback summaries never set status on fix runs except through these literals); update the schema (`status` enum + null; `required` without `outcome`); in `slack_line`, before the triage branch:
```python
    if s.kind == "fix":
        emoji, header, nxt = _FIX_HEADERS.get(s.status or "", ("🔧", "Fix run", "See the ticket."))
        ticket = f"<{s.ticket_url}|{s.ticket}>" if s.ticket_url and s.ticket else (s.ticket or "?")
        lines = [f"*{emoji} {header}*", f"*{ticket}*" + (f" {_plain(s.title)}" if s.title else "")]
        if s.tldr:
            lines.append(f"*What happened:* {_plain(s.tldr)}")
        if s.pr_url:
            lines.append(f"*PR:* {s.pr_url}")
        lines.append(f"*Technical:* {_plain(s.headline)}")
        lines.append(f"*Next:* {nxt}")
        return "\n".join(lines)
```

- [ ] **Step 4: Run tests** → green; ruff clean. **Step 5: Commit** `feat: fix-run statuses and Slack rendering`.

---

### Task 5: Fix prompt template and runner support

**Files:**
- Create: `src/tedsbot/prompts/fix.md.j2`
- Modify: `src/tedsbot/runner.py`, `tests/unit/test_prompts.py`, `tests/unit/test_runner_options.py`

**Interfaces:**
- `runner.FIX_TOOLS = ["Read", "Edit", "Write", "Grep", "Glob", "Bash(git:*)", "Bash(gh:*)"]`; `runner.AUTH_ENV` gains `"GH_TOKEN"`; `build_options` adds `f"Bash({cfg.fix.test_command}:*)"` to allowed tools when `spec.kind == "fix"` and `cfg.fix.test_command` is set.
- Template `fix` inputs: `ticket_key, branch, base_branch, github_repo, test_command` (the string `"none"` when unset). Facts: the Jira facts (`jira_url, jira_project, qa_instructions_field, status_in_progress, status_code_review, status_fix_approved`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_prompts.py`:
```python
def test_fix_prompt_substitutes_and_carries_rules() -> None:
    text = render_prompt("fix", FACTS, ticket_key="APP-7", branch="tedsbot/APP-7", base_branch="main",
                         github_repo="example-org/example-app", test_command="uv run pytest -q", summary_path="/x")
    assert "TICKET_KEY: APP-7" in text and "BRANCH: tedsbot/APP-7" in text and "example-org/example-app" in text
    assert "uv run pytest -q" in text and "customfield_10073" in text and "Code Review" in text
    assert "Draft only" in text and "never merge" in text and "submit_summary" in text
    assert '"status": "draft PR opened"' in text and "no em-dashes" in text


def test_fix_prompt_without_test_command_says_tests_cannot_run() -> None:
    text = render_prompt("fix", FACTS, ticket_key="APP-7", branch="b", base_branch="main",
                         github_repo="o/r", test_command="none", summary_path="/x")
    assert "cannot run the tests" in text
```
Append to `tests/unit/test_runner_options.py`:
```python
def test_fix_options_allow_edit_tools_test_command_and_gh_token(cfg, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "ghp_x")
    cfg.fix.test_command = "uv run pytest -q"
    spec = RunSpec(kind="fix", prompt_name="fix", inputs={"ticket_key": "APP-7", "branch": "tedsbot/APP-7", "base_branch": "main",
                   "github_repo": "example-org/example-app", "test_command": "uv run pytest -q"},
                   max_turns=150, tools=list(FIX_TOOLS), include_edit_tools=True, run_id="APP-7")
    options, prompt = build_options(cfg, spec, tmp_path)
    assert "Edit" in options.allowed_tools and "Bash(gh:*)" in options.allowed_tools
    assert "Bash(uv run pytest -q:*)" in options.allowed_tools
    assert options.env["GH_TOKEN"] == "ghp_x"
    assert "BRANCH: tedsbot/APP-7" in prompt
```
(Import `FIX_TOOLS` from `tedsbot.runner`.) Note `cfg` is a pydantic model; setting `cfg.fix.test_command` works because models are not frozen.

- [ ] **Step 2: Run tests** → fail (`FileNotFoundError: no prompt template named 'fix'`; `ImportError: FIX_TOOLS`).

- [ ] **Step 3: Write `src/tedsbot/prompts/fix.md.j2`**

```markdown
# Implement an approved fix and open a draft PR

You are the fix implementer running unattended. A human approved a triaged
ticket by moving it to **{{ status_fix_approved }}**, so you now implement
the fix the triage analysis described and open a **draft** pull request for
human review. You are not the final authority: the draft PR, CI, and a human
QA gate are.

## Run inputs

- TICKET_KEY: {{ ticket_key }}
- BRANCH: {{ branch }} (create it from `{{ base_branch }}` in this checkout)
- REPO: {{ github_repo }}, base branch `{{ base_branch }}`
- TEST_COMMAND: {{ test_command }}
- Record the run summary with the `submit_summary` tool.

## Facts for this project

- Jira site `{{ jira_url }}`, project `{{ jira_project }}`. QA Instructions field `{{ qa_instructions_field }}` (ADF).
- Statuses: in progress **{{ status_in_progress }}**, hand-off **{{ status_code_review }}**.
- Follow the project's own conventions (its CLAUDE.md is in your instructions when present): smallest reasonable change, match surrounding style, real implementations, never `--no-verify`.

## Procedure

1. **Read the ticket** `{{ ticket_key }}` and every comment. The triage analysis (root cause, evidence, suggested fix) is your spec; human comments may have chosen between options or added direction.
2. **Decision gate.** If the triage rated the ticket 🟡 or 🔴 and no human comment has settled the direction, or the fix needs a product or design choice nobody has made, do NOT write speculative code. Comment on the ticket (first line `[tedsbot]`) naming exactly the decision you need, record the summary with status `blocked`, and STOP.
3. **Transition** the ticket to **{{ status_in_progress }}** (fetch transitions live; match on the target status name).
4. **Branch**: `git checkout -b {{ branch }}` from the current `{{ base_branch }}`.
5. **Implement** the smallest change that resolves the root cause, in the surrounding style. No refactors, no unrelated changes.
6. **Tests.** Write tests that demonstrate the fix, following the project's conventions.
{% if test_command != "none" %}   Run `{{ test_command }}` and read the whole result. Fix what your change broke. Report the real outcome in the PR body and the summary: the exact command and its summary line.
{% else %}   You cannot run the tests here; do not claim they pass. Say in the PR body that CI validates them.
{% endif %}
7. **Commit** with a clear message ending in the trailers `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Ticket: {{ ticket_key }}`. **Push** the branch: `git push -u origin {{ branch }}`.
8. **Open a draft PR** against `{{ base_branch }}`: `gh pr create --repo {{ github_repo }} --draft --base {{ base_branch }} --head {{ branch }} --title "{{ ticket_key }}: <short summary>" --body-file <file you write in the run directory is not allowed; pass the body inline with --body>`. The body states what changed and why, the root cause, the test outcome exactly as observed, that this is an auto-generated draft for review, and the line `Ticket: {{ ticket_key }}`. Note the PR URL the command prints.
9. **QA Instructions**: populate `{{ qa_instructions_field }}` (ADF) with numbered verification steps a human QA can follow: role, navigation, action, expected result.
10. **Comment** the PR link on the ticket: one plain sentence plus the URL, first line `[tedsbot]`.
11. **Transition** the ticket to **{{ status_code_review }}** (match on the target status name; if no transition reaches it, leave the ticket in progress and say so in the summary).
12. **Record the summary** with `submit_summary`:

```json
{"kind": "fix", "ticket": "{{ ticket_key }}", "ticket_url": "{{ jira_url }}/browse/{{ ticket_key }}", "status": "draft PR opened", "pr_url": "https://github.com/{{ github_repo }}/pull/NNN", "title": "the ticket summary", "headline": "one technical line: what changed and where, and the test outcome", "tldr": "at most two plain sentences for non-engineers: what users get and that a PR is ready for review", "recommendation": null, "outcome": null, "ok": true}
```

`status` is one of `draft PR opened`, `blocked` (decision gate), `already open` (an open PR for the branch already existed). Write `tldr` and `headline` as plain sentences with no em-dashes and no semicolons.

## Rules

- **Draft only.** Never open a non-draft PR, never merge, never transition the ticket past **{{ status_code_review }}**.
- **Smallest reasonable change.** If the fix balloons beyond what the analysis described, stop, comment, and record `blocked`.
- **Honesty.** Report test results exactly as observed; if you could not run them, say so.
- Every comment you write starts with `[tedsbot]`. Plain sentences everywhere: no em-dashes, no semicolons.
- Touch only what the fix requires. Never use `--no-verify`.
```
(Replace the `--body-file` aside in step 8 with simply: `--body "<body>"`; the template must read `--body "..."` and not mention body files.)

- [ ] **Step 4: Runner changes** in `src/tedsbot/runner.py`: add `FIX_TOOLS`; `AUTH_ENV = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "GH_TOKEN")`; in `build_options`, after `allowed = list(spec.tools)`: `if spec.kind == "fix" and cfg.fix.test_command: allowed.append(f"Bash({cfg.fix.test_command}:*)")`.

- [ ] **Step 5: Run tests** → green; ruff clean. **Step 6: Commit** `feat: fix prompt template and fix-run tool allowlist`.

---

### Task 6: `tedsbot fix` command

**Files:**
- Create: `src/tedsbot/commands/fix.py`, `tests/unit/test_fix_command.py`
- Modify: `src/tedsbot/cli.py`

**Interfaces:**
- `commands.fix.build_fix_spec(cfg: Config, key: str) -> RunSpec` (kind `fix`, prompt `fix`, inputs as Task 5, `max_turns=cfg.agent.max_turns.fix`, tools `FIX_TOOLS`, `include_edit_tools=True`, `run_id=key`).
- `async commands.fix.fix(cfg, key, *, run_fn=None, home=None, gates_fn=run_fix_gates, watch_fn=watch_ci, tickets=None, notifier=None) -> tuple[RunSummary, Path]`:
  1. `run_dir = new_run_dir("fix", key, home)`; `tickets = tickets or registry.get_ticketing(cfg.tickets)`; `notifier = notifier or registry.get_notifier(cfg.notify)`.
  2. `branch = f"{cfg.fix.branch_prefix}{key}"`; call `gates_fn(cfg, tickets.status_of, key, branch)`; on `GateError` build `RunSummary(kind="fix", ticket=key, ticket_url=f"{cfg.tickets.url}/browse/{key}", status="gate refused", headline=str(exc), tldr="The fix did not start because a precondition failed.", ok=False)`, write `summary.resolved.json`, post `slack_line`, return.
  3. `summary = await (run_fn or runner.run)(cfg, spec, run_dir)` (the runner posts the first Slack message).
  4. If `summary.ok and summary.status == "draft PR opened" and summary.pr_url and cfg.fix.ci_wait_minutes > 0`: `verdict = watch_fn(summary.pr_url, cfg.fix.ci_wait_minutes, cfg.fix.ci_poll_seconds)`; on `failed`: `tickets.comment(key, f"[tedsbot] CI is red on {summary.pr_url}: {', '.join(verdict.failing)}. Handing back for a human to look at.")`, `summary = summary.model_copy(update={"status": "CI red, handed back", "headline": f"CI failed: {', '.join(verdict.failing)}. {summary.headline}"[:300]})`; on `passed`: `status="CI green"`; on `timeout`/`none`: leave the summary as is. When the status changed, rewrite `summary.resolved.json` and post a second `slack_line`.
  5. Return `(summary, run_dir)`.
- `commands.fix.main_fix(cfg, key) -> int` prints the final `slack_line` and returns `0` iff `summary.ok`.
- `cli._dispatch`: `fix` branch mirroring `triage` (config error → 2).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_fix_command.py`:
```python
# ABOUTME: Tests the fix command orchestration with injected gates, run function,
# ABOUTME: CI watch, ticketing and notifier; no agent, git, or gh is ever real.
import json
from pathlib import Path

import httpx
import pytest
import respx
import yaml

from tedsbot.ci import CiVerdict
from tedsbot.cli import main
from tedsbot.commands.fix import build_fix_spec, fix
from tedsbot.config import load_config
from tedsbot.errors import GateError
from tedsbot.runner import FIX_TOOLS
from tedsbot.summary import RunSummary

SLACK = "https://hooks.slack.example/T/B/X"


@pytest.fixture
def cfg(tmp_path: Path, config_dict: dict, env_tokens: None):
    config_dict["fix"] = {"ci_wait_minutes": 5}
    p = tmp_path / "tedsbot.yaml"
    p.write_text(yaml.safe_dump(config_dict))
    return load_config(p)


class FakeTickets:
    def __init__(self, status: str = "Approved For Fix") -> None:
        self.status, self.comments = status, []

    def status_of(self, key: str) -> str:
        return self.status

    def comment(self, key: str, body: str) -> None:
        self.comments.append((key, body))


class FakeNotifier:
    def __init__(self) -> None:
        self.posts: list[str] = []

    def post(self, text: str) -> None:
        self.posts.append(text)


def _draft(pr="https://github.com/example-org/example-app/pull/9"):
    async def run_fn(c, spec, run_dir):
        return RunSummary(kind="fix", ticket="APP-7", ticket_url="https://example.atlassian.net/browse/APP-7",
                          status="draft PR opened", pr_url=pr, headline="guarded null", tldr="Fixed.", ok=True)
    return run_fn


def test_fix_spec(cfg) -> None:
    spec = build_fix_spec(cfg, "APP-7")
    assert spec.kind == "fix" and spec.prompt_name == "fix" and spec.include_edit_tools
    assert spec.tools == FIX_TOOLS and spec.max_turns == 150
    assert spec.inputs == {"ticket_key": "APP-7", "branch": "tedsbot/APP-7", "base_branch": "main",
                           "github_repo": "example-org/example-app", "test_command": "none"}


async def test_gate_refusal_notifies_and_never_runs_the_agent(cfg, temp_home: Path) -> None:
    notifier, tickets = FakeNotifier(), FakeTickets()
    started = []

    async def run_fn(c, spec, run_dir):
        started.append(1)

    def gates(c, status_of, key, branch):
        raise GateError("checkout has uncommitted changes")

    summary, run_dir = await fix(cfg, "APP-7", run_fn=run_fn, gates_fn=gates, tickets=tickets, notifier=notifier)
    assert not started and summary.ok is False and summary.status == "gate refused"
    assert "uncommitted" in summary.headline and (run_dir / "summary.resolved.json").exists()
    assert notifier.posts and "precondition failed" in notifier.posts[0]


async def test_red_ci_hands_back_with_comment_and_second_message(cfg, temp_home: Path) -> None:
    notifier, tickets = FakeNotifier(), FakeTickets()
    summary, run_dir = await fix(cfg, "APP-7", run_fn=_draft(), gates_fn=lambda *a: None,
                                 watch_fn=lambda url, w, p: CiVerdict("failed", ["tests"]), tickets=tickets, notifier=notifier)
    assert summary.status == "CI red, handed back" and summary.headline.startswith("CI failed: tests")
    assert tickets.comments and tickets.comments[0][1].startswith("[tedsbot] CI is red")
    assert any("handed back" in p for p in notifier.posts)
    assert json.loads((run_dir / "summary.resolved.json").read_text())["status"] == "CI red, handed back"


async def test_green_ci_posts_second_message_without_comment(cfg, temp_home: Path) -> None:
    notifier, tickets = FakeNotifier(), FakeTickets()
    summary, _ = await fix(cfg, "APP-7", run_fn=_draft(), gates_fn=lambda *a: None,
                           watch_fn=lambda url, w, p: CiVerdict("passed"), tickets=tickets, notifier=notifier)
    assert summary.status == "CI green" and not tickets.comments and any("passed CI" in p for p in notifier.posts)


async def test_no_ci_wait_when_disabled(tmp_path: Path, config_dict: dict, env_tokens: None, temp_home: Path) -> None:
    p = tmp_path / "t.yaml"; p.write_text(yaml.safe_dump(config_dict)); c = load_config(p)
    called = []
    summary, _ = await fix(c, "APP-7", run_fn=_draft(), gates_fn=lambda *a: None,
                           watch_fn=lambda *a: called.append(1), tickets=FakeTickets(), notifier=FakeNotifier())
    assert not called and summary.status == "draft PR opened"


def test_cli_fix_exit_codes(tmp_path: Path, config_dict: dict, env_tokens: None, temp_home: Path,
                            monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "tedsbot.yaml"; p.write_text(yaml.safe_dump(config_dict))
    monkeypatch.setattr("tedsbot.commands.fix._run", _draft())
    monkeypatch.setattr("tedsbot.commands.fix._gates", lambda *a: None)
    monkeypatch.setattr("tedsbot.commands.fix._ticketing", lambda cfg: FakeTickets())
    monkeypatch.setattr("tedsbot.commands.fix._notifier", lambda cfg: FakeNotifier())
    assert main(["-c", str(p), "fix", "APP-7"]) == 0
    assert "Draft PR opened" in capsys.readouterr().out
    assert main(["-c", str(tmp_path / "absent.yaml"), "fix", "APP-7"]) == 2
```

- [ ] **Step 2: Run tests** → `ModuleNotFoundError: No module named 'tedsbot.commands.fix'`.

- [ ] **Step 3: Implement `src/tedsbot/commands/fix.py`**

```python
# ABOUTME: The `tedsbot fix` command: gates, the fix agent run, the CI watch that hands
# ABOUTME: red results back, and the Slack message per stage.
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from tedsbot import registry, runner
from tedsbot.ci import CiVerdict, watch_ci
from tedsbot.config import Config
from tedsbot.errors import GateError, ProviderError
from tedsbot.gates import run_fix_gates
from tedsbot.runner import FIX_TOOLS, RunSpec, new_run_dir
from tedsbot.summary import RunSummary, slack_line

RunFn = Callable[[Config, RunSpec, Path], Awaitable[RunSummary]]
_run: RunFn = runner.run
_gates = run_fix_gates
_watch = watch_ci


def _ticketing(cfg: Config) -> Any:
    return registry.get_ticketing(cfg.tickets)


def _notifier(cfg: Config) -> Any:
    return registry.get_notifier(cfg.notify)


def build_fix_spec(cfg: Config, key: str) -> RunSpec:
    return RunSpec(
        kind="fix", prompt_name="fix",
        inputs={"ticket_key": key, "branch": f"{cfg.fix.branch_prefix}{key}", "base_branch": cfg.repo.base_branch,
                "github_repo": cfg.repo.github, "test_command": cfg.fix.test_command or "none"},
        max_turns=cfg.agent.max_turns.fix, tools=list(FIX_TOOLS), include_edit_tools=True, run_id=key,
    )


def _post(notifier: Any, summary: RunSummary, run_dir: Path, cfg: Config) -> None:
    try:
        notifier.post(slack_line(summary, run_dir, cfg.tickets.statuses.fix_approved))
    except ProviderError:
        pass


def _write(summary: RunSummary, run_dir: Path) -> None:
    (run_dir / "summary.resolved.json").write_text(summary.model_dump_json(indent=2))


async def fix(cfg: Config, key: str, *, run_fn: RunFn | None = None, home: Path | None = None,
              gates_fn=None, watch_fn=None, tickets: Any = None, notifier: Any = None) -> tuple[RunSummary, Path]:
    run_dir = new_run_dir("fix", key, home)
    tickets = tickets or _ticketing(cfg)
    notifier = notifier or _notifier(cfg)
    branch = f"{cfg.fix.branch_prefix}{key}"
    try:
        (gates_fn or _gates)(cfg, tickets.status_of, key, branch)
    except GateError as exc:
        summary = RunSummary(kind="fix", ticket=key, ticket_url=f"{cfg.tickets.url}/browse/{key}", status="gate refused",
                             headline=str(exc)[:300], tldr="The fix did not start because a precondition failed.", ok=False)
        _write(summary, run_dir)
        _post(notifier, summary, run_dir, cfg)
        return summary, run_dir
    summary = await (run_fn or _run)(cfg, build_fix_spec(cfg, key), run_dir)
    if summary.ok and summary.status == "draft PR opened" and summary.pr_url and cfg.fix.ci_wait_minutes > 0:
        verdict: CiVerdict = (watch_fn or _watch)(summary.pr_url, cfg.fix.ci_wait_minutes, cfg.fix.ci_poll_seconds)
        if verdict.state == "failed":
            failing = ", ".join(verdict.failing) or "unknown checks"
            tickets.comment(key, f"[tedsbot] CI is red on {summary.pr_url}: {failing}. Handing back for a human to look at.")
            summary = summary.model_copy(update={"status": "CI red, handed back", "headline": f"CI failed: {failing}. {summary.headline}"[:300]})
        elif verdict.state == "passed":
            summary = summary.model_copy(update={"status": "CI green"})
        if summary.status in ("CI red, handed back", "CI green"):
            _write(summary, run_dir)
            _post(notifier, summary, run_dir, cfg)
    return summary, run_dir


def main_fix(cfg: Config, key: str) -> int:
    summary, run_dir = asyncio.run(fix(cfg, key, run_fn=_run, gates_fn=_gates, watch_fn=_watch,
                                       tickets=_ticketing(cfg), notifier=_notifier(cfg)))
    print(slack_line(summary, run_dir, cfg.tickets.statuses.fix_approved))
    return 0 if summary.ok else 1
```
Note: the runner's own `run()` posts the first Slack message (draft PR opened / blocked); `fix()` posts only the gate refusal and the CI follow-up, so no message is duplicated. Also: in `_write` on the CI path the runner already wrote `summary.resolved.json`; overwriting it with the updated status is intended.

In `src/tedsbot/cli.py` `_dispatch`, add before the fallthrough:
```python
    if ns.command == "fix":
        from tedsbot.commands.fix import main_fix
        from tedsbot.config import load_config
        from tedsbot.errors import ConfigError

        try:
            cfg = load_config(config_path)
        except ConfigError as exc:
            print(f"config error: {exc}", file=sys.stderr)
            return 2
        return main_fix(cfg, ns.target)
```

- [ ] **Step 4: Run tests** → green; ruff clean. **Step 5: Commit** `feat: tedsbot fix command with gates and CI hand-back`.

---

### Task 7: Post-triage status re-read

**Files:**
- Modify: `src/tedsbot/commands/triage.py`, `tests/unit/test_triage_commands.py`

**Interfaces:**
- `commands.triage.triage(...)` gains `tickets: Any = None` and `notifier: Any = None` (defaults from the registry). After the run, when `summary.ok` and `summary.ticket`: `status = tickets.status_of(summary.ticket)`; if `status not in (cfg.tickets.statuses.intake, cfg.tickets.statuses.triage_target)`, post `f"*⚠️ Ticket {summary.ticket} is in '{status}' after triage; expected '{intake}' or '{triage_target}'. The agent must never move a ticket past the triage target. Check the transcript in {run_dir}.*"` via the notifier and log a warning. `ProviderError` from `status_of` is logged, never raised.

- [ ] **Step 1: Write the failing test**

```python
async def test_triage_warns_when_ticket_moved_past_target(cfg, temp_home: Path) -> None:
    posts = []

    class N:
        def post(self, t): posts.append(t)

    class T:
        def status_of(self, key): return "Done"

    async def fake_run(c, spec, run_dir):
        return RunSummary(kind="triage_sentry", ticket="APP-1", headline="ok", tldr="t", ok=True)

    await triage(cfg, build_sentry_spec(cfg, "APP-1"), run_fn=fake_run, tickets=T(), notifier=N())
    assert posts and "is in 'Done' after triage" in posts[0]


async def test_triage_silent_when_ticket_in_target(cfg, temp_home: Path) -> None:
    posts = []

    class N:
        def post(self, t): posts.append(t)

    class T:
        def status_of(self, key): return "Dev Team Review"

    async def fake_run(c, spec, run_dir):
        return RunSummary(kind="triage_sentry", ticket="APP-1", headline="ok", tldr="t", ok=True)

    await triage(cfg, build_sentry_spec(cfg, "APP-1"), run_fn=fake_run, tickets=T(), notifier=N())
    assert posts == []
```
(Existing tests that call `triage(...)` without `tickets`/`notifier` must not hit the registry's real providers: `FakeTickets`-style defaults are required in those tests too. Update `test_triage_creates_run_dir_and_returns_summary` to pass `tickets=T()` with status `"Dev Team Review"` and a no-op notifier; `main_triage` wires the registry.)

- [ ] **Step 2: Run** → fails (`TypeError: unexpected keyword argument 'tickets'`).
- [ ] **Step 3: Implement** per the interface; `main_triage` passes `tickets=registry.get_ticketing(cfg.tickets)` and `notifier=registry.get_notifier(cfg.notify)`; the CLI test that monkeypatches `_run` must also monkeypatch `tedsbot.commands.triage._ticketing`/`_notifier` factory functions (add these two module-level factories, mirroring `commands/fix.py`).
- [ ] **Step 4: Run** → green. **Step 5: Commit** `feat: warn when a triaged ticket ends up past the triage target`.

---

### Task 8: End-to-end fix test, README, example config, wrapper notes

**Files:**
- Create: `tests/e2e/test_fix_e2e.py`
- Modify: `README.md`, `tedsbot.example.yaml` (comments only), `tests/unit/test_cli.py` (fix parser test)

**Interfaces:**
- e2e reads `TEDSBOT_E2E_FIX_CONFIG` (a config whose `repo.path` is a clean clone of this repository on `main` and whose `repo.github` is `tauhir/tedsbot-triage-worker` or a fork), `TEDSBOT_E2E_FIX_TICKET` (a ticket in the approved status describing a planted bug in that clone). Skips when either is unset. Runs `uv run tedsbot -c <config> fix <KEY>`, asserts exit 0 and `summary.resolved.json` has `status` in (`draft PR opened`, `CI green`, `CI red, handed back`) and a `pr_url`; then cleans up: `gh pr close <pr_url> --delete-branch --comment "e2e run, closing"`.

- [ ] **Step 1: Write the e2e test** (gated exactly like `tests/e2e/test_triage_e2e.py`, reusing `_snapshot`/`_new_run_dir`/`_required_env` by importing them from that module or duplicating the three helpers with ABOUTME headers).
- [ ] **Step 2: Add to `tests/unit/test_cli.py`**: `test_fix_parser_takes_a_ticket_key` asserting `parse_args(["fix", "APP-7"]).target == "APP-7"`.
- [ ] **Step 3: README**: in Status, milestone 2a ships `fix`. New section "## The fix stage" after "First run": the approval flow (human moves the ticket to the approved status; run `tedsbot fix <KEY>`), what the gates check, `fix.test_command`, `fix.ci_wait_minutes` and the hand-back behaviour, the `GH_TOKEN` requirement and that PRs are authored by that identity, "draft only, never past code review", and the recommendation to give the worker its own clone. Add to the Troubleshooting table: `gate refused: checkout ... has uncommitted changes` → the worker needs its own clean clone; `gh pr list failed: not logged in` → set `GH_TOKEN` or `gh auth login` in the worker's environment.
- [ ] **Step 4: Run** `uv run pytest -n auto -q` (e2e SKIPPED), ruff clean. **Step 5: Commit** `docs+test: fix stage e2e gate and README section`, push the branch.

---

## Self-review against the spec addendum

- Own clone + own branch: gates (Task 2), README (Task 8). GitHub identity via `GH_TOKEN`: runner passthrough (Task 5), README (Task 8). Tests: `fix.test_command` (Tasks 1, 5). CI watch and hand-back: Tasks 3, 6. Statuses and Slack: Task 4. e2e on this repo: Task 8. Post-triage re-read: Task 7.
- Every task has tests with real assertions; no real `gh`, git push, or agent in unit tests; git is used only on `tmp_path` repos.
- Type consistency: `RunSpec` fields unchanged; `RunSummary.status` stays `str | None` with fix-run validation; `slack_line(summary, run_dir, approve_status)` signature unchanged; `Ticketing.status_of`/`comment` as in milestone 1.
