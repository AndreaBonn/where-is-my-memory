"""The plain-language sentences of ui/plain.py in English."""

from datetime import datetime, timedelta

import pytest

from wimm.core import text
from wimm.model.enums import ActivityState
from wimm.model.snapshot import ActivityAssessment
from wimm.ui.plain import (
    friendly_container_name,
    friendly_process_name,
    plain_reason,
    titled_name,
)

pytestmark = pytest.mark.usefixtures("english")
NOW = datetime.fromisoformat("2026-10-16T10:12:00+02:00")


def _idle(*, reason: str, hours: float) -> ActivityAssessment:
    return ActivityAssessment(
        state=ActivityState.IDLE, reason=reason, since=NOW - timedelta(hours=hours)
    )


def test_an_idle_server_reads_as_nobody_connecting() -> None:
    facts = text.IdleFacts(
        window_s=600, cpu_avg_pct=0.0, net_avg_bps=None, watches_connections=True, open_port=None
    )
    reason = text.reason_idle(idle_for_s=18000, facts=facts, from_monitor_start=False)
    sentence = plain_reason(activity=_idle(reason=reason, hours=5), now=NOW)
    assert sentence == "You haven't used it for 5 hours: nobody connects to it."


def test_an_idle_program_since_the_monitor_started_says_at_least() -> None:
    facts = text.IdleFacts(
        window_s=600, cpu_avg_pct=0.0, net_avg_bps=None, watches_connections=False, open_port=None
    )
    reason = text.reason_idle(idle_for_s=7200, facts=facts, from_monitor_start=True)
    sentence = plain_reason(activity=_idle(reason=reason, hours=2), now=NOW)
    assert sentence == "You haven't used it for at least 2 hours."


def test_an_idle_tool_just_says_since_when_and_picks_the_singular() -> None:
    sentence = plain_reason(activity=_idle(reason="CPU average 0.0%", hours=1), now=NOW)
    assert sentence == "You haven't used it for 1 hour."


def test_an_active_program_reads_as_in_use_in_english() -> None:
    activity = ActivityAssessment(
        state=ActivityState.ACTIVE, since=NOW - timedelta(minutes=3), reason="x"
    )
    assert plain_reason(activity=activity, now=NOW) == "You're using it right now."


def test_observing_and_unmeasurable_programs_read_differently_in_english() -> None:
    unknown = ActivityState.UNKNOWN
    observing = ActivityAssessment(
        state=unknown, since=None, reason=text.reason_observing(elapsed_s=240)
    )
    unmeasured = ActivityAssessment(state=unknown, since=None, reason=text.reason_cpu_unavailable())
    assert plain_reason(activity=observing, now=NOW) == (
        "We're watching it: we'll soon know whether you use it."
    )
    assert plain_reason(activity=unmeasured, now=NOW) == (
        "We don't know if you're using it: you decide whether to close it."
    )


def test_the_names_of_use_are_english_and_the_technical_name_stays() -> None:
    assert friendly_container_name(image="redis:7") == "Fast memory (cache)"
    assert friendly_container_name(image="library/postgres:16") == "Database"
    assert friendly_process_name(name="uvicorn") == "Web server"
    assert friendly_process_name(name="node") is None
    assert titled_name(name="redis-1", friendly="Fast memory (cache)") == (
        "Fast memory (cache) (redis-1)"
    )
