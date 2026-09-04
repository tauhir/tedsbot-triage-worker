# ABOUTME: Tests the provider registry: kind lookup, unknown kinds, and that
# ABOUTME: the shipped providers register themselves on import.
import pytest

from tedsbot import registry
from tedsbot.config import (
    ErrorsConfig,
    NotifyConfig,
    TicketFields,
    TicketsConfig,
    TicketStatuses,
)
from tedsbot.errors import ConfigError
from tedsbot.providers.base import ErrorSource, Notifier, Ticketing


def _errors(kind: str = "sentry") -> ErrorsConfig:
    return ErrorsConfig(kind=kind, org="example-org", project_id="1", token="t")


def _tickets(kind: str = "jira") -> TicketsConfig:
    return TicketsConfig(
        kind=kind, url="https://example.atlassian.net", cloud_id="c", project="APP", token="t",
        bug_issue_type_id="10009",
        fields=TicketFields(qa_notes="customfield_1", qa_instructions="customfield_2"),
        statuses=TicketStatuses(intake="To Triage", triage_target="Dev Team Review",
                                fix_approved="Approved For Fix", in_progress="In Progress",
                                code_review="Code Review"),
    )


def test_sentry_registered() -> None:
    src = registry.get_error_source(_errors())
    assert isinstance(src, ErrorSource)


def test_jira_registered() -> None:
    assert isinstance(registry.get_ticketing(_tickets()), Ticketing)


def test_slack_registered() -> None:
    assert isinstance(registry.get_notifier(NotifyConfig(kind="slack_webhook", url="https://x")), Notifier)


def test_unknown_kind_raises() -> None:
    with pytest.raises(ConfigError, match="rollbar"):
        registry.get_error_source(_errors("rollbar"))
