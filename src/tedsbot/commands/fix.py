# ABOUTME: The `tedsbot fix` command: gates, the fix agent run, the CI watch that hands
# ABOUTME: red results back, and the Slack message per stage.
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

from tedsbot import registry, runner
from tedsbot.ci import CiVerdict, watch_ci
from tedsbot.config import Config
from tedsbot.errors import GateError, ProviderError
from tedsbot.gates import restore_checkout, run_fix_gates
from tedsbot.runner import FIX_TOOLS, RunSpec, new_run_dir
from tedsbot.summary import RunSummary, slack_line

log = logging.getLogger(__name__)

RunFn = Callable[[Config, RunSpec, Path], Awaitable[RunSummary]]
_run: RunFn = runner.run
_gates = run_fix_gates
_watch = watch_ci
_restore = restore_checkout


def _ticketing(cfg: Config) -> Any:
    return registry.get_ticketing(cfg.tickets)


def _notifier(cfg: Config) -> Any:
    return registry.get_notifier(cfg.notify)


def pr_body_path(cfg: Config) -> Path:
    """Where the agent writes the PR body.

    A fix run may write only inside the checkout, and `git status` ignores
    `.git/`, so a scratch file under it is both writable and invisible to the
    commit the agent makes.
    """
    return cfg.repo.path / ".git" / "tedsbot" / "pr-body.md"


def build_fix_spec(cfg: Config, key: str) -> RunSpec:
    return RunSpec(
        kind="fix", prompt_name="fix",
        inputs={"ticket_key": key, "branch": f"{cfg.fix.branch_prefix}{key}", "base_branch": cfg.repo.base_branch,
                "github_repo": cfg.repo.github, "test_command": cfg.fix.test_command or "none",
                "pr_body_path": str(pr_body_path(cfg))},
        max_turns=cfg.agent.max_turns.fix, tools=list(FIX_TOOLS), include_edit_tools=True, run_id=key,
    )


def _post_text(notifier: Any, text: str) -> None:
    try:
        notifier.post(text)
    except ProviderError as exc:
        # Slack being down must not lose the run, but a swallowed post is the
        # reason a result nobody saw looks like a run that never happened.
        log.error("notification failed: %s", exc)


def _post(notifier: Any, summary: RunSummary, run_dir: Path, cfg: Config) -> None:
    _post_text(notifier, slack_line(summary, run_dir, cfg.tickets.statuses.fix_approved))


def _write(summary: RunSummary, run_dir: Path) -> None:
    (run_dir / "summary.resolved.json").write_text(summary.model_dump_json(indent=2))


async def fix(cfg: Config, key: str, *, run_fn: RunFn | None = None, home: Path | None = None,
              gates_fn=None, watch_fn=None, restore_fn=None, tickets: Any = None,
              notifier: Any = None) -> tuple[RunSummary, Path]:
    run_dir = new_run_dir("fix", key, home)
    tickets = tickets or _ticketing(cfg)
    notifier = notifier or _notifier(cfg)
    branch = f"{cfg.fix.branch_prefix}{key}"
    try:
        (gates_fn or _gates)(cfg, tickets.status_of, key, branch)
    except (GateError, ProviderError, httpx.HTTPError, ValueError) as exc:
        # A gate that cannot be evaluated refuses the run for the same reason a
        # gate that fails does: nothing has confirmed the fix is safe to start.
        headline = str(exc) if isinstance(exc, GateError) else f"gate could not be evaluated: {exc}"
        summary = RunSummary(kind="fix", ticket=key, ticket_url=f"{cfg.tickets.url}/browse/{key}", status="gate refused",
                             headline=headline[:300], tldr="The fix did not start because a precondition failed.", ok=False)
        _write(summary, run_dir)
        _post(notifier, summary, run_dir, cfg)
        return summary, run_dir
    try:
        pr_body_path(cfg).parent.mkdir(parents=True, exist_ok=True)
        summary = await (run_fn or _run)(cfg, build_fix_spec(cfg, key), run_dir)
        if summary.ok and summary.status == "draft PR opened" and summary.pr_url and cfg.fix.ci_wait_minutes > 0:
            verdict: CiVerdict = (watch_fn or _watch)(summary.pr_url, cfg.fix.ci_wait_minutes, cfg.fix.ci_poll_seconds)
            if verdict.state == "failed":
                failing = ", ".join(verdict.failing) or "unknown checks"
                try:
                    tickets.comment(key, f"[tedsbot] CI is red on {summary.pr_url}: {failing}. Handing back for a human to look at.")
                except ProviderError as exc:
                    # The ticket comment is a courtesy; a human still needs the
                    # status update and the Slack post even if Jira is down.
                    log.error("failed to comment on %s: %s", key, exc)
                summary = summary.model_copy(update={"status": "CI red, handed back", "headline": f"CI failed: {failing}. {summary.headline}"[:300]})
            elif verdict.state == "passed":
                summary = summary.model_copy(update={"status": "CI green"})
            if summary.status in ("CI red, handed back", "CI green"):
                _write(summary, run_dir)
                _post(notifier, summary, run_dir, cfg)
    finally:
        # The run leaves the checkout on the bot branch, which the clean-checkout
        # gate would refuse next time, so it is restored however the run ended.
        note = (restore_fn or _restore)(cfg.repo.path, cfg.repo.base_branch)
        if note:
            log.warning("%s", note)
            _post_text(notifier, f"*Note:* {note}")
    return summary, run_dir


def main_fix(cfg: Config, key: str) -> int:
    summary, run_dir = asyncio.run(fix(cfg, key, run_fn=_run, gates_fn=_gates, watch_fn=_watch,
                                       restore_fn=_restore, tickets=_ticketing(cfg), notifier=_notifier(cfg)))
    print(slack_line(summary, run_dir, cfg.tickets.statuses.fix_approved))
    return 0 if summary.ok else 1
