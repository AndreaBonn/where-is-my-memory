import pytest
from gi.repository import Adw, Gtk

from tests.core.disk_helpers import docker_disk, image, report, volume
from tests.core.planning_helpers import container, group, proc, snapshot
from tests.ui.conftest import FakeActionService, descendants
from wimm.core.risk_table import CONSEQUENCES, ConsequenceKey
from wimm.model.actions import ActionRequest, Plan
from wimm.model.disk import DiskReport
from wimm.model.enums import ActionKind, Category, GroupId, TargetId
from wimm.model.snapshot import Snapshot
from wimm.ui.dialogs.confirm import CONFIRM_RESPONSE, ConfirmDialog
from wimm.ui.dialogs.session import ConfirmSession, entries_for
from wimm.ui.format import format_size

pytestmark = pytest.mark.ui
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
        session=session, on_confirm=lambda p, typed: confirmed.append((p, typed))
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


def test_safe_dialog_names_the_target_the_recovery_and_uses_the_suggested_style(
    display: None,
) -> None:
    snap = snapshot(group(gid="p", name="whitebox", members=(proc(pid=1, reclaimable=GB),)))

    dialog, _, _ = open_dialog(snap=snap, request=stop("p"), subject="whitebox")

    assert dialog.get_heading() == "Fermare whitebox?"
    assert dialog.get_response_label(CONFIRM_RESPONSE) == "Ferma"
    assert dialog.get_response_label("cancel") == "Annulla"
    assert dialog.get_response_appearance(CONFIRM_RESPONSE) == Adw.ResponseAppearance.SUGGESTED
    assert f"libera circa {format_size(size=GB)} di RAM" in dialog.get_body()
    assert "node (pid 1)" in labels(dialog)
    assert dialog.get_response_enabled(CONFIRM_RESPONSE)
    assert not entry_rows(dialog)
    assert not switches(dialog)


def test_caution_dialog_is_destructive_and_shows_the_consequences(display: None) -> None:
    snap = snapshot(
        group(gid="a", name="agent", members=(proc(pid=2, category=Category.AI_CLI),)),
        group(gid="s", name="server", members=(proc(pid=1),)),
    )
    safe, _, _ = open_dialog(snap=snap, request=stop("s"), subject="server")

    dialog, _, _ = open_dialog(snap=snap, request=stop("a"), subject="agent")

    warning = CONSEQUENCES[ConsequenceKey.AGENT]
    assert dialog.get_response_appearance(CONFIRM_RESPONSE) == Adw.ResponseAppearance.DESTRUCTIVE
    assert warning in labels(dialog)
    assert not entry_rows(dialog)
    assert warning not in labels(safe)
    assert safe.get_response_appearance(CONFIRM_RESPONSE) == Adw.ResponseAppearance.SUGGESTED


def test_danger_dialog_enables_the_button_only_for_the_exact_phrase(display: None) -> None:
    request = ActionRequest(kind=ActionKind.VOLUME_REMOVE, target_id=TargetId("pgdata"))
    orphan = report(docker=docker_disk(volumes=(volume(name="pgdata"),)))
    dialog, _, confirmed = open_dialog(
        snap=snapshot(), request=request, subject="pgdata", disk=orphan
    )
    (entry,) = entry_rows(dialog)

    assert "pgdata" in entry.get_title()
    assert dialog.get_response_appearance(CONFIRM_RESPONSE) == Adw.ResponseAppearance.DESTRUCTIVE
    assert not dialog.get_response_enabled(CONFIRM_RESPONSE)
    for wrong in ("pgdat", "PGDATA", "pgdata ", " pgdata", "pgdatax"):
        entry.set_text(wrong)
        assert not dialog.get_response_enabled(CONFIRM_RESPONSE), wrong
    entry.set_text("pgdata")
    assert dialog.get_response_enabled(CONFIRM_RESPONSE)
    entry.set_text("pgdat")
    assert not dialog.get_response_enabled(CONFIRM_RESPONSE)
    entry.set_text("pgdata")
    dialog.emit("response", CONFIRM_RESPONSE)
    assert [(plan.confirm_phrase, typed) for plan, typed in confirmed] == [("pgdata", "pgdata")]


def test_typed_confirmation_says_why_it_is_asked_and_safe_dialogs_do_not(display: None) -> None:
    request = ActionRequest(kind=ActionKind.VOLUME_REMOVE, target_id=TargetId("pgdata"))
    orphan = report(docker=docker_disk(volumes=(volume(name="pgdata"),)))
    danger, _, _ = open_dialog(snap=snapshot(), request=request, subject="pgdata", disk=orphan)
    snap = snapshot(group(gid="p", name="whitebox", members=(proc(pid=1, reclaimable=GB),)))
    safe, _, _ = open_dialog(snap=snap, request=stop("p"), subject="whitebox")

    hint = "Ti chiediamo di scrivere il nome perché questa azione cancella dati"
    assert any(text.startswith(hint) for text in labels(danger))
    assert not any(text.startswith(hint) for text in labels(safe))


def test_confirming_a_non_danger_plan_passes_no_typed_text(display: None) -> None:
    snap = snapshot(group(gid="p", members=(proc(pid=1),)))
    dialog, _, confirmed = open_dialog(snap=snap, request=stop("p"), subject="p")

    dialog.emit("response", "cancel")
    assert confirmed == []
    dialog.emit("response", CONFIRM_RESPONSE)

    assert [typed for _, typed in confirmed] == [None]


def test_removing_an_entry_asks_for_a_new_plan_and_updates_total_and_risk(display: None) -> None:
    dialog, service, _ = open_dialog(snap=mixed_project(), request=stop("p"), subject="whitebox")
    before = dialog.get_body()
    warning = CONSEQUENCES[ConsequenceKey.AGENT]
    rows = switches(dialog)

    assert set(rows) == {"node (pid 1)", "node (pid 2)", "name-db"}
    assert all(row.get_active() for row in rows.values())
    assert warning in labels(dialog)
    assert dialog.get_response_appearance(CONFIRM_RESPONSE) == Adw.ResponseAppearance.DESTRUCTIVE
    assert format_size(size=GB + GB // 10 + GB // 2) in before

    rows["node (pid 2)"].set_active(False)

    assert service.planned[-1].excluded_ids == frozenset({"2"})
    assert format_size(size=GB + GB // 2) in dialog.get_body()
    assert dialog.get_body() != before
    assert warning not in labels(dialog)
    assert dialog.get_response_appearance(CONFIRM_RESPONSE) == Adw.ResponseAppearance.SUGGESTED
    assert dialog.get_response_enabled(CONFIRM_RESPONSE)


def test_removing_every_entry_disables_the_button_and_adding_one_back_enables_it(
    display: None,
) -> None:
    dialog, service, confirmed = open_dialog(
        snap=mixed_project(), request=stop("p"), subject="whitebox"
    )
    rows = switches(dialog)

    for row in rows.values():
        row.set_active(False)

    assert service.planned[-1].excluded_ids == frozenset({"1", "2", "db"})
    assert not dialog.get_response_enabled(CONFIRM_RESPONSE)
    assert "Nessuna voce" in dialog.get_body()
    rows["name-db"].set_active(True)
    assert dialog.get_response_enabled(CONFIRM_RESPONSE)
    dialog.emit("response", CONFIRM_RESPONSE)
    assert [sorted(s.target_label for s in plan.steps) for plan, _ in confirmed] == [["name-db"]]
    assert confirmed[0][0].request.excluded_ids == frozenset({"1", "2"})


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

    switches(dialog)["name-c"].set_active(False)

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
    assert set(rows) == {first.id[:19], second.id[:19]}

    rows[second.id[:19]].set_active(False)

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
    assert "node (pid 1)" in shown  # positive pair: the plain names still render
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
    rows["/home/u/.cache/uv"].set_active(False)

    assert service.planned[-1].excluded_ids == frozenset({"/home/u/.cache/uv"})
    assert f"libera circa {format_size(size=6 * MB)} di disco" in dialog.get_body()
