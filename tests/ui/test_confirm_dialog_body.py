import pytest

from tests.core.planning_helpers import container, group, proc, snapshot
from tests.ui.conftest import descendants
from wimm.model.enums import Category
from wimm.ui.dialogs.confirm import ConfirmDialog
from wimm.ui.format import format_size

pytestmark = pytest.mark.ui
from tests.ui.confirm_dialog_helpers import GB, labels, open_dialog, stop, switches


def test_safe_stop_shows_what_stays_and_how_to_restart(display: None) -> None:
    members = (proc(pid=1, reclaimable=GB), container(cid="db", reclaimable=GB // 2))
    snap = snapshot(group(gid="p", name="whitebox", members=members))

    dialog, _, _ = open_dialog(snap=snap, request=stop("p"), subject="whitebox")

    shown = labels(dialog)
    assert "Cosa resta" in shown
    assert "Per riaccenderlo" in shown
    assert not [text for text in shown if "docker start" in text]


def test_body_explains_a_listed_amount_the_plan_cannot_free(display: None) -> None:
    from dataclasses import replace

    other = proc(pid=9, reclaimable=GB, uid=4242)  # another user's process: not stopped
    snap = snapshot(group(gid="p", name="mixed", members=(proc(pid=1, reclaimable=GB), other)))
    listed = replace(snap.groups[0].memory, reclaimable=2 * GB)
    snap = replace(snap, groups=(replace(snap.groups[0], memory=listed),))

    dialog, _, _ = open_dialog(snap=snap, request=stop("p"), subject="mixed")

    body = dialog.get_body()
    assert f"Liberi circa {format_size(size=GB)} di memoria." in body
    assert f"Nella lista conta {format_size(size=2 * GB)}" in body


def test_unticking_an_entry_does_not_blame_parts_that_cannot_stop(display: None) -> None:
    from dataclasses import replace

    members = (
        proc(pid=1, reclaimable=GB),
        proc(pid=2, reclaimable=GB),
        proc(pid=9, reclaimable=GB, uid=4242),  # another user's process: not stopped
    )
    snap = snapshot(group(gid="p", name="mixed", members=members))
    listed = replace(snap.groups[0].memory, reclaimable=3 * GB)
    snap = replace(snap, groups=(replace(snap.groups[0], memory=listed),))
    dialog, _, _ = open_dialog(snap=snap, request=stop("p"), subject="mixed")
    assert "Nella lista conta" in dialog.get_body()

    next(iter(switches(dialog).values())).set_active(False)

    assert "Nella lista conta" not in dialog.get_body()


def warning_box_classes(dialog: ConfirmDialog) -> set[str]:
    extra = dialog.get_extra_child()
    assert extra is not None
    boxes = [w for w in descendants(extra) if w.has_css_class("wimm-warning")]
    facts = [w for w in descendants(extra) if w.has_css_class("wimm-facts")]
    return {name for name, found in (("wimm-warning", boxes), ("wimm-facts", facts)) if found}


def test_consequences_use_warning_style_for_caution_and_plain_style_for_safe(
    display: None,
) -> None:
    snap = snapshot(
        group(gid="a", name="agent", members=(proc(pid=2, category=Category.AI_CLI),)),
        group(gid="s", name="server", members=(proc(pid=1),)),
    )

    caution, _, _ = open_dialog(snap=snap, request=stop("a"), subject="agent")
    safe, _, _ = open_dialog(snap=snap, request=stop("s"), subject="server")

    assert warning_box_classes(caution) == {"wimm-warning"}
    assert warning_box_classes(safe) == {"wimm-facts"}
