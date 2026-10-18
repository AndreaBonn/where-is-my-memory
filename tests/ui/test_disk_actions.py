from dataclasses import dataclass

import pytest
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
from tests.ui.conftest import WindowFactory, descendants, main_context_iterate, present_and_settle
from tests.ui.fakes import FakeDiskActionService, FakeDiskSource
from wimm.model.actions import ActionRequest
from wimm.model.disk import CacheKind, DiskReport
from wimm.model.enums import ActionKind, Risk, TargetId
from wimm.model.errors import InvalidRequest
from wimm.model.snapshot import Snapshot
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.ui.dialogs.confirm import CONFIRM_RESPONSE, ConfirmDialog
from wimm.ui.dialogs.facts import SHORT_ID_CHARS, UNNAMED_IMAGE
from wimm.ui.window import MainWindow

pytestmark = pytest.mark.ui
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


@pytest.mark.parametrize("case", ROW_CASES, ids=lambda c: c.request.kind.value)
def test_row_button_plans_confirms_and_executes_that_plan(
    window_factory: WindowFactory, case: RowCase
) -> None:
    window, service = setup(window_factory)

    click_row(window, case.title)

    assert service.planned == [case.request]
    dialog = dialog_of(window)
    assert dialog.get_heading() == case.heading
    assert service.executed == []
    if case.phrase is not None:
        assert not dialog.get_response_enabled(CONFIRM_RESPONSE)
        type_phrase(dialog, case.phrase)
    dialog.emit("response", CONFIRM_RESPONSE)
    assert service.last_plan is not None
    assert service.last_plan.confirm_phrase == case.phrase
    assert service.executed == [(service.last_plan.plan_id, case.phrase)]


def test_rows_that_cannot_act_have_no_button_and_actionable_ones_have_one(
    window_factory: WindowFactory,
) -> None:
    window, _ = setup(window_factory)

    assert len(row_buttons(window, "myapp:dev")) == 1
    assert row_buttons(window, "busy:1") == []
    assert len(row_buttons(window, "pgdata")) == 1
    assert row_buttons(window, "inuse") == []
    assert row_buttons(window, "nodate") == []


def test_a_source_that_cannot_plan_gets_no_buttons(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeDiskSource(snapshot=snapshot, report=full_report()))
    present_and_settle(window)

    assert len(row_buttons(window, "myapp:dev")) == 0
    assert window.action_flow is None


def test_dangling_prune_lists_its_images_and_executes_without_the_excluded_one(
    window_factory: WindowFactory,
) -> None:
    other = image(char="d", tags=(), dangling=True, size=2 * MB)
    disk = report(docker=docker_disk(images=(DANGLING, other)))
    window, service = setup(window_factory, disk=disk)

    click_label(window, "Elimina immagini senza nome")

    assert service.planned == [ActionRequest(kind=ActionKind.IMAGES_PRUNE_DANGLING)]
    dialog = dialog_of(window)
    extra = dialog.get_extra_child()
    assert extra is not None
    switches = {w.get_title(): w for w in descendants(extra) if isinstance(w, Adw.SwitchRow)}
    names = {
        UNNAMED_IMAGE.format(short=i.id.removeprefix("sha256:")[:SHORT_ID_CHARS]): i
        for i in (DANGLING, other)
    }
    assert set(switches) == set(names)
    switches[next(n for n, i in names.items() if i is other)].set_active(False)
    assert service.planned[-1].excluded_ids == frozenset({other.id})
    dialog.emit("response", CONFIRM_RESPONSE)
    assert service.last_plan is not None
    assert [s.target_label for s in service.last_plan.steps] == [DANGLING.id[:19]]
    assert service.executed == [(service.last_plan.plan_id, None)]


@pytest.mark.parametrize(
    ("label", "kind"),
    [
        ("Elimina immagini inutilizzate", ActionKind.IMAGES_PRUNE_UNUSED),
        ("Elimina container fermi", ActionKind.CONTAINERS_PRUNE_STOPPED),
    ],
)
def test_other_mass_actions_open_the_multi_target_dialog(
    window_factory: WindowFactory, label: str, kind: ActionKind
) -> None:
    window, service = setup(window_factory)

    click_label(window, label)

    assert service.planned == [ActionRequest(kind=kind)]
    assert dialog_of(window).get_extra_child() is not None


def test_mass_actions_appear_only_where_the_section_has_candidates(
    window_factory: WindowFactory,
) -> None:
    window, _ = setup(window_factory)
    labels_with = {
        w.get_label() or "" for w in descendants(window.disk) if isinstance(w, Gtk.Button)
    }
    assert any(label.startswith("Elimina container fermi") for label in labels_with)
    bare = report(docker=docker_disk(images=(IN_USE,)))
    quiet, _ = setup(window_factory, disk=bare)
    labels_without = {
        w.get_label() or "" for w in descendants(quiet.disk) if isinstance(w, Gtk.Button)
    }
    assert not any(label.startswith("Elimina") for label in labels_without)
    assert not any(label.startswith("Elimina immagini") for label in labels_without)


def test_a_plan_error_shows_a_plain_message_and_no_dialog(window_factory: WindowFactory) -> None:
    window, service = setup(window_factory)
    service.set_report(report())  # the image vanished from the report after the page was built

    click_row(window, "myapp:dev")
    main_context_iterate()

    assert window.action_flow is not None
    assert window.action_flow.dialog is None
    assert InvalidRequest.user_message in toast_texts(window)


def test_a_plan_error_toast_is_not_shown_when_the_plan_succeeds(
    window_factory: WindowFactory,
) -> None:
    window, _ = setup(window_factory)

    click_row(window, "myapp:dev")
    main_context_iterate()

    assert dialog_of(window) is not None
    assert InvalidRequest.user_message not in toast_texts(window)


def test_the_outcome_toast_says_how_much_was_freed_without_details(
    window_factory: WindowFactory,
) -> None:
    window, service = setup(window_factory)
    click_row(window, "Cache di build")
    dialog_of(window).emit("response", CONFIRM_RESPONSE)
    assert service.last_plan is not None

    done = StepOutcome(order=1, status=StepStatus.DONE, freed_bytes=100 * MB)
    service.emit("action-finished", service.last_plan.plan_id, (done,))
    main_context_iterate()

    assert "Cache di build: pulizia completata. Liberati 100 MB di disco" in toast_texts(window)
    buttons = [w.get_label() for w in descendants(window) if isinstance(w, Gtk.Button)]
    assert "Dettagli" not in buttons


def test_a_failed_target_is_reported_as_partial_with_details(
    window_factory: WindowFactory,
) -> None:
    window, service = setup(window_factory)
    click_row(window, "pgdata")
    type_phrase(dialog_of(window), "pgdata")
    dialog_of(window).emit("response", CONFIRM_RESPONSE)
    assert service.last_plan is not None

    failed = StepOutcome(order=1, status=StepStatus.FAILED, message="in use")
    service.emit("action-finished", service.last_plan.plan_id, (failed,))
    main_context_iterate()

    texts = toast_texts(window)
    assert "pgdata: operazione non riuscita" in texts
    assert not any(t.startswith("Fatto") for t in texts)


def test_buttons_are_disabled_while_an_action_runs_and_back_after(
    window_factory: WindowFactory,
) -> None:
    window, service = setup(window_factory)
    (button,) = row_buttons(window, "myapp:dev")
    assert button.get_sensitive()

    click_row(window, "Cache di build")
    dialog_of(window).emit("response", CONFIRM_RESPONSE)
    assert not button.get_sensitive()
    assert service.last_plan is not None
    done = StepOutcome(order=1, status=StepStatus.DONE)
    service.emit("action-finished", service.last_plan.plan_id, (done,))

    assert button.get_sensitive()


def test_free_safe_plans_only_the_safe_items_and_asks_once(window_factory: WindowFactory) -> None:
    window, service = setup(window_factory)

    click_label(window, "Libera ")

    assert service.planned == [ActionRequest(kind=ActionKind.DISK_FREE_SAFE)]
    assert service.last_plan is not None
    assert {s.risk for s in service.last_plan.steps} == {Risk.SAFE}
    dialog = dialog_of(window)
    assert dialog.get_heading() == "Liberare lo spazio che si ricrea da solo?"
    dialog.emit("response", CONFIRM_RESPONSE)
    assert service.executed == [(service.last_plan.plan_id, None)]


def test_free_safe_with_nothing_left_says_so(window_factory: WindowFactory) -> None:
    from wimm.ui.action_flow import NOTHING_SAFE_ON_DISK_TEXT

    window, service = setup(window_factory)
    service.set_report(report())  # everything was cleaned since the page was built

    click_label(window, "Libera ")
    main_context_iterate()

    assert window.action_flow is not None
    assert window.action_flow.dialog is None
    assert NOTHING_SAFE_ON_DISK_TEXT in toast_texts(window)
