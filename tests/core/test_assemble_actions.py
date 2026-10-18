import pytest

from wimm.core.assemble import assemble_snapshot
from wimm.model.enums import ActionKind, ActivityState, Category, Risk
from wimm.model.snapshot import ActionOffer, ProcessMember

from .assemble_helpers import UNKNOWN, build_input, container, draft, pair
from .helpers import process

CLOSE = ActionOffer(kind=ActionKind.APP_CLOSE, risk=Risk.CAUTION)
TERMINATE_CAUTION = ActionOffer(kind=ActionKind.PROCESS_TERMINATE, risk=Risk.CAUTION)
GROUP_STOP_SAFE = ActionOffer(kind=ActionKind.GROUP_STOP, risk=Risk.SAFE)


def test_assemble_firefox_group_without_foreground_data_is_unknown_and_closes_as_caution() -> None:
    firefox = [pair(pid, Category.BROWSER, name="firefox", pss=100, uss=60) for pid in (10, 11, 12)]
    drafts = [draft("g_f", name="Firefox", category=Category.BROWSER, pids=[10, 11, 12])]
    unknown = {item[0].pid: UNKNOWN for item in firefox}

    (group,) = assemble_snapshot(inputs=build_input(drafts, pairs=firefox, verdicts=unknown)).groups

    assert group.activity.state is ActivityState.UNKNOWN
    assert group.primary_action == CLOSE
    assert len(group.members) == 3
    assert all(member.actions == (TERMINATE_CAUTION,) for member in group.members)


def test_assemble_firefox_group_never_in_foreground_is_idle() -> None:
    firefox = [pair(pid, Category.BROWSER, name="firefox") for pid in (10, 11, 12)]
    drafts = [draft("g_f", name="Firefox", category=Category.BROWSER, pids=[10, 11, 12])]

    (group,) = assemble_snapshot(inputs=build_input(drafts, pairs=firefox)).groups

    assert group.activity.state is ActivityState.IDLE


def test_assemble_shell_member_has_no_actions_while_terminal_group_closes() -> None:
    server = pair(1, Category.TERMINAL, name="gnome-terminal-server", cgroup=process().cgroup)
    shell = pair(2, Category.TERMINAL, name="bash")
    drafts = [draft("g_t", name="Terminale", category=Category.TERMINAL, pids=[1, 2])]

    (group,) = assemble_snapshot(inputs=build_input(drafts, pairs=[server, shell])).groups

    assert group.members[1].actions == ()
    assert group.members[0].actions != ()
    assert group.primary_action == CLOSE


def test_assemble_terminal_group_of_orphan_shells_offers_nothing() -> None:
    shells = [pair(pid, Category.TERMINAL, name="bash") for pid in (1, 2)]
    drafts = [draft("g_t", name="Terminale", category=Category.TERMINAL, pids=[1, 2])]

    (group,) = assemble_snapshot(inputs=build_input(drafts, pairs=shells)).groups

    assert group.primary_action is None


def test_assemble_group_without_offered_actions_has_no_primary_action() -> None:
    shell = pair(2, Category.TERMINAL, name="bash")
    drafts = [draft("g_o", name="Shell", category=Category.OTHER, pids=[2])]

    (group,) = assemble_snapshot(inputs=build_input(drafts, pairs=[shell])).groups

    assert group.primary_action is None
    assert group.members[0].actions == ()


def test_assemble_running_and_exited_container_group_takes_risk_from_the_stoppable_one() -> None:
    running = container("up", memory=500)
    exited = container("down", memory=0, state="exited")
    drafts = [draft("g_c", name="stack", category=Category.CONTAINER, containers=["up", "down"])]

    snapshot = assemble_snapshot(inputs=build_input(drafts, containers=[running, exited]))

    (group,) = snapshot.groups
    assert group.primary_action == GROUP_STOP_SAFE
    assert snapshot.reclaimable_now.ram == 500


def test_assemble_only_exited_containers_group_keeps_the_removal_risk() -> None:
    drafts = [draft("g_c", category=Category.CONTAINER, containers=["old"])]

    (group,) = assemble_snapshot(
        inputs=build_input(drafts, containers=[container("old", state="exited")])
    ).groups

    assert group.primary_action == ActionOffer(kind=ActionKind.CONTAINER_REMOVE, risk=Risk.CAUTION)


@pytest.mark.parametrize(
    ("state", "kind"),
    [
        ("running", ActionKind.CONTAINER_STOP),
        ("paused", ActionKind.CONTAINER_STOP),
        ("restarting", ActionKind.CONTAINER_STOP),
        ("exited", ActionKind.CONTAINER_REMOVE),
        ("created", ActionKind.CONTAINER_REMOVE),
    ],
)
def test_assemble_container_is_stoppable_unless_it_is_not_alive(
    state: str, kind: ActionKind
) -> None:
    drafts = [draft("g_c", category=Category.CONTAINER, containers=["c"])]

    (group,) = assemble_snapshot(
        inputs=build_input(drafts, containers=[container("c", state=state)])
    ).groups

    assert [offer.kind for offer in group.members[0].actions] == [kind]


def test_assemble_process_without_start_time_offers_no_action() -> None:
    drafts = [draft("g_1", category=Category.DEV_SERVER, pids=[1, 2])]
    pairs = [pair(1, Category.DEV_SERVER, create_time=None), pair(2, Category.DEV_SERVER)]

    (group,) = assemble_snapshot(inputs=build_input(drafts, pairs=pairs)).groups

    blind, identified = group.members
    assert isinstance(blind, ProcessMember)
    assert (blind.create_time, blind.cmdline, blind.actions) == (0.0, (), ())
    assert identified.actions != ()
    assert group.primary_action is not None
    assert group.primary_action.kind is ActionKind.PROCESS_TERMINATE


def test_assemble_foreground_server_is_caution() -> None:
    server = pair(1, Category.DEV_SERVER, tpgid=77, pgid=77)
    drafts = [draft("g_s", category=Category.DEV_SERVER, pids=[1])]

    (group,) = assemble_snapshot(inputs=build_input(drafts, pairs=[server])).groups

    assert group.primary_action == TERMINATE_CAUTION


def test_assemble_idle_dev_process_named_like_a_document_app_is_not_safe() -> None:
    editor = pair(1, Category.DEV_PROCESS, name="code")
    drafts = [draft("g_1", pids=[1])]

    (group,) = assemble_snapshot(inputs=build_input(drafts, pairs=[editor])).groups

    assert group.primary_action == TERMINATE_CAUTION


def test_assemble_process_memory_falls_back_to_rss_without_pss() -> None:
    other_user = pair(1, Category.DEV_PROCESS, pss=None, uss=None, swap=None, rss=250, uid=999)
    drafts = [draft("g_1", pids=[1])]

    (group,) = assemble_snapshot(inputs=build_input(drafts, pairs=[other_user])).groups

    assert (group.memory.used, group.memory.reclaimable) == (250, 0)


def test_assemble_process_without_verdict_is_not_evaluated() -> None:
    drafts = [draft("g_s", category=Category.DEV_SERVER, pids=[5])]

    (group,) = assemble_snapshot(
        inputs=build_input(drafts, pairs=[pair(5, Category.DEV_SERVER)], verdicts={})
    ).groups

    assert group.members[0].activity.state is ActivityState.UNKNOWN


def test_assemble_excluded_process_cannot_reach_a_group() -> None:
    drafts = [draft("g_1", pids=[1])]

    with pytest.raises(ValueError, match="excluded process 1"):
        assemble_snapshot(inputs=build_input(drafts, pairs=[pair(1, None)]))


def test_assemble_project_group_risk_is_the_maximum_of_its_members() -> None:
    server = pair(1, Category.DEV_SERVER, name="uvicorn", tpgid=77, pgid=77)
    containers = [container("db"), container("cache")]
    drafts = [
        draft("g_p", name="proj", category=Category.PROJECT, pids=[1], containers=["db", "cache"])
    ]

    (group,) = assemble_snapshot(
        inputs=build_input(drafts, pairs=[server], containers=containers)
    ).groups

    assert group.primary_action == ActionOffer(kind=ActionKind.GROUP_STOP, risk=Risk.CAUTION)
