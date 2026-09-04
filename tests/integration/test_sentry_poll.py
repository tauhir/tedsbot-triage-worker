# ABOUTME: Integration test for Sentry polling against a recorded cassette.
# ABOUTME: Re-record with SENTRY_AUTH_TOKEN, SENTRY_ORG, SENTRY_PROJECT_ID set and --record-mode=once.
import os
from pathlib import Path

import pytest
import vcr

from tedsbot.config import ErrorsConfig
from tedsbot.providers.sentry import SentryErrorSource

CASSETTES = Path(__file__).parent / "cassettes"
def _drop_cookies(response: dict) -> dict:
    """Session cookies are not needed for replay and must never be committed."""
    response["headers"].pop("set-cookie", None)
    response["headers"].pop("Set-Cookie", None)
    return response


recorder = vcr.VCR(
    cassette_library_dir=str(CASSETTES),
    filter_headers=["authorization"],
    before_record_response=_drop_cookies,
    decode_compressed_response=True,
    record_mode=os.environ.get("VCR_RECORD_MODE", "none"),
)

def _replay_only() -> bool:
    """True unless VCR_RECORD_MODE asks to record; the skip guard only applies on replay."""
    return os.environ.get("VCR_RECORD_MODE", "none") == "none"


@recorder.use_cassette("sentry_poll.yaml")
def test_poll_returns_candidates_with_pass_labels() -> None:
    if _replay_only() and not (CASSETTES / "sentry_poll.yaml").exists():
        pytest.skip("cassette not recorded; see module docstring")
    cfg = ErrorsConfig(
        kind="sentry",
        org=os.environ.get("SENTRY_ORG", "example-org"),
        project_id=os.environ.get("SENTRY_PROJECT_ID", "123"),
        token=os.environ.get("SENTRY_AUTH_TOKEN", "recorded"),
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
    )
    source = SentryErrorSource(cfg)
    try:
        out = source.poll()
    finally:
        source.close()
    assert all(c.short_id and c.pass_label for c in out)
    assert len(out) <= cfg.poll.max_issues_per_cycle
