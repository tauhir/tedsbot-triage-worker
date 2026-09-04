# ABOUTME: Exception types raised by tedsbot: config problems, gate refusals,
# ABOUTME: and provider (HTTP) failures. Commands map these to exit codes.


class ConfigError(Exception):
    """Config file is missing, malformed, or references something that does not exist."""


class GateError(Exception):
    """A precondition for a run was not met; the agent was not started."""


class ProviderError(Exception):
    """A provider's deterministic operation failed (HTTP error, bad response)."""
