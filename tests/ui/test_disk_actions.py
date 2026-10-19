import pytest
from gi.repository import Adw, Gtk

from tests.core.disk_helpers import (
    MB,
    docker_disk,
    image,
    report,
)
from tests.ui.conftest import WindowFactory, descendants, present_and_settle
from tests.ui.disk_actions_helpers import (
    DANGLING,
    IN_USE,
    ROW_CASES,
    RowCase,
    click_label,
    click_row,
    dialog_of,
    full_report,
    row_buttons,
    setup,
    type_phrase,
)
from tests.ui.fakes import FakeDiskSource
from wimm.model.actions import ActionRequest
from wimm.model.enums import ActionKind
from wimm.model.snapshot import Snapshot
from wimm.ui.dialogs.confirm import CONFIRM_RESPONSE
from wimm.ui.dialogs.facts import SHORT_ID_CHARS, UNNAMED_IMAGE

pytestmark = pytest.mark.ui


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
