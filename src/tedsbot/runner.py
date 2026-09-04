# ABOUTME: Builds ClaudeAgentOptions from config and a RunSpec, runs the agent,
# ABOUTME: records the transcript, reads the summary, and notifies.
from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from tedsbot import registry
from tedsbot.config import Config
from tedsbot.errors import ProviderError
from tedsbot.knowledge import assemble_knowledge
from tedsbot.prompts import render_prompt
from tedsbot.summary import RunKind, RunSummary, read_summary, slack_line

log = logging.getLogger(__name__)

TRIAGE_TOOLS = [
    "Read", "Grep", "Glob",
    "Bash(git log:*)", "Bash(git show:*)", "Bash(git blame:*)", "Bash(git diff:*)",
]
AUTH_ENV = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")


@dataclass
class RunSpec:
    kind: RunKind
    prompt_name: str
    inputs: dict[str, str]
    max_turns: int
    tools: list[str]
    run_id: str
    include_edit_tools: bool = False
    extra_facts: dict[str, str] = field(default_factory=dict)


def new_run_dir(kind: str, target: str, home: Path | None = None) -> Path:
    last_segment = [seg for seg in target.split("/") if seg][-1]
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", last_segment).strip("-")[-40:]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = (home or Path.home()) / ".tedsbot" / "runs"
    run_dir = base / f"{stamp}-{kind}-{safe}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _project_claude_md(repo: Path) -> str | None:
    for candidate in (repo / "CLAUDE.md", repo / ".claude" / "CLAUDE.md"):
        if candidate.is_file():
            return f"## Project CLAUDE.md\n\n{candidate.read_text()}"
    return None


def build_options(cfg: Config, spec: RunSpec, run_dir: Path) -> tuple[ClaudeAgentOptions, str]:
    errors = registry.get_error_source(cfg.errors)
    tickets = registry.get_ticketing(cfg.tickets)
    notifier = registry.get_notifier(cfg.notify)
    providers = [errors, tickets]
    if cfg.logs is not None:
        providers.append(registry.get_log_store(cfg.logs))

    extra = []
    if spec.include_edit_tools and (claude_md := _project_claude_md(cfg.repo.path)):
        extra.append(claude_md)
    knowledge = assemble_knowledge(
        [p.knowledge() for p in providers], cfg.agent.knowledge_dir,
        cfg.agent.knowledge_size_warn_kb, extra_sections=extra,
    )
    for warning in knowledge.warnings:
        log.warning(warning)

    facts: dict[str, str] = {}
    for p in providers:
        facts.update(p.prompt_facts())
    facts.update(spec.extra_facts)
    summary_path = run_dir / "summary.json"
    prompt = render_prompt(spec.prompt_name, facts, summary_path=str(summary_path), **spec.inputs)

    mcp_servers: dict[str, Any] = {}
    allowed = list(spec.tools)
    for server in [p.mcp_server() for p in providers] + [notifier.sdk_server()]:
        mcp_servers[server.name] = server.config
        allowed.extend(server.allowed_tools)
    allowed.append(f"Write({summary_path})")

    append = (
        f"{knowledge.text}\n\n## Run directory\n\n"
        f"Your run directory is `{run_dir}`. The only file you may write is `{summary_path}`."
    )
    env = {k: os.environ[k] for k in AUTH_ENV if k in os.environ}
    options = ClaudeAgentOptions(
        system_prompt={
            "type": "preset", "preset": "claude_code",
            "append": append, "exclude_dynamic_sections": True,
        },
        permission_mode="dontAsk",
        setting_sources=[],
        strict_mcp_config=True,
        cwd=cfg.repo.path,
        add_dirs=[run_dir],
        model=cfg.agent.model,
        max_turns=spec.max_turns,
        mcp_servers=mcp_servers,
        allowed_tools=allowed,
        env=env,
    )
    return options, prompt


def _jsonable(message: Any) -> Any:
    if dataclasses.is_dataclass(message):
        try:
            return dataclasses.asdict(message)
        except TypeError:
            pass
    return {"repr": repr(message)}


async def run(cfg: Config, spec: RunSpec, run_dir: Path) -> RunSummary:
    options, prompt = build_options(cfg, spec, run_dir)
    (run_dir / "prompt.md").write_text(prompt)
    transcript = run_dir / "transcript.jsonl"
    final_text = ""
    with transcript.open("a") as fh:
        try:
            async for message in query(prompt=prompt, options=options):
                fh.write(json.dumps({"type": type(message).__name__, "data": _jsonable(message)}, default=str) + "\n")
                if isinstance(message, ResultMessage):
                    final_text = str(message.result or "")
        except Exception as exc:  # the SDK raises after yielding an error result
            log.exception("agent run failed")
            fh.write(json.dumps({"type": "exception", "data": repr(exc)}) + "\n")
            final_text = final_text or f"agent run failed: {exc}"
    summary = read_summary(run_dir / "summary.json", spec.kind, final_text)
    (run_dir / "summary.resolved.json").write_text(summary.model_dump_json(indent=2))
    try:
        registry.get_notifier(cfg.notify).post(slack_line(summary, run_dir))
    except ProviderError as exc:
        log.error("notification failed: %s", exc)
    return summary
