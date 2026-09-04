# ABOUTME: Integration test for Sentry polling against a recorded cassette.
# ABOUTME: Re-record with SENTRY_AUTH_TOKEN, SENTRY_ORG, SENTRY_PROJECT_ID set and --record-mode=once.
import os
from pathlib import Path

import pytest
import vcr

from tedsbot.config import ErrorsConfig
from tedsbot.providers.sentry import SentryErrorSource

CASSETTES = Path(__file__).parent / "cassettes"
recorder = vcr.VCR(
    cassette_library_dir=str(CASSETTES),
    filter_headers=["authorization"],
    record_mode=os.environ.get("VCR_RECORD_MODE", "none"),
)


@recorder.use_cassette("sentry_poll.yaml")
def test_poll_returns_candidates_with_pass_labels() -> None:
    if not (CASSETTES / "sentry_poll.yaml").exists():
        pytest.skip("cassette not recorded; see module docstring")
    cfg = ErrorsConfig(
        kind="sentry",
        org=os.environ.get("SENTRY_ORG", "example-org"),
        project_id=os.environ.get("SENTRY_PROJECT_ID", "123"),
        token=os.environ.get("SENTRY_AUTH_TOKEN", "recorded"),
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
    )
    out = SentryErrorSource(cfg).poll()
    assert all(c.short_id and c.pass_label for c in out)
    assert len(out) <= cfg.poll.max_issues_per_cycle
