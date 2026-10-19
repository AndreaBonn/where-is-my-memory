from gi.repository import Adw, Gtk

from tests.core.planning_helpers import container, group, proc, snapshot
from tests.ui.conftest import FakeActionService, descendants
from wimm.model.actions import ActionRequest, Plan
from wimm.model.disk import DiskReport
from wimm.model.enums import ActionKind, Category, GroupId
from wimm.model.snapshot import Snapshot
from wimm.ui.dialogs.confirm import ConfirmDialog
from wimm.ui.dialogs.facts import SHORT_ID_CHARS, UNNAMED_IMAGE
from wimm.ui.dialogs.session import ConfirmSession, entries_for

GB = 1_000_000_000
Confirmed = list[tuple[Plan, str | None]]


def open_dialog(
    *, snap: Snapshot, request: ActionRequest, subject: str | None, disk: DiskReport | None = None
) -> tuple[ConfirmDialog, FakeActionService, Confirmed]:
    service = FakeActionService(snapshot=snap)
    service.disk_report = disk
    plan = service.plan(request=request)
    session = ConfirmSession(
        plan=plan,
        subject=subject,
        entries=entries_for(plan=plan, snapshot=snap),
        replan=lambda new: service.plan(request=new),
    )
    confirmed: Confirmed = []
    dialog = ConfirmDialog(
        session=session,
        on_confirm=lambda p, typed: confirmed.append((p, typed)),
        snapshot=snap,
    )
    return dialog, service, confirmed


def stop(gid: str) -> ActionRequest:
    return ActionRequest(kind=ActionKind.GROUP_STOP, group_id=GroupId(gid))


def labels(dialog: ConfirmDialog) -> list[str]:
    """Texts shown in the extra child: labels and row titles that are visible."""
    extra = dialog.get_extra_child()
    assert extra is not None
    shown = [w for w in descendants(extra) if isinstance(w, Gtk.Label) and w.is_visible()]
    texts = [w.get_label() for w in shown]
    texts += [w.get_title() for w in descendants(extra) if isinstance(w, Adw.ActionRow)]
    return texts


def switches(dialog: ConfirmDialog) -> dict[str, Adw.SwitchRow]:
    extra = dialog.get_extra_child()
    assert extra is not None
    return {w.get_title(): w for w in descendants(extra) if isinstance(w, Adw.SwitchRow)}


def row_for(rows: dict[str, Adw.SwitchRow], *, part: str) -> Adw.SwitchRow:
    """The one switch whose plain title mentions the technical name `part`."""
    (row,) = [row for title, row in rows.items() if part in title]
    return row


def unnamed(*, image_id: str) -> str:
    return UNNAMED_IMAGE.format(short=image_id.removeprefix("sha256:")[:SHORT_ID_CHARS])


def entry_rows(dialog: ConfirmDialog) -> list[Adw.EntryRow]:
    extra = dialog.get_extra_child()
    assert extra is not None
    return [w for w in descendants(extra) if isinstance(w, Adw.EntryRow) and w.is_visible()]


def mixed_project() -> Snapshot:
    members = (
        proc(pid=1, reclaimable=GB),
        proc(pid=2, category=Category.AI_CLI, reclaimable=GB // 10),
        container(cid="db", reclaimable=GB // 2),
    )
    return snapshot(group(gid="p", name="whitebox", members=members))
