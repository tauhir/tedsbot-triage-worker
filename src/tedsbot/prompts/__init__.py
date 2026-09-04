# ABOUTME: Renders the run-type prompt templates with provider facts and run
# ABOUTME: inputs. Missing variables raise so a bad config never reaches the agent.
from __future__ import annotations

from importlib import resources

from jinja2 import Environment, StrictUndefined

_env = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)


def render_prompt(name: str, facts: dict[str, str], **inputs: str) -> str:
    path = resources.files("tedsbot.prompts").joinpath(f"{name}.md.j2")
    if not path.is_file():
        raise FileNotFoundError(f"no prompt template named {name!r}")
    template = _env.from_string(path.read_text())
    return template.render(**facts, **inputs)
