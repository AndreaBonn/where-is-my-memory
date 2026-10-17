import logging
from dataclasses import dataclass

from gi.repository import Gdk, Gio, GLib, Gtk

from wimm.i18n import _

from . import name_icon_button

LOGGER = logging.getLogger(__name__)
CONTEXT_GROUP = "ctx"


@dataclass(frozen=True, slots=True)
class MenuTarget:
    """What the context menu can copy or open for one group or member."""

    command: str | None
    pid: str | None
    cwd: str | None


def _context_menu() -> Gio.Menu:
    menu = Gio.Menu()
    menu.append(_("Copia comando"), f"{CONTEXT_GROUP}.copy-command")
    menu.append(_("Copia PID"), f"{CONTEXT_GROUP}.copy-pid")
    menu.append(_("Apri cartella"), f"{CONTEXT_GROUP}.open-folder")
    return menu


def _open_folder(path: str) -> None:
    try:
        Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)
    except GLib.Error:
        # Only the path is logged: it is the one thing the user asked to open.
        LOGGER.warning("Could not open folder %s", path)


def install_context_actions(*, owner: Gtk.Widget, target: MenuTarget) -> Gio.SimpleActionGroup:
    """(Re)create the ctx.* actions of ``owner``; absent data disables the menu item."""
    actions = Gio.SimpleActionGroup()
    clipboard = owner.get_clipboard()
    specs = (
        ("copy-command", target.command, lambda text: clipboard.set(text)),
        ("copy-pid", target.pid, lambda text: clipboard.set(text)),
        ("open-folder", target.cwd, _open_folder),
    )
    for name, value, handler in specs:
        action = Gio.SimpleAction.new(name, None)
        action.set_enabled(value is not None)
        if value is not None:
            action.connect("activate", lambda _action, _param, v=value, h=handler: h(v))
        actions.add_action(action)
    owner.insert_action_group(CONTEXT_GROUP, actions)
    return actions


def menu_label(*, title: str) -> str:
    """The accessible name of the ⋮ button of the row called ``title``."""
    return _("Altre azioni: {title}").format(title=title)


def make_context_button(*, title: str) -> Gtk.MenuButton:
    """The ⋮ button that opens the context menu of the row it is placed on."""
    button = Gtk.MenuButton(
        icon_name="view-more-symbolic", menu_model=_context_menu(), valign=Gtk.Align.CENTER
    )
    button.add_css_class("flat")
    name_icon_button(button=button, label=menu_label(title=title))
    return button


def attach_right_click(*, widget: Gtk.Widget, button: Gtk.MenuButton) -> None:
    """Open the context menu of ``button`` on a secondary click on ``widget``."""
    gesture = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
    gesture.connect("pressed", lambda *_args: button.popup())
    widget.add_controller(gesture)
