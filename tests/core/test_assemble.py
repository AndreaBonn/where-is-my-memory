from dataclasses import replace

import pytest

from wimm.core.assemble import assemble_snapshot
from wimm.model.enums import ActionKind, ActivityState, Category, Risk
from wimm.model.snapshot import ActionOffer, ProtectedSummaryItem
from wimm.serialize import snapshot_from_json, snapshot_to_json

from .assemble_helpers import (
    SESSION_KEY,
    SYSTEM_KEY,
    build_input,
    container,
    draft,
    pair,
    whitebox_input,
)

SAFE_STOP = ActionOffer(kind=ActionKind.GROUP_STOP, risk=Risk.SAFE)


def test_assemble_whitebox_project_is_one_idle_group_with_safe_group_stop() -> None:
    inputs = whitebox_input()

    snapshot = assemble_snapshot(inputs=inputs)

    (group,) = snapshot.groups
    assert group.id == inputs.drafts[0].id
    assert group.category is Category.PROJECT
    assert group.activity.state is ActivityState.IDLE
    assert group.ports == (8000, 8080)
    assert group.primary_action == SAFE_STOP
    assert group.memory.used == 680 + 300 + 180
    assert group.memory.reclaimable == 680 + 300 + 165
    assert group.explanation == inputs.drafts[0].explanation
    assert [type(member).__name__ for member in group.members] == [
        "ProcessMember",
        "ContainerMember",
        "ContainerMember",
    ]
    uvicorn = group.members[0]
    assert uvicorn.actions == (ActionOffer(kind=ActionKind.PROCESS_TERMINATE, risk=Risk.SAFE),)
    assert snapshot.reclaimable_now.ram == group.memory.reclaimable
    assert snapshot.protected_summary == ()


def test_assemble_group_carries_the_draft_compose_project() -> None:
    fused = draft("g1", name="cartella", category=Category.PROJECT, compose_project="whitebox")
    plain = draft("g2", name="other", category=Category.PROJECT)

    snapshot = assemble_snapshot(inputs=build_input([fused, plain]))

    assert {g.name: g.compose_project for g in snapshot.groups} == {
        "cartella": "whitebox",
        "other": None,
    }


def test_assemble_whitebox_splits_project_memory_over_member_categories() -> None:
    breakdown = assemble_snapshot(inputs=whitebox_input()).memory.breakdown

    assert dict(breakdown.categories) == {Category.CONTAINER: 980, Category.DEV_SERVER: 180}


def test_assemble_whitebox_round_trips_through_json() -> None:
    session = pair(5, Category.SESSION, name="gnome-shell", pss=400)
    inputs = whitebox_input()
    protected = draft("g_s", name="Sessione GNOME", category=Category.SESSION, pids=[5])
    inputs = replace(
        inputs,
        drafts=(*inputs.drafts, replace(protected, key=SESSION_KEY)),
        entities=replace(inputs.entities, processes={**inputs.entities.processes, 5: session}),
    )

    snapshot = assemble_snapshot(inputs=inputs)

    assert snapshot.protected_summary
    assert snapshot_from_json(text=snapshot_to_json(snapshot=snapshot)) == snapshot


def test_assemble_session_process_goes_to_protected_summary_not_groups() -> None:
    session = pair(5, Category.SESSION, name="gnome-shell", pss=400, uss=300, swap=0)
    inputs = build_input(
        [draft("g_s", name="Sessione GNOME", category=Category.SESSION, pids=[5], key=SESSION_KEY)],
        pairs=[session],
    )

    snapshot = assemble_snapshot(inputs=inputs)

    assert snapshot.groups == ()
    assert snapshot.protected_summary == (
        ProtectedSummaryItem(label="Sessione GNOME", memory=400, reason="componente del desktop"),
    )
    assert dict(snapshot.memory.breakdown.categories) == {Category.SESSION: 400}
    assert snapshot.reclaimable_now.ram == 0


def test_assemble_protected_summary_is_sorted_by_memory_then_label() -> None:
    drafts = [
        draft("g_a", name="Audio", category=Category.SESSION, pids=[1], key="session-audio"),
        draft("g_b", name="Sessione GNOME", category=Category.SESSION, pids=[2], key=SESSION_KEY),
        draft("g_c", name="Servizi di sistema", category=Category.SYSTEM, pids=[3], key=SYSTEM_KEY),
    ]
    pairs = [
        pair(1, Category.SESSION, pss=50),
        pair(2, Category.SESSION, pss=900),
        pair(3, Category.SYSTEM, pss=50),
    ]

    snapshot = assemble_snapshot(inputs=build_input(drafts, pairs=pairs))

    assert [(item.label, item.reason) for item in snapshot.protected_summary] == [
        ("Sessione GNOME", "componente del desktop"),
        ("Audio", "audio e media del desktop"),
        ("Servizi di sistema", "servizio di sistema"),
    ]


def test_assemble_groups_are_ranked_by_reclaimable_then_name_then_id() -> None:
    pairs = [
        pair(1, Category.DEV_SERVER, uss=10, swap=0),
        pair(2, Category.DEV_SERVER, uss=90, swap=0),
        pair(3, Category.DEV_SERVER, uss=10, swap=0),
        pair(4, Category.DEV_SERVER, uss=10, swap=0),
    ]
    drafts = [
        draft("g_2", name="same", category=Category.DEV_SERVER, pids=[3]),
        draft("g_1", name="same", category=Category.DEV_SERVER, pids=[4]),
        draft("g_9", name="big", category=Category.DEV_SERVER, pids=[2]),
        draft("g_0", name="aaa", category=Category.DEV_SERVER, pids=[1]),
    ]

    snapshot = assemble_snapshot(inputs=build_input(drafts, pairs=pairs))

    assert [group.id for group in snapshot.groups] == ["g_9", "g_0", "g_1", "g_2"]


def test_assemble_breakdown_accounts_for_every_group_and_protected_byte() -> None:
    inputs = whitebox_input()
    protected = replace(
        draft("g_s", name="Sessione GNOME", category=Category.SESSION, pids=[5]), key=SESSION_KEY
    )
    inputs = replace(
        inputs,
        drafts=(*inputs.drafts, protected),
        entities=replace(
            inputs.entities,
            processes={**inputs.entities.processes, 5: pair(5, Category.SESSION, pss=400)},
        ),
    )

    snapshot = assemble_snapshot(inputs=inputs)

    attributed = sum(size for _, size in snapshot.memory.breakdown.categories)
    expected = sum(group.memory.used for group in snapshot.groups) + sum(
        item.memory for item in snapshot.protected_summary
    )
    assert attributed == expected == 980 + 180 + 400


def test_assemble_input_rejects_a_process_listed_in_two_drafts() -> None:
    drafts = [draft("g_1", pids=[1]), draft("g_2", pids=[1])]

    with pytest.raises(ValueError, match="more than one group"):
        build_input(drafts, pairs=[pair(1)])


def test_assemble_input_rejects_a_container_listed_in_two_drafts() -> None:
    drafts = [draft("g_1", containers=["a"]), draft("g_2", containers=["a"])]

    with pytest.raises(ValueError, match="more than one group"):
        build_input(drafts, containers=[container("a")])
