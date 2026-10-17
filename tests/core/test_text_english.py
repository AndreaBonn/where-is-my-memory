from datetime import datetime, timedelta

import pytest

from wimm.core import text
from wimm.core.text_groups import GroupFacts, explain_group
from wimm.i18n import _
from wimm.model.enums import ActivityState, Category
from wimm.model.snapshot import ActivityAssessment
from wimm.ui.format import activity_text
from wimm.ui.plain import plain_reason

pytestmark = pytest.mark.usefixtures("english")

NOW = datetime.fromisoformat("2026-10-16T10:12:00+02:00")


def test_format_decimal_uses_a_point() -> None:
    assert text.format_decimal(value=12.34) == "12.3"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (30, "less than 1 minute"),
        (60, "1 minute"),
        (240, "4 minutes"),
        (3 * 3600, "3 h"),
        (3 * 86400, "3 days"),
    ],
)
def test_format_duration_in_english(seconds: float, expected: str) -> None:
    assert text.format_duration(seconds=seconds) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(60, "1 minute"), (2400, "40 minutes"), (3600, "1 hour"), (7200, "2 hours"), (86400, "1 day")],
)
def test_spoken_duration_picks_the_english_plural(seconds: float, expected: str) -> None:
    assert text.spoken_duration(seconds=seconds) == expected


def test_reason_observing_starts_with_the_translated_prefix() -> None:
    reason = text.reason_observing(elapsed_s=300)
    assert reason == "observing for 5 minutes"
    assert reason.startswith(_(text.OBSERVING_PREFIX))


def test_reason_unmeasurable_names_the_category_in_english() -> None:
    assert text.reason_unmeasurable(category=Category.BROWSER) == (
        "activity cannot be measured for browsers"
    )
    assert text.reason_unmeasurable(category=Category.OTHER) == "activity cannot be measured"


def test_reason_idle_server_from_monitor_start_carries_both_marks() -> None:
    facts = text.IdleFacts(
        window_s=600, cpu_avg_pct=0.04, net_avg_bps=None, watches_connections=True, open_port=None
    )
    reason = text.reason_idle(idle_for_s=7200, facts=facts, from_monitor_start=True)
    assert reason == (
        "idle for at least 2 h, that is since the monitor started; "
        "no connection coming in and average CPU 0.0% in the last 10 minutes"
    )
    assert _(text.AT_LEAST_MARK) in reason
    assert _(text.NO_CONNECTIONS_MARK) in reason


def test_reason_idle_with_forgotten_browser_port() -> None:
    facts = text.IdleFacts(
        window_s=600, cpu_avg_pct=1.25, net_avg_bps=None, watches_connections=True, open_port=5173
    )
    reason = text.reason_idle(idle_for_s=10800, facts=facts, from_monitor_start=False)
    assert reason == (
        "idle for 3 h; no connection opened recently and average CPU 1.2% in the last 10 minutes; "
        "a browser has an open connection (probably a forgotten tab on localhost:5173)"
    )


def test_reason_idle_container_reports_network_traffic() -> None:
    facts = text.IdleFacts(
        window_s=600, cpu_avg_pct=0.0, net_avg_bps=12.4, watches_connections=False, open_port=None
    )
    reason = text.reason_idle(idle_for_s=10800, facts=facts, from_monitor_start=False)
    assert reason.endswith(
        "average CPU 0.0% and average network traffic 12 B/s in the last 10 minutes"
    )


def test_reason_foreground_and_persisted_texts() -> None:
    assert text.reason_foreground_active(ago_s=120) == "in the foreground 2 minutes ago"
    assert text.reason_foreground_idle(
        idle_for_s=10800, window_s=1800, from_monitor_start=False
    ) == ("idle for 3 h; not in the foreground in the last 30 minutes")
    assert text.reason_idle_persisted(idle_for_s=10800, observed_s=300) == (
        "idle for 3 h; last activity recorded before the restart, observing for 5 minutes"
    )


@pytest.mark.parametrize(
    ("active", "measurable", "expected"),
    [
        (1, 1, "the only measurable member is active"),
        (1, 3, "1 active member out of 3 measurable"),
        (2, 3, "2 active members out of 3 measurable"),
    ],
)
def test_reason_group_active_in_english(active: int, measurable: int, expected: str) -> None:
    assert text.reason_group_active(active=active, measurable=measurable) == expected


def test_reason_group_idle_and_unknown_in_english() -> None:
    assert text.reason_group_idle(measurable=2) == "both measurable members are idle"
    assert text.reason_group_idle(measurable=4) == "all 4 measurable members are idle"
    assert text.reason_group_unknown(measurable=0) == "no measurable members"


def _idle_assessment(*, watches_connections: bool, from_monitor_start: bool) -> ActivityAssessment:
    facts = text.IdleFacts(
        window_s=600,
        cpu_avg_pct=0.0,
        net_avg_bps=None,
        watches_connections=watches_connections,
        open_port=None,
    )
    reason = text.reason_idle(idle_for_s=7200, facts=facts, from_monitor_start=from_monitor_start)
    return ActivityAssessment(
        state=ActivityState.IDLE, since=NOW - timedelta(hours=2), reason=reason
    )


def test_plain_reason_reads_the_english_connection_mark() -> None:
    server = _idle_assessment(watches_connections=True, from_monitor_start=False)
    tool = _idle_assessment(watches_connections=False, from_monitor_start=False)
    assert plain_reason(activity=server, now=NOW).endswith(": nobody connects to it.")
    assert not plain_reason(activity=tool, now=NOW).endswith(": nobody connects to it.")


def test_plain_reason_reads_the_english_at_least_mark() -> None:
    since_start = _idle_assessment(watches_connections=False, from_monitor_start=True)
    measured = _idle_assessment(watches_connections=False, from_monitor_start=False)
    assert _(text.AT_LEAST_MARK) in since_start.reason
    assert _(text.AT_LEAST_MARK) not in measured.reason
    # Same duration on both sides: the only difference is the "at least" the reader adds.
    assert plain_reason(activity=since_start, now=NOW) != plain_reason(activity=measured, now=NOW)


def test_ui_readers_tell_observing_from_other_unknown_reasons() -> None:
    observing = text.reason_observing(elapsed_s=60)
    unavailable = text.reason_cpu_unavailable()
    unknown = ActivityState.UNKNOWN
    assert activity_text(state=unknown, reason=observing, elapsed_s=None) == "observing"
    assert activity_text(state=unknown, reason=unavailable, elapsed_s=None) != "observing"
    observed = ActivityAssessment(state=unknown, since=None, reason=observing)
    unmeasured = ActivityAssessment(state=unknown, since=None, reason=unavailable)
    assert plain_reason(activity=observed, now=NOW) == (
        "We're watching it: we'll soon know whether you use it."
    )
    assert plain_reason(activity=unmeasured, now=NOW) == (
        "We don't know if you're using it: you decide whether to close it."
    )


def _facts(**changes: object) -> GroupFacts:
    values: dict[str, object] = {
        "category": Category.OTHER,
        "name": "x",
        "folder": None,
        "containers": 0,
        "processes": 1,
        "ports": (),
        "compose_project": None,
        "lead_process": None,
    }
    values.update(changes)
    return GroupFacts(**values)  # type: ignore[arg-type]


def test_explain_group_dev_server_with_ports_and_folder() -> None:
    facts = _facts(
        category=Category.DEV_SERVER,
        processes=1,
        lead_process="vite",
        ports=(3000, 3001),
        folder="/home/u/site",
    )
    assert explain_group(facts=facts) == (
        "one vite process listening on ports 3000 and 3001 in the folder site"
    )


def test_explain_group_launched_from_terminal_plural() -> None:
    facts = _facts(category=Category.DEV_PROCESS, processes=3, ports=(80,), folder="/home/u/api")
    assert explain_group(facts=facts) == (
        "3 processes started from the terminal in the folder api, listening on port 80"
    )


def test_explain_group_project_and_container_counts() -> None:
    facts = _facts(
        category=Category.PROJECT,
        compose_project="shop",
        containers=2,
        processes=2,
        folder="/srv/shop",
    )
    assert explain_group(facts=facts) == (
        "compose project 'shop' with 2 containers in /srv/shop, plus 2 processes in the same folder"
    )
    single = _facts(category=Category.CONTAINER, compose_project="shop", containers=1)
    assert explain_group(facts=single) == "compose project 'shop' with 1 container"
    bare = _facts(category=Category.CONTAINER, name="db")
    assert explain_group(facts=bare) == "container 'db' with no compose project"


def test_explain_group_apps_protected_and_other() -> None:
    app = _facts(category=Category.BROWSER, name="Firefox", processes=12)
    assert (
        explain_group(facts=app)
        == "browser Firefox with 12 processes (tabs, extensions and services)"
    )
    protected = _facts(category=Category.SYSTEM, name="System services", process_names=("b", "a"))
    assert explain_group(facts=protected) == "System services: a, b, cannot be changed from here"
    names = tuple(f"p{i:02d}" for i in range(10))
    many = _facts(category=Category.SYSTEM, name="S", process_names=names)
    assert "p00, p01, p02, p03, p04, p05, p06, p07 and 2 more" in explain_group(facts=many)
    assert explain_group(facts=_facts(processes=1)) == "one process not tied to a project or an app"
    assert explain_group(facts=_facts(processes=3)) == "3 processes not tied to a project or an app"
