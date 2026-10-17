import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import TypedDict, Unpack

import pytest

from wimm.model.enums import ActionKind, ActivityState, Category, GroupId, Pressure, Risk
from wimm.model.memory import MemoryBreakdown, MemoryUse
from wimm.model.snapshot import (
    ActionOffer,
    ActivityAssessment,
    Group,
    Member,
    ProcessMember,
    ProtectedSummaryItem,
    Snapshot,
)
from wimm.serialize import snapshot_from_json
from wimm.ui.viewmodel import (
    build_rows,
    build_summary,
    build_system_rows,
    empty_state,
)
from wimm.ui.views import EmptyKind, RowFilters

FIXTURE = Path(__file__).parents[1] / "fixtures" / "snapshot_whitebox.json"
IDLE_SINCE = datetime.fromisoformat("2026-10-16T05:12:00+02:00")
PERF_GROUPS = 320
PERF_BUDGET_S = 0.1


@pytest.fixture
def snapshot() -> Snapshot:
    return snapshot_from_json(text=FIXTURE.read_text())


@pytest.fixture
def now(snapshot: Snapshot) -> datetime:
    return snapshot.taken_at


class GroupOverrides(TypedDict, total=False):
    id: GroupId
    ports: tuple[int, ...]
    explanation: str
    members: tuple[Member, ...]
    snoozed_until: datetime | None
    ignored: bool


def make_group(
    name: str = "g",
    *,
    category: Category = Category.DEV_SERVER,
    state: ActivityState = ActivityState.IDLE,
    reclaimable: int = 100,
    used: int = 200,
    risk: Risk | None = Risk.SAFE,
    reason: str = "reason",
    since: datetime | None = IDLE_SINCE,
    **overrides: Unpack[GroupOverrides],
) -> Group:
    primary = None if risk is None else ActionOffer(kind=ActionKind.GROUP_STOP, risk=risk)
    base = Group(
        id=GroupId(f"id-{name}"),
        name=name,
        category=category,
        activity=ActivityAssessment(state=state, since=since, reason=reason),
        memory=MemoryUse(used=used, reclaimable=reclaimable),
        ports=(),
        primary_action=primary,
        ignored=False,
        snoozed_until=None,
        explanation="explanation",
        compose_project=None,
        members=(),
    )
    return replace(base, **overrides)


def with_groups(snapshot: Snapshot, *groups: Group) -> Snapshot:
    return replace(snapshot, groups=groups)


def titles(
    snapshot: Snapshot,
    now: datetime,
    *,
    only_idle: bool = False,
    categories: frozenset[Category] = frozenset(),
    risks: frozenset[Risk] = frozenset(),
    query: str = "",
) -> list[str]:
    filters = RowFilters(only_idle=only_idle, categories=categories, risks=risks, query=query)
    return [row.title for row in build_rows(snapshot=snapshot, filters=filters, now=now)]


def test_fixture_group_row_reads_like_the_spec_mockup(snapshot: Snapshot, now: datetime) -> None:
    (row,) = build_rows(snapshot=snapshot, filters=RowFilters(), now=now)

    assert row.title == "whitebox"
    assert row.subtitle == "Progetto · inattivo da 5 h"
    assert row.detail == (
        "nessuna connessione in ingresso e CPU media 0,1% negli ultimi 30 minuti · porte 8000, 8080"
    )
    assert (row.reclaimable, row.memory) == ("1,1 GB", "1,1 GB")
    assert (row.risk_text, row.risk_style) == ("Sicuro", "success")
    assert row.primary_action is not None
    assert (row.primary_action.label, row.primary_action.kind) == ("Ferma", ActionKind.GROUP_STOP)
    assert row.explanation.startswith("progetto compose 'whitebox'")
    assert (row.ignored, row.snoozed_until, row.snoozed_text) == (False, None, None)


def test_fixture_members_show_command_cwd_ports_image_and_mounts(
    snapshot: Snapshot, now: datetime
) -> None:
    container, process = build_rows(snapshot=snapshot, filters=RowFilters(), now=now)[0].members

    assert (container.key, container.kind, container.name) == (
        "2c9184903a37",
        "container",
        "whitebox-keycloak",
    )
    assert container.image == "quay.io/keycloak/keycloak:26.0.8"
    assert container.state == "running"
    assert container.mounts == (
        "bind: /home/bonn/projects/ai-whitebox-core/vault -> /opt/keycloak/vault",
    )
    assert (container.command, container.cwd, container.started) == (None, None, None)
    assert container.memory == "682 MB"
    assert [a.label for a in container.actions] == ["Ferma"]

    assert (process.key, process.kind, process.name) == ("941149", "process", "uvicorn")
    assert process.command == "uvicorn app:main --port 8000"
    assert process.cwd == "/home/bonn/projects/ai-whitebox-core"
    assert process.ports == "8000"
    assert process.started == "16/10 06:46"
    assert process.memory == "180 MB"
    assert process.activity == "inattivo da 5 h"
    assert [a.label for a in process.actions] == ["Termina"]


def test_member_command_quotes_arguments_with_spaces(snapshot: Snapshot, now: datetime) -> None:
    process = snapshot.groups[0].members[1]
    assert isinstance(process, ProcessMember)
    spaced = replace(process, cmdline=("node", "my app.js"), cwd=None)
    group = replace(snapshot.groups[0], members=(spaced,))

    (member,) = build_rows(snapshot=with_groups(snapshot, group), filters=RowFilters(), now=now)[
        0
    ].members

    assert member.command == "node 'my app.js'"
    assert member.cwd is None


def test_member_with_empty_cmdline_has_no_command(snapshot: Snapshot, now: datetime) -> None:
    process = snapshot.groups[0].members[1]
    assert isinstance(process, ProcessMember)
    group = replace(snapshot.groups[0], members=(replace(process, cmdline=()),))

    (member,) = build_rows(snapshot=with_groups(snapshot, group), filters=RowFilters(), now=now)[
        0
    ].members

    assert member.command is None


def test_group_without_ports_does_not_mention_ports(snapshot: Snapshot, now: datetime) -> None:
    quiet = make_group("quiet", reason="CPU sotto soglia")
    noisy = make_group("noisy", reason="CPU sotto soglia", ports=(3000,))
    multi = make_group("multi", reason="CPU sotto soglia", ports=(3000, 8000))

    rows = {
        r.title: r
        for r in build_rows(
            snapshot=with_groups(snapshot, quiet, noisy, multi), filters=RowFilters(), now=now
        )
    }

    assert rows["quiet"].detail == "CPU sotto soglia"
    assert rows["noisy"].detail == "CPU sotto soglia · porta 3000"
    assert rows["multi"].detail == "CPU sotto soglia · porte 3000, 8000"


def test_long_name_arrives_untruncated(snapshot: Snapshot, now: datetime) -> None:
    name = "n" * 200
    (row,) = build_rows(
        snapshot=with_groups(snapshot, make_group(name)), filters=RowFilters(), now=now
    )
    assert row.title == name


def test_rows_sorted_by_reclaimable_descending(snapshot: Snapshot, now: datetime) -> None:
    groups = (
        make_group("small", reclaimable=10),
        make_group("big", reclaimable=900),
        make_group("mid", reclaimable=500),
    )
    assert titles(with_groups(snapshot, *groups), now) == ["big", "mid", "small"]


def test_ties_break_on_used_then_name_then_id(snapshot: Snapshot, now: datetime) -> None:
    groups = (
        make_group("beta", reclaimable=5, used=10),
        make_group("Alpha", reclaimable=5, used=10),
        make_group("heavy", reclaimable=5, used=99),
        make_group("beta", reclaimable=5, used=10, id=GroupId("id-aaa")),
    )
    rows = build_rows(snapshot=with_groups(snapshot, *groups), filters=RowFilters(), now=now)
    assert [r.id for r in rows] == ["id-heavy", "id-Alpha", "id-aaa", "id-beta"]


def test_filter_only_idle_keeps_idle_groups(snapshot: Snapshot, now: datetime) -> None:
    groups = (
        make_group("idle", state=ActivityState.IDLE),
        make_group("busy", state=ActivityState.ACTIVE),
        make_group("unk", state=ActivityState.UNKNOWN, since=None),
    )
    shot = with_groups(snapshot, *groups)
    assert titles(shot, now, only_idle=True) == ["idle"]
    assert sorted(titles(shot, now)) == ["busy", "idle", "unk"]


def test_filter_by_category_set(snapshot: Snapshot, now: datetime) -> None:
    groups = (
        make_group("web", category=Category.BROWSER),
        make_group("srv", category=Category.DEV_SERVER),
        make_group("ai", category=Category.AI_CLI),
    )
    shot = with_groups(snapshot, *groups)
    chosen = frozenset({Category.BROWSER, Category.AI_CLI})
    assert sorted(titles(shot, now, categories=chosen)) == ["ai", "web"]


def test_filter_by_risk_set_excludes_rows_without_a_risk(snapshot: Snapshot, now: datetime) -> None:
    groups = (
        make_group("safe", risk=Risk.SAFE),
        make_group("care", risk=Risk.CAUTION),
        make_group("none", risk=None),
    )
    shot = with_groups(snapshot, *groups)
    assert titles(shot, now, risks=frozenset({Risk.CAUTION})) == ["care"]
    assert sorted(titles(shot, now, risks=frozenset({Risk.SAFE, Risk.CAUTION}))) == [
        "care",
        "safe",
    ]
    assert "none" in titles(shot, now)


def test_search_is_case_insensitive_on_name_and_explanation(
    snapshot: Snapshot, now: datetime
) -> None:
    groups = (
        make_group("Frontend"),
        make_group("other", explanation="lanciato dal TERMINALE"),
        make_group("noise"),
    )
    shot = with_groups(snapshot, *groups)
    assert titles(shot, now, query="frontEND") == ["Frontend"]
    assert titles(shot, now, query="terminale") == ["other"]
    assert titles(shot, now, query="  frontend  ") == ["Frontend"]


def test_search_matches_member_command_and_ports(snapshot: Snapshot, now: datetime) -> None:
    shot = with_groups(snapshot, make_group("noise"), *snapshot.groups)
    assert titles(shot, now, query="UVICORN app:main") == ["whitebox"]
    assert titles(shot, now, query="8000") == ["whitebox"]
    assert titles(shot, now, query="8080") == ["whitebox"]
    assert titles(shot, now, query="9999") == []


def test_search_matches_group_ports(snapshot: Snapshot, now: datetime) -> None:
    shot = with_groups(snapshot, make_group("srv", ports=(4321,)), make_group("noise"))
    assert titles(shot, now, query="4321") == ["srv"]


def test_search_is_accent_insensitive(snapshot: Snapshot, now: datetime) -> None:
    shot = with_groups(snapshot, make_group("noise"), make_group("x", explanation="attività"))
    assert titles(shot, now, query="attivita") == ["x"]
    assert titles(shot, now, query="ATTIVITÀ") == ["x"]
    assert titles(shot, now, query="attivite") == []


def test_search_matches_container_name_image_and_process_name(
    snapshot: Snapshot, now: datetime
) -> None:
    shot = with_groups(snapshot, make_group("noise"), *snapshot.groups)
    assert titles(shot, now, query="keycloak:26") == ["whitebox"]
    assert titles(shot, now, query="whitebox-keycloak") == ["whitebox"]
    assert titles(shot, now, query="quay.io") == ["whitebox"]
    renamed = replace(snapshot.groups[0], explanation="x", name="proj", ports=())
    process = renamed.members[1]
    assert isinstance(process, ProcessMember)
    only_name = replace(renamed, members=(replace(process, name="gunicorn", cmdline=("run",)),))
    assert titles(with_groups(snapshot, only_name), now, query="gunicorn") == ["proj"]


def test_search_ignores_container_members_without_a_command(
    snapshot: Snapshot, now: datetime
) -> None:
    container_only = replace(
        snapshot.groups[0],
        members=snapshot.groups[0].members[:1],
        ports=(),
        explanation="solo un container",
    )
    shot = with_groups(snapshot, container_only)
    assert titles(shot, now, query="uvicorn") == []
    assert titles(shot, now, query="whitebox") == ["whitebox"]


def test_combined_filters_all_apply(snapshot: Snapshot, now: datetime) -> None:
    groups = (
        make_group("api-idle", category=Category.DEV_SERVER, state=ActivityState.IDLE),
        make_group("api-busy", category=Category.DEV_SERVER, state=ActivityState.ACTIVE),
        make_group("api-ai", category=Category.AI_CLI, state=ActivityState.IDLE),
        make_group("web-idle", category=Category.DEV_SERVER, state=ActivityState.IDLE),
        make_group("api-risky", category=Category.DEV_SERVER, risk=Risk.DANGER),
    )
    shot = with_groups(snapshot, *groups)
    result = titles(
        shot,
        now,
        only_idle=True,
        categories=frozenset({Category.DEV_SERVER}),
        risks=frozenset({Risk.SAFE}),
        query="API",
    )
    assert result == ["api-idle"]


def test_protected_groups_never_appear_in_the_overview(snapshot: Snapshot, now: datetime) -> None:
    protected = make_group("gnome", category=Category.SESSION, risk=None)
    system = make_group("kernel", category=Category.SYSTEM, risk=None)
    own = make_group("wimm", category=Category.SELF, risk=None)
    normal = make_group("srv")
    shot = with_groups(snapshot, protected, system, own, normal)

    assert titles(shot, now) == ["srv"]
    assert titles(shot, now, query="gnome") == []
    assert empty_state(snapshot=shot, filters=RowFilters(query="gnome")) is not None


@pytest.mark.parametrize(
    ("risk", "text", "style", "label"),
    [
        (Risk.SAFE, "Sicuro", "success", "Ferma"),
        (Risk.CAUTION, "Attenzione", "warning", "Ferma…"),
        (Risk.DANGER, "Pericolo", "error", "Ferma…"),
    ],
)
def test_badge_and_button_for_each_risk(
    snapshot: Snapshot, now: datetime, risk: Risk, text: str, style: str, label: str
) -> None:
    (row,) = build_rows(
        snapshot=with_groups(snapshot, make_group(risk=risk)), filters=RowFilters(), now=now
    )

    assert (row.risk, row.risk_text, row.risk_style) == (risk, text, style)
    assert row.primary_action is not None
    assert (row.primary_action.label, row.primary_action.risk) == (label, risk)


def test_actionable_group_without_primary_uses_riskiest_member_action(
    snapshot: Snapshot, now: datetime
) -> None:
    process = snapshot.groups[0].members[1]
    assert isinstance(process, ProcessMember)
    risky = replace(process, actions=(ActionOffer(kind=ActionKind.PROCESS_KILL, risk=Risk.DANGER),))
    with_actions = replace(snapshot.groups[0], primary_action=None, members=(risky,))
    no_actions = make_group("idle-none", risk=None)

    rows = {
        r.title: r
        for r in build_rows(
            snapshot=with_groups(snapshot, with_actions, no_actions), filters=RowFilters(), now=now
        )
    }

    assert (rows["whitebox"].risk_text, rows["whitebox"].primary_action) == ("Pericolo", None)
    assert (rows["idle-none"].risk_text, rows["idle-none"].risk_style) == (
        "Nessuna azione",
        "dim-label",
    )


def test_subtitle_for_each_activity_state(snapshot: Snapshot, now: datetime) -> None:
    groups = (
        make_group("a", category=Category.DEV_SERVER, state=ActivityState.ACTIVE),
        make_group(
            "b",
            category=Category.BROWSER,
            state=ActivityState.UNKNOWN,
            since=None,
            reason="attività non misurabile per i browser",
        ),
        make_group(
            "c",
            category=Category.AI_CLI,
            state=ActivityState.UNKNOWN,
            since=None,
            reason="in osservazione da 4 minuti",
        ),
    )
    rows = {
        r.title: r.subtitle
        for r in build_rows(snapshot=with_groups(snapshot, *groups), filters=RowFilters(), now=now)
    }
    assert rows == {
        "a": "Dev server · in uso",
        "b": "Browser · attività non misurabile",
        "c": "CLI AI · in osservazione",
    }


def test_snooze_text_only_while_in_the_future(snapshot: Snapshot, now: datetime) -> None:
    future = now + timedelta(hours=1)
    groups = (
        make_group("future", snoozed_until=future),
        make_group("tomorrow", snoozed_until=datetime(2026, 10, 17, 14, 30, tzinfo=now.tzinfo)),
        make_group("past", snoozed_until=now - timedelta(minutes=1)),
        make_group("ignored", ignored=True),
    )
    rows = {
        r.title: r
        for r in build_rows(snapshot=with_groups(snapshot, *groups), filters=RowFilters(), now=now)
    }

    assert rows["future"].snoozed_until == future
    assert rows["future"].snoozed_text == "silenziato fino alle 11:30"
    assert rows["tomorrow"].snoozed_text == "silenziato fino al 17/10 alle 14:30"
    assert (rows["past"].snoozed_until, rows["past"].snoozed_text) == (None, None)
    assert rows["ignored"].ignored is True
    assert rows["future"].ignored is False


def test_summary_formats_ram_swap_disk_and_reclaimable(snapshot: Snapshot) -> None:
    summary = build_summary(snapshot=snapshot)

    assert (summary.ram_used, summary.ram_total, summary.ram_available) == (
        "32,9 GB",
        "41,7 GB",
        "8,8 GB",
    )
    assert (summary.swap_used, summary.swap_total) == ("120 MB", "4,3 GB")
    assert (summary.disk_mount, summary.disk_used, summary.disk_total, summary.disk_free) == (
        "/",
        "329,6 GB",
        "375,8 GB",
        "27,9 GB",
    )
    assert (summary.reclaimable_ram, summary.reclaimable_disk) == ("4,2 GB", "7,4 GB")
    assert (summary.pressure, summary.pressure_text) == (Pressure.WARNING, "Alta")
    assert summary.ram_fraction == pytest.approx(32.9 / 41.742)
    assert summary.disk_fraction == pytest.approx(329638211584 / 375809638400)
    assert "si libera da sola" in summary.kernel_cache_note


def test_summary_segments_are_ranked_and_carry_a_text_legend(snapshot: Snapshot) -> None:
    segments = build_summary(snapshot=snapshot).segments

    assert [s.key for s in segments] == [
        "BROWSER",
        "DESKTOP_APP",
        "AI_CLI",
        "DEV_SERVER",
        "CONTAINER",
        "kernel_cache",
        "unattributed",
        "free",
    ]
    assert segments[0].legend == "Browser: 9,8 GB (23%)"
    assert segments[-2].legend == "Non attribuita: 1,9 GB (4%)"
    assert segments[-3].label == "Cache del kernel"
    assert segments[-1].legend == "Libera: 14,9 GB (36%)"
    assert segments[0].fraction == pytest.approx(9.8 / 41.742)


def test_summary_segments_cover_total_memory_and_percents_sum_to_100(
    snapshot: Snapshot,
) -> None:
    segments = build_summary(snapshot=snapshot).segments

    assert sum(s.size for s in segments) == snapshot.memory.total
    assert sum(s.percent for s in segments) == 100
    assert sum(s.fraction for s in segments) == pytest.approx(1.0)


def test_percents_sum_to_100_when_plain_rounding_would_not(snapshot: Snapshot) -> None:
    thirds = MemoryBreakdown(
        categories=((Category.BROWSER, 1), (Category.CONTAINER, 1)), kernel_cache=0, unattributed=1
    )
    memory = replace(snapshot.memory, total=3, used=3, available=0, breakdown=thirds)

    segments = build_summary(snapshot=replace(snapshot, memory=memory)).segments

    assert [s.percent for s in segments if s.size] == [34, 33, 33]
    assert sum(s.percent for s in segments) == 100


def test_summary_always_lists_unattributed_but_skips_empty_categories(snapshot: Snapshot) -> None:
    empty = MemoryBreakdown(
        categories=((Category.BROWSER, 0), (Category.CONTAINER, 5)), kernel_cache=0, unattributed=0
    )
    shot = replace(snapshot, memory=replace(snapshot.memory, breakdown=empty))

    segments = build_summary(snapshot=shot).segments

    assert [s.key for s in segments] == ["CONTAINER", "unattributed", "free"]
    assert segments[1].legend == "Non attribuita: 0 B (0%)"


def test_summary_without_free_memory_has_no_free_segment(snapshot: Snapshot) -> None:
    full = MemoryBreakdown(categories=((Category.BROWSER, 10),), kernel_cache=0, unattributed=0)
    memory = replace(snapshot.memory, total=10, used=10, available=0, breakdown=full)

    segments = build_summary(snapshot=replace(snapshot, memory=memory)).segments

    assert [s.key for s in segments] == ["BROWSER", "unattributed"]
    assert segments[0].percent == 100


def test_summary_with_zero_totals_has_zero_fractions(snapshot: Snapshot) -> None:
    memory = replace(
        snapshot.memory,
        total=0,
        used=0,
        available=0,
        breakdown=MemoryBreakdown(categories=(), kernel_cache=0, unattributed=0),
    )
    shot = replace(snapshot, memory=memory, disk=replace(snapshot.disk, total=0, used=0, free=0))

    summary = build_summary(snapshot=shot)

    assert (summary.ram_fraction, summary.disk_fraction) == (0.0, 0.0)


def test_system_rows_are_read_only_and_largest_first(snapshot: Snapshot) -> None:
    extra = (
        ProtectedSummaryItem(label="Audio", memory=300_000_000, reason="servizio di sistema"),
        ProtectedSummaryItem(label="Altri utenti", memory=300_000_000, reason="processi di altri"),
    )
    shot = replace(snapshot, protected_summary=snapshot.protected_summary + extra)

    rows = build_system_rows(snapshot=shot)

    assert [(r.label, r.memory, r.reason) for r in rows] == [
        ("Sessione GNOME", "1,4 GB", "componente del desktop"),
        ("Altri utenti", "300 MB", "processi di altri"),
        ("Audio", "300 MB", "servizio di sistema"),
    ]
    assert not hasattr(rows[0], "primary_action")


def test_empty_state_for_idle_filter_uses_spec_text(snapshot: Snapshot) -> None:
    shot = with_groups(snapshot, make_group(state=ActivityState.ACTIVE))

    view = empty_state(snapshot=shot, filters=RowFilters(only_idle=True))

    assert view is not None
    assert view.kind is EmptyKind.NOTHING_IDLE
    assert view.message == "Niente di inattivo. Tutto ciò che è acceso risulta in uso."


def test_empty_state_is_none_when_rows_exist_or_unfiltered(snapshot: Snapshot) -> None:
    assert empty_state(snapshot=snapshot, filters=RowFilters()) is None
    assert empty_state(snapshot=with_groups(snapshot), filters=RowFilters()) is None
    idle_shot = with_groups(snapshot, make_group(state=ActivityState.IDLE))
    assert empty_state(snapshot=idle_shot, filters=RowFilters(only_idle=True)) is None


def test_empty_state_with_narrowing_filters_reports_no_results(snapshot: Snapshot) -> None:
    for filters in (
        RowFilters(only_idle=True, query="zzz"),
        RowFilters(categories=frozenset({Category.BROWSER})),
        RowFilters(risks=frozenset({Risk.DANGER})),
    ):
        view = empty_state(snapshot=snapshot, filters=filters)
        assert view is not None
        assert view.kind is EmptyKind.NO_RESULTS


def test_whitespace_query_is_not_a_filter(snapshot: Snapshot) -> None:
    assert empty_state(snapshot=snapshot, filters=RowFilters(query="   ")) is None
    assert (
        len(build_rows(snapshot=snapshot, filters=RowFilters(query="   "), now=snapshot.taken_at))
        == 1
    )


def test_building_hundreds_of_groups_is_fast(snapshot: Snapshot, now: datetime) -> None:
    groups = tuple(
        make_group(
            f"g{i:04d}", reclaimable=i, ports=(3000 + i % 100,), members=snapshot.groups[0].members
        )
        for i in range(PERF_GROUPS)
    )
    shot = with_groups(snapshot, *groups)

    started = time.process_time()
    rows = build_rows(snapshot=shot, filters=RowFilters(only_idle=True, query="g0"), now=now)
    elapsed = time.process_time() - started

    assert len(rows) == PERF_GROUPS
    assert elapsed < PERF_BUDGET_S, f"process_time {elapsed:.4f}s exceeds {PERF_BUDGET_S}s"
