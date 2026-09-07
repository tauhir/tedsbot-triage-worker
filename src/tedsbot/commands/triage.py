# ABOUTME: The `tedsbot triage` commands: build a RunSpec for a Sentry issue or
# ABOUTME: a ticket, create the run directory, and hand off to the runner.
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from tedsbot import registry, runner
from tedsbot.config import Config
from tedsbot.errors import ProviderError
from tedsbot.runner import TRIAGE_TOOLS, RunSpec, new_run_dir
from tedsbot.summary import RunSummary, slack_line

log = logging.getLogger(__name__)

RunFn = Callable[[Config, RunSpec, Path], Awaitable[RunSummary]]
_run: RunFn = runner.run

# Outcomes where the agent itself just created and transitioned the ticket; the
# others (duplicate, not_a_bug, analysed_existing, insufficient_repro) leave an
# existing ticket's status alone by design, so a re-read there would be a false positive.
RE_READ_OUTCOMES = ("new_ticket", "regression")


def _ticketing(cfg: Config) -> Any:
    return registry.get_ticketing(cfg.tickets)


def _notifier(cfg: Config) -> Any:
    return registry.get_notifier(cfg.notify)


def build_sentry_spec(cfg: Config, target: str) -> RunSpec:
    return RunSpec(kind="triage_sentry", prompt_name="triage_sentry",
                   inputs={"sentry_issue": target}, max_turns=cfg.agent.max_turns.triage,
                   tools=list(TRIAGE_TOOLS), run_id=target)


def build_ticket_spec(cfg: Config, key: str) -> RunSpec:
    return RunSpec(kind="triage_ticket", prompt_name="triage_ticket",
                   inputs={"ticket_key": key}, max_turns=cfg.agent.max_turns.triage,
                   tools=list(TRIAGE_TOOLS), run_id=key)


async def triage(cfg: Config, spec: RunSpec, *, run_fn: RunFn | None = None, home: Path | None = None,
                 tickets: Any = None, notifier: Any = None) -> tuple[RunSummary, Path]:
    run_dir = new_run_dir(spec.kind, spec.run_id, home)
    summary = await (run_fn or _run)(cfg, spec, run_dir)
    if summary.ok and summary.ticket and summary.outcome in RE_READ_OUTCOMES:
        try:
            status = (tickets or _ticketing(cfg)).status_of(summary.ticket)
        except ProviderError as exc:
            log.warning("failed to re-read status for %s: %s", summary.ticket, exc)
        else:
            statuses = cfg.tickets.statuses
            if status not in (statuses.intake, statuses.triage_target):
                warning = (
                    f"*⚠️ Ticket {summary.ticket} is in '{status}' after triage; expected "
                    f"'{statuses.intake}' or '{statuses.triage_target}'. The agent must never move "
                    f"a ticket past the triage target. Check the transcript in {run_dir}.*"
                )
                log.warning(warning)
                try:
                    (notifier or _notifier(cfg)).post(warning)
                except ProviderError as exc:
                    log.warning("failed to post triage status warning for %s: %s", summary.ticket, exc)
    return summary, run_dir


def main_triage(cfg: Config, kind: str, target: str) -> int:
    spec = build_sentry_spec(cfg, target) if kind == "sentry" else build_ticket_spec(cfg, target)
    summary, run_dir = asyncio.run(triage(cfg, spec, run_fn=_run, tickets=_ticketing(cfg), notifier=_notifier(cfg)))
    print(slack_line(summary, run_dir, cfg.tickets.statuses.fix_approved))
    return 0 if summary.ok else 1
