import pytest
from gi.repository import Adw, Gtk

from tests.core.disk_helpers import docker_disk, image, report
from tests.core.planning_helpers import container, group, proc, snapshot
from tests.ui.conftest import FakeActionService, descendants
from wimm.model.actions import ActionRequest
from wimm.model.enums import ActionKind
from wimm.ui.dialogs.confirm import CONFIRM_RESPONSE, ConfirmDialog
from wimm.ui.dialogs.session import ConfirmSession, entries_for
from wimm.ui.format import format_size

pytestmark = pytest.mark.ui
from tests.ui.confirm_dialog_helpers import GB, open_dialog, row_for, stop, switches, unnamed


def test_stop_all_lists_entries_grouped_by_group_with_one_total(display: None) -> None:
    snap = snapshot(
        group(gid="a", name="alfa", members=(proc(pid=1, reclaimable=100),)),
        group(
            gid="b",
            name="beta",
            members=(proc(pid=2, reclaimable=200), container(cid="c", reclaimable=300)),
        ),
    )
    request = ActionRequest(kind=ActionKind.STOP_ALL_IDLE_SAFE)
    dialog, service, _ = open_dialog(snap=snap, request=request, subject=None)
    extra = dialog.get_extra_child()
    assert extra is not None

    titles = [w.get_title() for w in descendants(extra) if isinstance(w, Adw.PreferencesGroup)]
    assert dialog.get_heading() == "Fermare i programmi che non usi?"
    assert dialog.get_response_label(CONFIRM_RESPONSE) == "Libera la memoria"
    assert titles == ["alfa", "beta"]
    assert "600 B" in dialog.get_body()

    row_for(switches(dialog), part="name-c").set_active(False)

    assert service.planned[-1].kind is ActionKind.STOP_ALL_IDLE_SAFE
    assert service.planned[-1].excluded_ids == frozenset({"c"})
    assert "300 B" in dialog.get_body()


def test_prune_dialog_offers_a_switch_per_image_and_replans_without_the_removed_one(
    display: None,
) -> None:
    first = image(char="a", tags=(), dangling=True, size=5 * GB)
    second = image(char="b", tags=(), dangling=True, size=2 * GB)
    request = ActionRequest(kind=ActionKind.IMAGES_PRUNE_DANGLING)
    service = FakeActionService(snapshot=snapshot())
    service.disk_report = report(docker=docker_disk(images=(first, second)))
    plan = service.plan(request=request)
    session = ConfirmSession(
        plan=plan,
        subject=None,
        entries=entries_for(plan=plan, snapshot=snapshot()),
        replan=lambda new: service.plan(request=new),
    )
    dialog = ConfirmDialog(session=session, on_confirm=lambda *_: None)

    rows = switches(dialog)
    assert set(rows) == {unnamed(image_id=first.id), unnamed(image_id=second.id)}

    rows[unnamed(image_id=second.id)].set_active(False)

    assert service.planned[-1].excluded_ids == frozenset({second.id})
    assert format_size(size=5 * GB) in dialog.get_body()


def test_names_with_markup_characters_are_shown_literally(display: None) -> None:
    # A group, process or volume name with "&" or "<" made the libadwaita title empty.
    members = (proc(pid=1, reclaimable=GB), proc(pid=2, reclaimable=GB))
    snap = snapshot(group(gid="p", name="R&D <lab>", members=members))

    dialog, _, _ = open_dialog(snap=snap, request=stop("p"), subject="R&D <lab>")

    extra = dialog.get_extra_child()
    assert extra is not None
    shown = [w.get_text() for w in descendants(extra) if isinstance(w, Gtk.Label)]
    assert "R&D <lab>" in shown
    assert "node · 1,0 GB" in shown  # positive pair: the plain names still render
    (entry,) = [w for w in descendants(extra) if isinstance(w, Adw.EntryRow)]
    entry.set_title("Scrivi R&D <lab> per confermare")
    assert "Scrivi R&D <lab> per confermare" in [
        w.get_text() for w in descendants(entry) if isinstance(w, Gtk.Label)
    ]


def test_free_safe_dialog_lets_each_item_be_left_out(display: None) -> None:
    from tests.core.disk_helpers import MB, cache
    from wimm.model.disk import CacheKind

    disk = report(
        docker=docker_disk(
            images=(image(char="a", tags=(), dangling=True, size=2 * MB),),
            build_cache_size=5 * MB,
            build_cache_reclaimable=4 * MB,
        ),
        caches=(cache(kind=CacheKind.UV, size=3 * MB),),
    )
    request = ActionRequest(kind=ActionKind.DISK_FREE_SAFE)
    dialog, service, _ = open_dialog(snap=snapshot(), request=request, subject=None, disk=disk)

    rows = switches(dialog)
    assert len(rows) == 3
    rows["uv"].set_active(False)

    assert service.planned[-1].excluded_ids == frozenset({"/home/u/.cache/uv"})
    assert f"liberi circa {format_size(size=6 * MB)} di spazio sul disco" in dialog.get_body()
