# ABOUTME: Assembles the three knowledge tiers (provider, shipped, consumer)
# ABOUTME: into one markdown block for the system prompt, with size warnings.
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path


@dataclass
class KnowledgeBlock:
    text: str
    size_kb: float
    warnings: list[str] = field(default_factory=list)


def _section(stem: str, body: str) -> str:
    body = body.strip()
    if body.startswith("#"):
        return body
    return f"## {stem}\n\n{body}"


def _shipped_sections() -> list[str]:
    pkg = resources.files("tedsbot.shipped_knowledge")
    files = sorted(p for p in pkg.iterdir() if p.name.endswith(".md"))
    return [_section(Path(p.name).stem, p.read_text()) for p in files]


def _consumer_sections(consumer_dir: Path | None, warnings: list[str]) -> list[str]:
    if consumer_dir is None:
        return []
    if not consumer_dir.is_dir():
        warnings.append(f"knowledge_dir {consumer_dir} does not exist; continuing without it")
        return []
    sections: list[str] = []
    for p in sorted(consumer_dir.glob("*.md")):
        try:
            body = p.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(f"knowledge file {p} skipped: {exc}")
            continue
        sections.append(_section(p.stem, body))
    return sections


def assemble_knowledge(
    provider_sections: Sequence[str],
    consumer_dir: Path | None,
    warn_kb: int,
    extra_sections: Sequence[str] = (),
) -> KnowledgeBlock:
    warnings: list[str] = []
    parts = [s.strip() for s in provider_sections]
    parts += _shipped_sections()
    parts += _consumer_sections(consumer_dir, warnings)
    parts += [s.strip() for s in extra_sections]
    text = "\n\n".join(p for p in parts if p)
    size_kb = len(text.encode()) / 1024
    if size_kb > warn_kb:
        warnings.append(f"knowledge block is {size_kb:.0f} KB, exceeds {warn_kb} KB")
    return KnowledgeBlock(text=text, size_kb=size_kb, warnings=warnings)
