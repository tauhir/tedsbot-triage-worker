# ABOUTME: Maps a config role + kind to a provider factory. Provider modules
# ABOUTME: call register() at import; commands call the get_* helpers.
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tedsbot.errors import ConfigError

_REGISTRY: dict[tuple[str, str], Callable[[Any], Any]] = {}


def register(role: str, kind: str, factory: Callable[[Any], Any]) -> None:
    _REGISTRY[(role, kind)] = factory


def _resolve(role: str, cfg: Any) -> Any:
    import tedsbot.providers  # noqa: F401  (ensure shipped providers registered)

    factory = _REGISTRY.get((role, cfg.kind))
    if factory is None:
        known = sorted(k for r, k in _REGISTRY if r == role)
        raise ConfigError(f"{role}.kind {cfg.kind!r} is not registered; known: {known}")
    return factory(cfg)


def get_error_source(cfg: Any) -> Any:
    return _resolve("errors", cfg)


def get_ticketing(cfg: Any) -> Any:
    return _resolve("tickets", cfg)


def get_log_store(cfg: Any) -> Any:
    return _resolve("logs", cfg)


def get_notifier(cfg: Any) -> Any:
    return _resolve("notify", cfg)
