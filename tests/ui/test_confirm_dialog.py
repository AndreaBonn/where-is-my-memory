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
from wimm.ui.dialogs.facts import SHORT_ID_CHARS, UNNAMED_IMAGE
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


def test_safe_dialog_names_the_target_the_recovery_and_uses_the_suggested_style(
    display: None,
) -> None:
    snap = snapshot(group(gid="p", name="whitebox", members=(proc(pid=1, reclaimable=GB),)))

    dialog, _, _ = open_dialog(snap=snap, request=stop("p"), subject="whitebox")

    assert dialog.get_heading() == "Fermare whitebox?"
    assert dialog.get_response_label(CONFIRM_RESPONSE) == "Ferma"
    assert dialog.get_response_label("cancel") == "Annulla"
    assert dialog.get_response_appearance(CONFIRM_RESPONSE) == Adw.ResponseAppearance.SUGGESTED
    assert f"Liberi circa {format_size(size=GB)} di memoria." in dialog.get_body()
    assert "node · 1,0 GB" in labels(dialog)
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

    assert set(rows) == {"node · 1,0 GB", "node · 100 MB", "name-db · 500 MB"}
    assert all(row.get_active() for row in rows.values())
    assert warning in labels(dialog)
    assert dialog.get_response_appearance(CONFIRM_RESPONSE) == Adw.ResponseAppearance.DESTRUCTIVE
    assert format_size(size=GB + GB // 10 + GB // 2) in before

    rows["node · 100 MB"].set_active(False)

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
    row_for(rows, part="name-db").set_active(True)
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
