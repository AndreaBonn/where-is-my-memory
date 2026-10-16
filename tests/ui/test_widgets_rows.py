from datetime import datetime

import pytest
from gi.repository import Adw, Gtk

from tests.ui.conftest import descendants, main_context_iterate
from wimm.model.snapshot import Snapshot
from wimm.ui.viewmodel import build_rows
from wimm.ui.views import (
    GroupRow,
    MemberRow,
    RowFilters,
)
from wimm.ui.widgets import icon_only_label, install_style
from wimm.ui.widgets.group_row import (
    PRIMARY_ACTION_NAME,
    GroupRowWidget,
    MenuTarget,
    group_target,
    member_subtitle,
    target_of,
)

pytestmark = pytest.mark.ui
LONG_NAME_LENGTH = 200


@pytest.fixture
def group_row(display: None, snapshot: Snapshot, now: datetime) -> GroupRow:
    install_style()
    return build_rows(snapshot=snapshot, filters=RowFilters(), now=now)[0]


def labels_under(widget: Gtk.Widget) -> list[Gtk.Label]:
    return [w for w in descendants(widget) if isinstance(w, Gtk.Label)]


def test_actionable_group_row_has_exactly_one_disabled_primary_button(group_row: GroupRow) -> None:
    widget = GroupRowWidget(row=group_row)

    buttons = [w for w in descendants(widget) if w.get_name() == PRIMARY_ACTION_NAME]

    assert len(buttons) == 1
    assert isinstance(buttons[0], Gtk.Button)
    assert buttons[0].get_label() == "Ferma"
    assert not buttons[0].get_sensitive()
    assert buttons[0].get_tooltip_text() == "Disponibile con le azioni (fase 3)"


def test_group_without_primary_action_has_no_button_and_says_so_in_the_badge(
    display: None, group_row: GroupRow
) -> None:
    from dataclasses import replace

    row = replace(
        group_row,
        primary_action=None,
        risk=None,
        risk_text="Nessuna azione",
        risk_style="dim-label",
    )

    widget = GroupRowWidget(row=row)

    assert not [w for w in descendants(widget) if w.get_name() == PRIMARY_ACTION_NAME]
    assert "Nessuna azione" in {label.get_label() for label in labels_under(widget)}


def test_group_row_text_and_tooltip_come_from_the_view_model(group_row: GroupRow) -> None:
    widget = GroupRowWidget(row=group_row)

    assert widget.get_title() == "whitebox"
    assert widget.get_subtitle() == f"{group_row.subtitle}\n{group_row.detail}"
    assert widget.get_tooltip_text() == group_row.explanation
    assert not widget.get_use_markup()


def test_name_with_markup_characters_is_shown_literally(group_row: GroupRow) -> None:
    from dataclasses import replace

    widget = GroupRowWidget(row=replace(group_row, title="a<b>&c"))

    texts = [label.get_label() for label in labels_under(widget)]
    assert "a<b>&c" in texts


def test_two_hundred_character_name_is_ellipsized_not_wrapped(group_row: GroupRow) -> None:
    from dataclasses import replace

    name = "n" * LONG_NAME_LENGTH
    widget = GroupRowWidget(row=replace(group_row, title=name))

    (title,) = [label for label in labels_under(widget) if label.get_label() == name]

    assert title.get_ellipsize().value_nick == "end"
    assert title.get_lines() == 1


def test_members_are_built_only_when_the_row_is_expanded(group_row: GroupRow) -> None:
    widget = GroupRowWidget(row=group_row)
    names = {m.name for m in group_row.members}
    before = {label.get_label() for label in labels_under(widget)}
    assert names.isdisjoint(before)

    widget.set_expanded(True)

    after = {label.get_label() for label in labels_under(widget)}
    assert names <= after


def test_member_subtitle_lists_pid_command_cwd_ports_start_and_memory(group_row: GroupRow) -> None:
    process = next(m for m in group_row.members if m.kind == "process")

    text = member_subtitle(member=process)

    assert text.splitlines()[0] == "PID 941149 · avvio 16/10 06:46 · 180 MB · inattivo da 5 h"
    assert "comando: uvicorn app:main --port 8000" in text
    assert "cartella: /home/bonn/projects/ai-whitebox-core" in text
    assert "porte: 8000" in text


def test_container_subtitle_shows_image_state_and_mounts(group_row: GroupRow) -> None:
    container = next(m for m in group_row.members if m.kind == "container")

    lines = member_subtitle(member=container).splitlines()

    assert lines[0].startswith("2c9184903a37 · 682 MB")
    assert "immagine quay.io/keycloak/keycloak:26.0.8 (running)" in lines
    assert any(line.startswith("mount bind: ") for line in lines)
    assert not any("PID" in line or line.startswith("comando") for line in lines)


def test_context_targets_use_the_first_process_and_skip_containers(group_row: GroupRow) -> None:
    assert group_target(row=group_row) == MenuTarget(
        command="uvicorn app:main --port 8000",
        pid="941149",
        cwd="/home/bonn/projects/ai-whitebox-core",
    )
    container = next(m for m in group_row.members if m.kind == "container")
    assert target_of(member=container) == MenuTarget(command=None, pid=None, cwd=None)


def test_context_actions_are_enabled_only_when_the_data_exists(group_row: GroupRow) -> None:
    widget = GroupRowWidget(row=group_row)
    actions = widget.context_actions
    assert all(
        actions.get_action_enabled(name) for name in ("copy-command", "copy-pid", "open-folder")
    )

    from dataclasses import replace

    containers = tuple(m for m in group_row.members if m.kind == "container")
    widget.update(row=replace(group_row, members=containers))

    actions = widget.context_actions
    assert not any(
        actions.get_action_enabled(name) for name in ("copy-command", "copy-pid", "open-folder")
    )


def test_update_with_an_identical_row_keeps_the_expanded_state(group_row: GroupRow) -> None:
    widget = GroupRowWidget(row=group_row)
    widget.set_expanded(True)

    widget.update(row=group_row)

    assert widget.get_expanded()


def test_update_rebuilds_the_members_of_an_expanded_row(group_row: GroupRow) -> None:
    from dataclasses import replace

    widget = GroupRowWidget(row=group_row)
    widget.set_expanded(True)
    process = next(m for m in group_row.members if m.kind == "process")
    renamed: MemberRow = replace(process, name="renamed-process")

    widget.update(row=replace(group_row, members=(renamed,)))

    texts = {label.get_label() for label in labels_under(widget)}
    assert "renamed-process" in texts
    assert "whitebox-keycloak" not in texts


def test_icon_only_buttons_register_their_accessible_label(group_row: GroupRow) -> None:
    widget = GroupRowWidget(row=group_row)
    widget.set_expanded(True)

    icon_buttons = [
        w
        for w in descendants(widget)
        if isinstance(w, Gtk.MenuButton) and w.get_icon_name() is not None
    ]

    assert len(icon_buttons) == 1 + len(group_row.members)
    for button in icon_buttons:
        assert (icon_only_label(button=button) or "").startswith("Altre azioni: ")
        assert button.get_tooltip_text() == icon_only_label(button=button)


def test_adw_is_the_libadwaita_expander(group_row: GroupRow) -> None:
    assert isinstance(GroupRowWidget(row=group_row), Adw.ExpanderRow)


def open_in_window(widget: GroupRowWidget) -> Gtk.Window:
    window = Gtk.Window(default_width=900, default_height=700)
    box = Gtk.ListBox()
    box.append(widget)
    window.set_child(box)
    window.present()
    main_context_iterate()
    return window


def member_row_named(widget: GroupRowWidget, name: str) -> Adw.ActionRow:
    return next(
        w for w in descendants(widget) if isinstance(w, Adw.ActionRow) and w.get_title() == name
    )


def member_menu(row: Adw.ActionRow) -> Gtk.MenuButton:
    return next(
        w
        for w in descendants(row)
        if isinstance(w, Gtk.MenuButton) and w.get_icon_name() is not None
    )


def with_first_member_memory(group_row: GroupRow, memory: str) -> GroupRow:
    from dataclasses import replace

    first = replace(group_row.members[0], memory=memory)
    return replace(group_row, members=(first, *group_row.members[1:]))


def test_update_keeps_member_widgets_and_the_open_menu(group_row: GroupRow) -> None:
    widget = GroupRowWidget(row=group_row)
    window = open_in_window(widget)
    widget.set_expanded(True)
    name = group_row.members[0].name
    member_row = member_row_named(widget, name)
    menu = member_menu(member_row)
    menu.popup()
    main_context_iterate()
    assert menu.get_active()

    widget.update(row=with_first_member_memory(group_row, "999 MB"))

    assert member_row_named(widget, name) is member_row
    assert "999 MB" in (member_row.get_subtitle() or "")
    assert menu.get_active()
    window.destroy()


def focus_is_inside(*, window: Gtk.Window, button: Gtk.MenuButton) -> bool:
    """MenuButton hands the focus to its inner toggle, so test the button or a descendant."""
    focus = window.get_focus()
    return focus is not None and (focus is button or focus.is_ancestor(button))


def test_update_keeps_the_focus_on_a_member_button(group_row: GroupRow) -> None:
    widget = GroupRowWidget(row=group_row)
    window = open_in_window(widget)
    widget.set_expanded(True)
    button = member_menu(member_row_named(widget, group_row.members[0].name))
    assert button.grab_focus()
    assert focus_is_inside(window=window, button=button)

    widget.update(row=with_first_member_memory(group_row, "1 GB"))

    assert focus_is_inside(window=window, button=button)
    window.destroy()


def test_set_of_members_changing_rebuilds_the_member_rows(group_row: GroupRow) -> None:
    from dataclasses import replace

    widget = GroupRowWidget(row=group_row)
    widget.set_expanded(True)
    old_row = member_row_named(widget, group_row.members[0].name)
    extra = replace(group_row.members[0], key="424242", name="extra-process")

    widget.update(row=replace(group_row, members=(*group_row.members, extra)))

    assert member_row_named(widget, "extra-process") is not None
    assert member_row_named(widget, group_row.members[0].name) is not old_row


def test_collapsed_row_skips_member_work_and_catches_up_when_reopened(group_row: GroupRow) -> None:
    widget = GroupRowWidget(row=group_row)
    widget.set_expanded(True)
    widget.set_expanded(False)
    member_row = member_row_named(widget, group_row.members[0].name)
    old_subtitle = member_row.get_subtitle()

    widget.update(row=with_first_member_memory(group_row, "7 GB"))
    assert member_row.get_subtitle() == old_subtitle

    widget.set_expanded(True)

    assert "7 GB" in (member_row.get_subtitle() or "")
