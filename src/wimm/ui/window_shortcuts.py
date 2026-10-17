from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

ACTION_PREFERENCES = "win.preferences"


def shortcut_controller(
    *, on_refresh: Callable[[], None], on_find: Callable[[], None]
) -> Gtk.ShortcutController:
    """Window-wide shortcuts: F5 refreshes, Ctrl+F searches, Ctrl+, opens the preferences."""

    def run(callback: Callable[[], None]) -> Callable[..., bool]:
        def handler(*_args: object) -> bool:
            callback()
            return True

        return handler

    controller = Gtk.ShortcutController(scope=Gtk.ShortcutScope.GLOBAL)
    shortcuts = (
        ("F5", Gtk.CallbackAction.new(run(on_refresh))),
        ("<Control>f", Gtk.CallbackAction.new(run(on_find))),
        ("<Control>comma", Gtk.NamedAction.new(ACTION_PREFERENCES)),
    )
    for trigger, action in shortcuts:
        controller.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string(trigger), action))
    return controller
