# ABOUTME: The `tedsbot triage` commands: build a RunSpec for a Sentry issue or
# ABOUTME: a ticket, create the run directory, and hand off to the runner.
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from tedsbot import runner
from tedsbot.config import Config
from tedsbot.runner import TRIAGE_TOOLS, RunSpec, new_run_dir
from tedsbot.summary import RunSummary, slack_line

RunFn = Callable[[Config, RunSpec, Path], Awaitable[RunSummary]]
_run: RunFn = runner.run


def build_sentry_spec(cfg: Config, target: str) -> RunSpec:
    return RunSpec(kind="triage_sentry", prompt_name="triage_sentry",
                   inputs={"sentry_issue": target}, max_turns=cfg.agent.max_turns.triage,
                   tools=list(TRIAGE_TOOLS), run_id=target)


def build_ticket_spec(cfg: Config, key: str) -> RunSpec:
    return RunSpec(kind="triage_ticket", prompt_name="triage_ticket",
                   inputs={"ticket_key": key}, max_turns=cfg.agent.max_turns.triage,
                   tools=list(TRIAGE_TOOLS), run_id=key)


async def triage(cfg: Config, spec: RunSpec, *, run_fn: RunFn | None = None,
                 home: Path | None = None) -> tuple[RunSummary, Path]:
    run_dir = new_run_dir(spec.kind, spec.run_id, home)
    summary = await (run_fn or _run)(cfg, spec, run_dir)
    return summary, run_dir


def main_triage(cfg: Config, kind: str, target: str) -> int:
    spec = build_sentry_spec(cfg, target) if kind == "sentry" else build_ticket_spec(cfg, target)
    summary, run_dir = asyncio.run(triage(cfg, spec, run_fn=_run))
    print(slack_line(summary, run_dir, cfg.tickets.statuses.fix_approved))
    return 0 if summary.ok else 1
