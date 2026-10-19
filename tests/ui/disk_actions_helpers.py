from dataclasses import dataclass

from gi.repository import Adw, Gtk

from tests.core.disk_helpers import (
    MB,
    cache,
    devdir,
    docker_disk,
    image,
    report,
    stopped,
    volume,
)
from tests.core.planning_helpers import container, group
from tests.core.planning_helpers import snapshot as make_snapshot
from tests.ui.conftest import WindowFactory, descendants, present_and_settle
from tests.ui.fakes import FakeDiskActionService
from wimm.model.actions import ActionRequest
from wimm.model.disk import CacheKind, DiskReport
from wimm.model.enums import ActionKind, TargetId
from wimm.model.snapshot import Snapshot
from wimm.ui.dialogs.confirm import ConfirmDialog
from wimm.ui.window import MainWindow

STOPPED_ID = "e" * 64
DEVDIR = "/home/u/proj/node_modules"
# F7: the row reads as project and folder; the path stays the action target.
DEVDIR_TITLE = "proj · node_modules"
UNUSED = image(char="a", tags=("myapp:dev",), local_build=True)
DANGLING = image(char="b", tags=(), dangling=True, size=5 * MB)
IN_USE = image(char="c", tags=("busy:1",), in_use=True)


def full_report() -> DiskReport:
    return report(
        docker=docker_disk(
            images=(UNUSED, DANGLING, IN_USE),
            volumes=(
                volume(name="pgdata"),
                volume(name="inuse", ref_count=1),
                volume(name="nodate", created_at=""),
            ),
            containers=(stopped(cid="e"),),
            build_cache_size=100 * MB,
        ),
        caches=(cache(kind=CacheKind.UV), cache(kind=CacheKind.TRASH, ino=12)),
        devdirs=(devdir(path=DEVDIR),),
    )


def with_stopped_container() -> Snapshot:
    member = container(cid=STOPPED_ID, state="exited")
    return make_snapshot(group(gid="c1", members=(member,)))


def setup(
    factory: WindowFactory, *, disk: DiskReport | None = None
) -> tuple[MainWindow, FakeDiskActionService]:
    service = FakeDiskActionService(snapshot=with_stopped_container(), report=disk or full_report())
    window = factory(service)
    present_and_settle(window)
    return window, service


def row_buttons(window: MainWindow, title: str) -> list[Gtk.Button]:
    rows = [w for w in descendants(window.disk) if isinstance(w, Adw.ActionRow)]
    (row,) = [r for r in rows if r.get_title() == title]
    return [w for w in descendants(row) if isinstance(w, Gtk.Button)]


def click_row(window: MainWindow, title: str) -> None:
    (button,) = row_buttons(window, title)
    button.emit("clicked")


def click_label(window: MainWindow, label: str) -> None:
    """Click the one disk button whose label starts with ``label`` (the ellipsis is optional)."""
    (button,) = [
        w
        for w in descendants(window.disk)
        if isinstance(w, Gtk.Button) and (w.get_label() or "").startswith(label)
    ]
    button.emit("clicked")


def dialog_of(window: MainWindow) -> ConfirmDialog:
    assert window.action_flow is not None
    assert window.action_flow.dialog is not None
    return window.action_flow.dialog


def type_phrase(dialog: ConfirmDialog, text: str) -> None:
    extra = dialog.get_extra_child()
    assert extra is not None
    (entry,) = [w for w in descendants(extra) if isinstance(w, Adw.EntryRow) and w.is_visible()]
    entry.set_text(text)


def toast_texts(window: MainWindow) -> list[str]:
    return [w.get_label() for w in descendants(window) if isinstance(w, Gtk.Label)]


@dataclass(frozen=True)
class RowCase:
    title: str
    request: ActionRequest
    heading: str
    phrase: str | None = None


ROW_CASES = [
    RowCase(
        "myapp:dev",
        ActionRequest(kind=ActionKind.IMAGE_REMOVE, target_id=TargetId(UNUSED.id)),
        "Rimuovere l'immagine myapp:dev?",
    ),
    RowCase(
        "pgdata",
        ActionRequest(kind=ActionKind.VOLUME_REMOVE, target_id=TargetId("pgdata")),
        "Rimuovere il volume pgdata?",
        phrase="pgdata",
    ),
    RowCase(
        "uv",
        ActionRequest(kind=ActionKind.CACHE_CLEAN, target_id=TargetId("uv")),
        "Pulire la cache uv?",
    ),
    RowCase(
        "Cestino",
        ActionRequest(kind=ActionKind.TRASH_EMPTY),
        "Svuotare il cestino?",
        phrase="Cestino",
    ),
    RowCase(
        "Cache di build",
        ActionRequest(kind=ActionKind.BUILDER_PRUNE),
        "Svuotare la cache di build?",
    ),
    RowCase(
        DEVDIR_TITLE,
        ActionRequest(kind=ActionKind.DEVDIR_DELETE, target_id=TargetId(DEVDIR)),
        f"Eliminare la cartella {DEVDIR_TITLE}?",
    ),
    RowCase(
        "ctr-e",
        ActionRequest(kind=ActionKind.CONTAINER_REMOVE, target_id=TargetId(STOPPED_ID)),
        "Rimuovere ctr-e?",
    ),
]
