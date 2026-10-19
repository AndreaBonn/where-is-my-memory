"""F10: a program that comes back on its own says how, not "the same command"."""

import pytest

from tests.core.planning_helpers import group, proc, snapshot
from tests.ui.test_dialog_facts import plan_for
from wimm.i18n import _
from wimm.model.actions import ActionRequest
from wimm.model.enums import ActionKind, GroupId
from wimm.model.snapshot import ProcessMember
from wimm.ui.dialogs.facts import RESTART_TITLE, facts_for

GITSTATUSD = "gitstatusd-linux-x86_64"
# Measured 2026-10-19: a stopped gitstatusd is not restarted by the zsh that owned it,
# a new terminal starts its own.
GITSTATUS_RESTART = (
    "Lo stato git del terminale: riparte da solo nei terminali che apri dopo; "
    "in quelli già aperti torna quando li riapri."
)
SAME_COMMAND = "con lo stesso comando"


def restart_text(*members: ProcessMember) -> str:
    snap = snapshot(group(gid="g", name="g", members=members))
    request = ActionRequest(kind=ActionKind.GROUP_STOP, group_id=GroupId("g"))
    return dict(facts_for(plan=plan_for(snap=snap, request=request), snapshot=snap))[
        _(RESTART_TITLE)
    ]


def test_gitstatusd_says_it_comes_back_with_new_terminals_once() -> None:
    text = restart_text(*(proc(pid=pid, name=GITSTATUSD) for pid in (1, 2, 3)))

    assert text == GITSTATUS_RESTART
    assert SAME_COMMAND not in text


def test_a_plain_program_next_to_gitstatusd_keeps_the_command_line() -> None:
    text = restart_text(proc(pid=1, name=GITSTATUSD), proc(pid=2, name="node"))

    assert text.splitlines() == [
        GITSTATUS_RESTART,
        "I programmi del terminale: con lo stesso comando, nella cartella /work/app.",
    ]


@pytest.mark.usefixtures("english")
def test_the_gitstatusd_restart_line_in_english() -> None:
    text = restart_text(proc(pid=1, name=GITSTATUSD))

    assert text == (
        "The terminal's git status: it starts again by itself in terminals you open later; "
        "in the ones already open it comes back when you reopen them."
    )
