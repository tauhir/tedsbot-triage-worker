# ABOUTME: Provider package. Importing it registers every shipped provider
# ABOUTME: so the registry can resolve a config `kind` to a class.
from tedsbot.providers import (  # noqa: F401  (registration side effect)
    jira,
    sentry,
    slack,
)
