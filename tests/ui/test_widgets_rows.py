import pytest
from gi.repository import Gtk

from tests.ui.conftest import descendants, main_context_iterate
from tests.ui.widgets_rows_helpers import (
    focus_is_inside,
    labels_under,
    member_menu,
    member_row_named,
    open_in_window,
    with_first_member_memory,
)
from tests.ui.widgets_rows_helpers import group_row as group_row
from wimm.ui.views import (
    GroupRow,
    MemberRow,
)
from wimm.ui.widgets import icon_only_label
from wimm.ui.widgets.context_menu import MenuTarget
from wimm.ui.widgets.group_row import PRIMARY_ACTION_NAME, GroupRowWidget
from wimm.ui.widgets.member_row import (
    DETAILS_BUTTON_NAME,
    member_subtitle,
    member_summary,
    target_of,
)

pytestmark = pytest.mark.ui
LONG_NAME_LENGTH = 200


def test_actionable_group_row_has_exactly_one_disabled_primary_button(group_row: GroupRow) -> None:
    widget = GroupRowWidget(row=group_row)

    buttons = [w for w in descendants(widget) if w.get_name() == PRIMARY_ACTION_NAME]

    assert len(buttons) == 1
    assert isinstance(buttons[0], Gtk.Button)
    assert buttons[0].get_label() == "Ferma"
    assert not buttons[0].get_sensitive()
    assert buttons[0].get_tooltip_text() == "Le azioni non sono attive in questa finestra"


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
    assert group_row.growth_text == "+620 MB in 2 h"
    assert widget.get_subtitle() == (f"{group_row.subtitle} · +620 MB in 2 h\n{group_row.detail}")
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
    names = {m.title for m in group_row.members}
    before = {label.get_label() for label in labels_under(widget)}
    assert names.isdisjoint(before)

    widget.set_expanded(True)

    after = {label.get_label() for label in labels_under(widget)}
    assert names <= after


def test_member_subtitle_lists_pid_command_cwd_ports_start_and_memory(group_row: GroupRow) -> None:
    process = next(m for m in group_row.members if m.kind == "process")

    text = member_subtitle(member=process)

    assert text.splitlines()[0] == "PID 941149 · avvio 16/10 06:46 · 180 MB · non in uso da 5 h"
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


def test_container_has_no_menu_target(group_row: GroupRow) -> None:
    container = next(m for m in group_row.members if m.kind == "container")
    process = next(m for m in group_row.members if m.kind == "process")
    assert target_of(member=container) == MenuTarget(command=None, pid=None, cwd=None)
    assert target_of(member=process).pid == "941149"


def test_group_row_has_no_menu_of_its_own(group_row: GroupRow) -> None:
    # P10: copy and open live on the members, where the data is; the row stays plain.
    widget = GroupRowWidget(row=group_row)
    assert not [w for w in descendants(widget) if isinstance(w, Gtk.MenuButton)]
    widget.set_expanded(True)
    assert len([w for w in descendants(widget) if isinstance(w, Gtk.MenuButton)]) == len(
        group_row.members
    )


def test_member_shows_a_short_line_and_the_technical_one_on_request(group_row: GroupRow) -> None:
    widget = GroupRowWidget(row=group_row)
    widget.set_expanded(True)
    process = next(m for m in group_row.members if m.kind == "process")
    row = member_row_named(widget, process.title)
    toggle = next(w for w in descendants(row) if w.get_name() == DETAILS_BUTTON_NAME)
    assert isinstance(toggle, Gtk.ToggleButton)

    assert row.get_subtitle() == member_summary(member=process)
    assert "PID" not in (row.get_subtitle() or "")

    toggle.set_active(True)
    assert member_subtitle(member=process) in (row.get_subtitle() or "")

    widget.update(row=with_first_member_memory(group_row, "3 GB"))
    assert "PID" in (row.get_subtitle() or "")


def test_member_summary_reads_memory_start_and_use(group_row: GroupRow) -> None:
    process = next(m for m in group_row.members if m.kind == "process")
    assert member_summary(member=process) == "180 MB · avviato 16/10 06:46 · non in uso da 5 h"


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
    renamed: MemberRow = replace(process, name="renamed-process", title="renamed-process")

    widget.update(row=replace(group_row, members=(renamed,)))

    texts = {label.get_label() for label in labels_under(widget)}
    assert "renamed-process" in texts
    assert "Accesso utenti (whitebox-keycloak)" not in texts


def test_icon_only_buttons_register_their_accessible_label(group_row: GroupRow) -> None:
    widget = GroupRowWidget(row=group_row)
    widget.set_expanded(True)

    icon_buttons = [
        w
        for w in descendants(widget)
        if isinstance(w, Gtk.MenuButton) and w.get_icon_name() is not None
    ]

    assert len(icon_buttons) == len(group_row.members)
    for button in icon_buttons:
        assert (icon_only_label(button=button) or "").startswith("Altre azioni: ")
        assert button.get_tooltip_text() == icon_only_label(button=button)


def test_update_keeps_member_widgets_and_the_open_menu(group_row: GroupRow) -> None:
    widget = GroupRowWidget(row=group_row)
    window = open_in_window(widget)
    widget.set_expanded(True)
    name = group_row.members[0].title
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


def test_update_keeps_the_focus_on_a_member_button(group_row: GroupRow) -> None:
    widget = GroupRowWidget(row=group_row)
    window = open_in_window(widget)
    widget.set_expanded(True)
    button = member_menu(member_row_named(widget, group_row.members[0].title))
    assert button.grab_focus()
    assert focus_is_inside(window=window, button=button)

    widget.update(row=with_first_member_memory(group_row, "1 GB"))

    assert focus_is_inside(window=window, button=button)
    window.destroy()


def test_set_of_members_changing_keeps_the_members_that_stay(group_row: GroupRow) -> None:
    from dataclasses import replace

    widget = GroupRowWidget(row=group_row)
    widget.set_expanded(True)
    old_row = member_row_named(widget, group_row.members[0].title)
    opened = next(w for w in descendants(old_row) if w.get_name() == DETAILS_BUTTON_NAME)
    assert isinstance(opened, Gtk.ToggleButton)
    opened.set_active(True)
    extra = replace(group_row.members[0], key="424242", name="extra-process", title="extra-process")

    widget.update(row=replace(group_row, members=(*group_row.members, extra)))

    assert member_row_named(widget, "extra-process") is not None
    # The member that stayed keeps its widget, with its details still open.
    assert member_row_named(widget, group_row.members[0].title) is old_row
    toggle = next(w for w in descendants(old_row) if w.get_name() == DETAILS_BUTTON_NAME)
    assert isinstance(toggle, Gtk.ToggleButton)
    assert toggle.get_active()


def test_collapsed_row_skips_member_work_and_catches_up_when_reopened(group_row: GroupRow) -> None:
    widget = GroupRowWidget(row=group_row)
    widget.set_expanded(True)
    widget.set_expanded(False)
    member_row = member_row_named(widget, group_row.members[0].title)
    old_subtitle = member_row.get_subtitle()

    widget.update(row=with_first_member_memory(group_row, "7 GB"))
    assert member_row.get_subtitle() == old_subtitle

    widget.set_expanded(True)

    assert "7 GB" in (member_row.get_subtitle() or "")


def test_a_new_member_does_not_steal_the_focus_from_one_that_stays(group_row: GroupRow) -> None:
    from dataclasses import replace

    widget = GroupRowWidget(row=group_row)
    window = open_in_window(widget)
    widget.set_expanded(True)
    button = member_menu(member_row_named(widget, group_row.members[0].title))
    assert button.grab_focus()
    extra = replace(group_row.members[0], key="424242", name="extra", title="extra")

    widget.update(row=replace(group_row, members=(*group_row.members, extra)))

    assert member_row_named(widget, "extra") is not None
    assert focus_is_inside(window=window, button=button)
    window.destroy()


def test_group_row_subtitle_drops_the_growth_when_it_goes_away(group_row: GroupRow) -> None:
    from dataclasses import replace

    widget = GroupRowWidget(row=group_row)
    widget.update(row=replace(group_row, growth_text=None))

    assert widget.get_subtitle() == f"{group_row.subtitle}\n{group_row.detail}"
