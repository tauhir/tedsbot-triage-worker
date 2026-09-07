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
