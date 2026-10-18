from dataclasses import replace

from tests.core.disk_helpers import MB, cache, docker_disk, image, report, stopped
from tests.core.planning_helpers import NOW, OWNER_UID, container, group, proc, snapshot
from wimm.core.planning import PlanningContext, plan_action
from wimm.core.planning_restart import StoppedContainer
from wimm.model.actions import ActionRequest, Plan
from wimm.model.disk import CacheKind, DiskReport
from wimm.model.enums import ActionKind, Category, GroupId, PlanId, TargetId
from wimm.model.snapshot import Snapshot
from wimm.ui.dialogs.facts import KEEP_TITLE, RESTART_TITLE, WHAT_TITLE, facts_for
from wimm.ui.dialogs.session import entries_for

GB = 1_000_000_000


def plan_for(*, snap: Snapshot, request: ActionRequest, disk: DiskReport | None = None) -> Plan:
    context = PlanningContext(
        owner_uid=OWNER_UID, now=lambda: NOW, new_plan_id=lambda: PlanId("p"), disk_report=disk
    )
    return plan_action(request=request, snapshot=snap, context=context)


def project() -> Snapshot:
    members = (proc(pid=1, name="uvicorn", reclaimable=GB), container(cid="kc"))
    return snapshot(group(gid="p", name="whitebox", members=members))


def test_stopping_says_what_happens_what_stays_and_how_to_restart() -> None:
    snap = project()
    plan = plan_for(
        snap=snap, request=ActionRequest(kind=ActionKind.GROUP_STOP, group_id=GroupId("p"))
    )

    facts = dict(facts_for(plan=plan, snapshot=snap))

    assert list(facts) == [WHAT_TITLE, KEEP_TITLE, RESTART_TITLE]
    assert "Il server si ferma." in facts[WHAT_TITLE]
    assert "docker" not in facts[RESTART_TITLE].lower()
    assert "Riaccendi" in facts[RESTART_TITLE]
    assert "/work/app" in facts[RESTART_TITLE]


def test_a_disk_cleanup_only_says_what_happens() -> None:
    disk = report(caches=(cache(kind=CacheKind.UV, size=3 * MB),))
    plan = plan_for(
        snap=snapshot(), request=ActionRequest(kind=ActionKind.DISK_FREE_SAFE), disk=disk
    )

    facts = facts_for(plan=plan, snapshot=snapshot())

    assert [title for title, _ in facts] == [WHAT_TITLE]


def test_entries_use_names_of_use_and_memory() -> None:
    members = (proc(pid=1, name="uvicorn", reclaimable=GB), container(cid="kc"))
    snap = snapshot(group(gid="p", name="whitebox", members=members))
    plan = plan_for(
        snap=snap, request=ActionRequest(kind=ActionKind.GROUP_STOP, group_id=GroupId("p"))
    )

    labels = [entry.label for entry in entries_for(plan=plan, snapshot=snap)]

    assert labels == ["Server web (uvicorn) · 1,0 GB", "name-kc · 300 B"]


def test_disk_entries_read_as_plain_things() -> None:
    disk = report(
        docker=docker_disk(
            images=(image(char="a", tags=(), dangling=True, size=2 * MB),),
            build_cache_size=5 * MB,
            build_cache_reclaimable=4 * MB,
        ),
        caches=(cache(kind=CacheKind.UV, size=3 * MB),),
    )
    plan = plan_for(
        snap=snapshot(), request=ActionRequest(kind=ActionKind.DISK_FREE_SAFE), disk=disk
    )

    labels = sorted(entry.label for entry in entries_for(plan=plan, snapshot=snapshot()))

    assert labels == [
        "Cache di build Docker",
        "Cache uv",
        "Immagine senza nome (" + "a" * 12 + ")",
    ]


def test_a_restart_entry_shows_no_size_since_it_frees_nothing() -> None:
    snap = project()
    request = ActionRequest(kind=ActionKind.RESTART_STOPPED, target_id=TargetId("stop"))
    context = PlanningContext(
        owner_uid=OWNER_UID,
        now=lambda: NOW,
        new_plan_id=lambda: PlanId("p"),
        stopped={"stop": (StoppedContainer(id="kc", label="name-kc"),)},
    )
    plan = plan_action(request=request, snapshot=snap, context=context)

    labels = [entry.label for entry in entries_for(plan=plan, snapshot=snap)]

    assert labels == ["name-kc"]


def test_closing_an_app_says_that_saved_files_and_data_stay() -> None:
    members = (proc(pid=1, name="firefox", category=Category.BROWSER),)
    snap = snapshot(group(gid="b", category=Category.BROWSER, members=members))
    plan = plan_for(
        snap=snap, request=ActionRequest(kind=ActionKind.APP_CLOSE, group_id=GroupId("b"))
    )

    titles = [title for title, _ in facts_for(plan=plan, snapshot=snap)]

    assert KEEP_TITLE in titles


def test_removing_stopped_containers_does_not_claim_that_data_stays() -> None:
    disk = report(docker=docker_disk(containers=(stopped(cid="1"),)))
    removal = plan_for(
        snap=snapshot(),
        request=ActionRequest(kind=ActionKind.CONTAINERS_PRUNE_STOPPED),
        disk=disk,
    )
    stopping = plan_for(
        snap=project(),
        request=ActionRequest(kind=ActionKind.GROUP_STOP, group_id=GroupId("p")),
    )

    removal_titles = [title for title, _ in facts_for(plan=removal, snapshot=snapshot())]
    stop_titles = [title for title, _ in facts_for(plan=stopping, snapshot=project())]

    assert {s.kind for s in removal.steps} == {ActionKind.CONTAINER_REMOVE}
    assert KEEP_TITLE not in removal_titles
    assert KEEP_TITLE in stop_titles


def terminal_plan(*pids: int, cwds: tuple[str, ...]) -> tuple[Plan, Snapshot]:
    members = tuple(
        replace(proc(pid=pid, name="node"), cwd=cwd) for pid, cwd in zip(pids, cwds, strict=True)
    )
    snap = snapshot(group(gid="p", name="whitebox", members=members))
    request = ActionRequest(kind=ActionKind.GROUP_STOP, group_id=GroupId("p"))
    return plan_for(snap=snap, request=request), snap


def test_the_restart_line_names_the_folder_when_every_process_shares_it() -> None:
    plan, snap = terminal_plan(1, 2, cwds=("/work/app", "/work/app"))

    restart = dict(facts_for(plan=plan, snapshot=snap))[RESTART_TITLE]

    assert "con lo stesso comando, nella cartella /work/app." in restart


def test_the_restart_line_drops_the_folder_when_the_processes_differ() -> None:
    plan, snap = terminal_plan(1, 2, cwds=("/work/app", "/work/other"))

    restart = dict(facts_for(plan=plan, snapshot=snap))[RESTART_TITLE]

    assert "con lo stesso comando di prima." in restart
    assert "/work" not in restart


def test_the_restart_line_drops_the_folder_when_one_process_has_none() -> None:
    plan, snap = terminal_plan(1, 2, cwds=("/work/app", "/work/app"))
    snap = snapshot(
        group(
            gid="p",
            name="whitebox",
            members=(proc(pid=1, name="node"), replace(proc(pid=2, name="node"), cwd=None)),
        )
    )

    restart = dict(facts_for(plan=plan, snapshot=snap))[RESTART_TITLE]

    assert "con lo stesso comando di prima." in restart
    assert "/work" not in restart
