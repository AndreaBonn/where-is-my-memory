import pytest
from gi.repository import Adw

from tests.core.disk_helpers import docker_disk, report, volume
from tests.core.planning_helpers import group, proc, snapshot
from wimm.core.risk_table import CONSEQUENCES, ConsequenceKey
from wimm.model.actions import ActionRequest
from wimm.model.enums import ActionKind, Category, TargetId
from wimm.ui.dialogs.confirm import CONFIRM_RESPONSE
from wimm.ui.format import format_size

pytestmark = pytest.mark.ui
from tests.ui.confirm_dialog_helpers import (
    GB,
    entry_rows,
    labels,
    mixed_project,
    open_dialog,
    row_for,
    stop,
    switches,
)


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
