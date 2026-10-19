import time
from dataclasses import replace
from datetime import datetime

import pytest

from tests.ui.viewmodel_helpers import FIXTURE, make_group, roomy_disk, titles, with_groups
from wimm.model.enums import ActivityState, Category, Pressure, Risk
from wimm.model.snapshot import (
    Snapshot,
)
from wimm.serialize import snapshot_from_json
from wimm.ui.viewmodel import (
    build_rows,
    build_summary,
    empty_state,
    filter_counts,
)
from wimm.ui.views import EmptyKind, RowFilters

PERF_GROUPS = 320


PERF_BUDGET_S = 0.1


@pytest.fixture
def snapshot() -> Snapshot:
    return snapshot_from_json(text=FIXTURE.read_text())


@pytest.fixture
def now(snapshot: Snapshot) -> datetime:
    return snapshot.taken_at


def test_empty_state_for_idle_filter_uses_spec_text(snapshot: Snapshot) -> None:
    shot = with_groups(snapshot, make_group(state=ActivityState.ACTIVE))

    view = empty_state(snapshot=shot, filters=RowFilters(only_idle=True))

    assert view is not None
    assert view.kind is EmptyKind.NOTHING_IDLE
    assert view.message == "Niente da liberare: il resto è in uso o ancora in osservazione."


def test_empty_state_without_any_program_says_all_is_well(snapshot: Snapshot) -> None:
    for filters in (RowFilters(), RowFilters(only_idle=True)):
        view = empty_state(snapshot=with_groups(snapshot), filters=filters)
        assert view is not None
        assert view.kind is EmptyKind.ALL_CLEAR
        assert view.message == "Tutto in ordine"
        assert "Ti avvisiamo" in view.description


def test_empty_state_is_none_when_rows_exist_or_unfiltered(snapshot: Snapshot) -> None:
    assert empty_state(snapshot=snapshot, filters=RowFilters()) is None
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


@pytest.mark.perf
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


def test_status_follows_the_pressure_and_offers_the_safe_amount(snapshot: Snapshot) -> None:
    ram_tight = roomy_disk(snapshot)
    warning = build_summary(snapshot=ram_tight)
    critical = build_summary(snapshot=replace(ram_tight, pressure=Pressure.CRITICAL))
    calm = build_summary(snapshot=replace(ram_tight, pressure=Pressure.OK))

    assert (warning.status_title, warning.status_level) == (
        "La memoria si sta riempiendo",
        "warning",
    )
    assert (critical.status_title, critical.status_level) == ("La memoria è quasi finita", "error")
    assert (calm.status_title, calm.status_level) == ("Il computer sta bene", "success")
    assert warning.status_text == (
        "Puoi liberare memoria chiudendo programmi che non usi. "
        "Niente si chiude senza il tuo consenso."
    )


def test_status_without_anything_safe_to_close_does_not_offer_an_amount(
    snapshot: Snapshot,
) -> None:
    nothing = replace(snapshot, reclaimable_now=replace(snapshot.reclaimable_now, ram=0))

    summary = build_summary(snapshot=roomy_disk(nothing))

    assert summary.status_text == "Non c'è niente da chiudere senza rischi."
    assert summary.safe_label == ""
    assert summary.safe_text == ""


def test_safe_button_names_the_programs_it_stops(snapshot: Snapshot) -> None:
    groups = tuple(
        make_group(name, reclaimable=size)
        for name, size in (("a", 3), ("b", 9), ("c", 5), ("d", 1))
    )
    shot = replace(
        with_groups(snapshot, *groups), reclaimable_now=replace(snapshot.reclaimable_now, ram=18)
    )
    unsafe = make_group("risky", reclaimable=99, risk=Risk.CAUTION)
    busy = make_group("busy", reclaimable=99, state=ActivityState.ACTIVE)

    summary = build_summary(snapshot=replace(shot, groups=(*groups, unsafe, busy)))

    assert summary.safe_label == "Libera 18 B di memoria"
    assert summary.safe_text == "Ferma b, c, a e un altro: non li usi e non perdi nulla."


def test_an_idle_group_with_nothing_to_do_on_it_is_not_listed_as_to_free(
    snapshot: Snapshot, now: datetime
) -> None:
    # F5: an idle terminal with "Nessuna azione" topped "Da liberare" and freed nothing.
    groups = (
        make_group("zsh", category=Category.TERMINAL, risk=None, reclaimable=286),
        make_group("gitstatusd", reclaimable=13),
    )
    shot = with_groups(snapshot, *groups)

    assert titles(shot, now, only_idle=True) == ["gitstatusd"]
    assert sorted(titles(shot, now)) == ["gitstatusd", "zsh"]
    assert filter_counts(snapshot=shot) == (1, 2)
    # In "Tutto" it sits with the rest, not under the "Da liberare" heading.
    rows = build_rows(snapshot=shot, filters=RowFilters(), now=now)
    assert [(r.title, r.is_idle) for r in rows] == [("gitstatusd", True), ("zsh", False)]


def test_filter_counts_count_actionable_idle_and_all(snapshot: Snapshot) -> None:
    groups = (
        make_group("idle"),
        make_group("busy", state=ActivityState.ACTIVE),
        make_group("gnome", category=Category.SESSION, risk=None),
    )
    assert filter_counts(snapshot=with_groups(snapshot, *groups)) == (1, 2)


def test_status_and_button_agree_when_no_group_is_safe_to_stop(snapshot: Snapshot) -> None:
    # A reclaimable total with no group behind it must not be offered by either.
    summary = build_summary(snapshot=roomy_disk(with_groups(snapshot)))

    assert summary.status_text == "Non c'è niente da chiudere senza rischi."
    assert summary.safe_label == ""


def test_status_names_the_disk_when_the_disk_drives_the_pressure(snapshot: Snapshot) -> None:
    warning = build_summary(snapshot=snapshot)
    critical = build_summary(snapshot=replace(snapshot, pressure=Pressure.CRITICAL))

    assert (warning.status_title, warning.status_level) == ("Il disco si sta riempiendo", "warning")
    assert critical.status_title == "Il disco è quasi pieno"
    assert warning.status_text == "Fai spazio dalla scheda Disco: lì trovi cosa si può cancellare."


def test_a_one_program_group_is_titled_with_its_name_of_use(
    snapshot: Snapshot, now: datetime
) -> None:
    # F7: "gitstatusd-linux-x86_64" alone says nothing to whoever must decide to stop it.
    from tests.core.planning_helpers import proc

    name = "gitstatusd-linux-x86_64"
    # One gitstatusd per open terminal: the real group has several copies of it.
    copies = tuple(proc(pid=pid, name=name, category=Category.DEV_PROCESS) for pid in (7, 70))
    alone = make_group(name, members=copies)
    project = make_group("vite", members=(proc(pid=8, name="node"), proc(pid=9, name="vite")))

    titles_now = titles(with_groups(snapshot, alone, project), now)

    assert "Stato git del terminale (gitstatusd-linux-x86_64)" in titles_now
    # A project that happens to share a known name keeps its own name.
    assert "vite" in titles_now
    lone = make_group("ollama", category=Category.PROJECT, members=(proc(pid=5, name="ollama"),))
    assert titles(with_groups(snapshot, lone), now) == ["ollama"]
