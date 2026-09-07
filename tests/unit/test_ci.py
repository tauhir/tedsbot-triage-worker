# ABOUTME: Tests the CI watch: polling gh pr checks with injected gh, sleep and clock,
# ABOUTME: and the verdicts passed, failed, none, and timeout.
import json
import subprocess

from tedsbot.ci import watch_ci


def _gh_sequence(*payloads):
    payloads = list(payloads)

    def run(cmd, **kwargs):
        body = payloads.pop(0) if len(payloads) > 1 else payloads[0]
        if isinstance(body, int):
            return subprocess.CompletedProcess(cmd, body, stdout="", stderr="boom")
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(body), stderr="")

    return run


def _clock(step: float = 10.0):
    now = [0.0]

    def clock():
        now[0] += step
        return now[0]

    return clock


def test_all_pass_after_pending() -> None:
    run = _gh_sequence([{"name": "tests", "bucket": "pending"}], [{"name": "tests", "bucket": "pass"}, {"name": "lint", "bucket": "skipping"}])
    v = watch_ci("https://github.com/x/y/pull/1", wait_minutes=5, poll_seconds=1, run=run, sleep=lambda s: None, clock=_clock())
    assert v.state == "passed" and v.failing == [] and v.pending == []


def test_failure_waits_for_the_rest_then_names_all_failures() -> None:
    run = _gh_sequence(
        [{"name": "tests", "bucket": "fail"}, {"name": "lint", "bucket": "pending"}],
        [{"name": "tests", "bucket": "fail"}, {"name": "lint", "bucket": "cancel"}],
    )
    v = watch_ci("u", wait_minutes=5, poll_seconds=1, run=run, sleep=lambda s: None, clock=_clock())
    assert v.state == "failed" and v.failing == ["tests", "lint"]


def test_no_checks_is_none() -> None:
    v = watch_ci("u", wait_minutes=5, poll_seconds=1, run=_gh_sequence([]), sleep=lambda s: None, clock=_clock())
    assert v.state == "none"


def test_timeout_with_pending_checks() -> None:
    run = _gh_sequence([{"name": "tests", "bucket": "pending"}])
    v = watch_ci("u", wait_minutes=1, poll_seconds=1, run=run, sleep=lambda s: None, clock=_clock(step=20.0))
    assert v.state == "timeout" and v.pending == ["tests"]


def test_gh_errors_are_retried_until_deadline() -> None:
    v = watch_ci("u", wait_minutes=1, poll_seconds=1, run=_gh_sequence(1), sleep=lambda s: None, clock=_clock(step=20.0))
    assert v.state == "timeout"
