"""The confirmation and outcome dialogs in English."""

import pytest
from gi.repository import Adw

from tests.core.disk_helpers import docker_disk, report, volume
from tests.core.planning_helpers import group, proc, snapshot
from tests.service.executor_fakes import container_step, make_plan, process_step
from tests.ui.conftest import descendants
from tests.ui.test_confirm_dialog import entry_rows, labels, open_dialog, stop
from wimm.model.actions import ActionRequest
from wimm.model.enums import ActionKind, TargetId
from wimm.service.actions import ReclaimDelta
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.ui.dialogs.outcome import OutcomeDialog
from wimm.ui.dialogs.text import dialog_title, listed_note, reclaim_text
from wimm.ui.format import button_label
from wimm.ui.outcome import freed_text, step_reports, summary_text

pytestmark = [pytest.mark.ui, pytest.mark.usefixtures("english")]
GB = 1_000_000_000


def test_a_safe_stop_asks_and_explains_in_english(display: None) -> None:
    snap = snapshot(group(gid="p", name="whitebox", members=(proc(pid=1, reclaimable=GB),)))

    dialog, _, _ = open_dialog(snap=snap, request=stop("p"), subject="whitebox")

    assert dialog.get_heading() == "Stop whitebox?"
    assert dialog.get_response_label("cancel") == "Cancel"
    assert dialog.get_response_label("confirm") == "Stop"
    assert "You free about 1.0 GB of memory." in dialog.get_body()
    shown = labels(dialog)
    assert "What happens" in shown
    assert "What stays" in shown
    assert "Saved files, data and settings." in shown
    assert "To start it again" in shown


def test_a_dangerous_removal_asks_to_type_the_name_in_english(display: None) -> None:
    request = ActionRequest(kind=ActionKind.VOLUME_REMOVE, target_id=TargetId("pgdata"))
    orphan = report(docker=docker_disk(volumes=(volume(name="pgdata"),)))

    dialog, _, _ = open_dialog(snap=snapshot(), request=request, subject="pgdata", disk=orphan)

    assert dialog.get_heading() == "Remove the volume pgdata?"
    assert dialog.get_response_label("confirm") == "Remove volume"
    (entry,) = entry_rows(dialog)
    assert entry.get_title() == "Type pgdata to confirm"
    assert any("deletes data for good" in text for text in labels(dialog))


def test_a_mixed_selection_and_the_totals_read_in_english() -> None:
    title = dialog_title(kind=ActionKind.GROUP_STOP, subject=None)
    assert title == "Stop these items?"
    assert reclaim_text(ram=GB, disk=GB, total=True) == (
        "In total you free about 1.0 GB of memory and 1.0 GB of disk space."
    )
    assert reclaim_text(ram=0, disk=0, total=False) == (
        "How much is freed cannot be estimated beforehand."
    )
    assert listed_note(listed=3 * GB, planned=GB) == (
        "The list counts 3.0 GB: the rest belongs to parts that cannot be stopped from here."
    )


def test_the_outcome_texts_are_in_english() -> None:
    plan = make_plan(steps=[process_step(order=1, pid=1), process_step(order=2, pid=2)])
    done = (StepOutcome(order=0, status=StepStatus.DONE),)
    stuck = (StepOutcome(order=0, status=StepStatus.NOT_RESPONDING),)
    failed = (StepOutcome(order=0, status=StepStatus.FAILED),)
    second = StepOutcome(order=1, status=StepStatus.FAILED)
    third = StepOutcome(order=2, status=StepStatus.NOT_RESPONDING)

    assert summary_text(outcomes=done, subject="whitebox") == "whitebox: operation completed"
    assert summary_text(outcomes=done, plan=plan, subject="whitebox") == "whitebox: stop completed"
    assert summary_text(outcomes=(*done, *done), plan=plan) == "2 items: stop completed"
    assert summary_text(outcomes=(*done, second), plan=plan) == "1 of 2 stopped, 1 failed"
    assert summary_text(outcomes=(*stuck, *done, third), plan=plan) == (
        "1 of 3 stopped, 2 not responding"
    )
    assert summary_text(outcomes=stuck, subject="firefox") == "firefox: not responding"
    assert summary_text(outcomes=failed, subject="firefox") == "firefox: operation failed"
    assert freed_text(delta=ReclaimDelta(freed_ram=GB, freed_disk=2 * GB)) == (
        "Freed 1.0 GB of RAM and 2.0 GB of disk"
    )
    assert freed_text(delta=ReclaimDelta(freed_ram=0, freed_disk=2 * GB)) == (
        "Freed 2.0 GB of disk"
    )
    (generic,) = step_reports(plan=None, outcomes=stuck)
    assert generic.label == "Step 0"
    assert generic.status_text == "Not responding"


def test_a_restart_reads_started_again_in_english() -> None:
    step = container_step(order=1, container_id="c1", kind=ActionKind.CONTAINER_START)
    plan = make_plan(steps=[step])
    done = (StepOutcome(order=1, status=StepStatus.DONE),)
    gone = (StepOutcome(order=1, status=StepStatus.ALREADY_GONE),)

    assert step_reports(plan=plan, outcomes=done)[0].status_text == "Started again"
    assert step_reports(plan=plan, outcomes=gone)[0].status_text == "Already running"


def test_the_outcome_dialog_shows_english_headings_and_force_button(display: None) -> None:
    stuck = (StepOutcome(order=0, status=StepStatus.NOT_RESPONDING),)
    reports = step_reports(plan=None, outcomes=stuck)
    dialog = OutcomeDialog(reports=reports, on_force=lambda _report: None)
    dialog.set_freed(text=freed_text(delta=ReclaimDelta(freed_ram=GB, freed_disk=0)))

    assert dialog.get_heading() == "Result"
    assert dialog.get_response_label("close") == "Close"
    extra = dialog.get_extra_child()
    assert extra is not None
    (row,) = [w for w in descendants(extra) if isinstance(w, Adw.ActionRow)]
    assert row.get_subtitle() == "Not responding"


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (ActionKind.PROCESS_KILL, "Force close"),
        (ActionKind.STOP_ALL_IDLE_SAFE, "Free the memory"),
        (ActionKind.CONTAINER_START, "Start again"),
        (ActionKind.BUILDER_PRUNE, "Empty the build cache"),
    ],
)
def test_action_buttons_read_in_english(kind: ActionKind, expected: str) -> None:
    assert button_label(kind=kind) == expected
