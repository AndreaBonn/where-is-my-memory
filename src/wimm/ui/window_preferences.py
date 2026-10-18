from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gi.repository import Gio

from wimm.paths import UserPaths
from wimm.ui.dialogs.preferences import PreferencesDialog
from wimm.ui.window_shortcuts import ACTION_FOLDERS, ACTION_PREFERENCES

ACTION_NAME = ACTION_PREFERENCES.removeprefix("win.")
FOLDERS_ACTION_NAME = ACTION_FOLDERS.removeprefix("win.")


@dataclass(frozen=True)
class PreferencesEnv:
    """Where the preferences file lives, the home its directories must stay in, the session.

    `session_type` is `XDG_SESSION_TYPE`: following the foreground window needs X11 (R5).
    """

    paths: UserPaths
    home: Path
    session_type: str | None = None


def can_edit_config(*, source: object) -> bool:
    """True when the source can read and save preferences (the real service)."""
    return all(callable(getattr(source, name, None)) for name in ("config", "update_config"))


def install_preferences(*, window: Any, source: object, env: PreferencesEnv) -> bool:
    """Register `win.preferences` so the menu entry and Ctrl+, open the dialog.

    Without the service the action stays unregistered and the entry stays disabled.
    """
    if not can_edit_config(source=source):
        return False

    def open_dialog(*, folders: bool) -> None:
        shown = window.get_visible_dialog()
        if not isinstance(shown, PreferencesDialog):
            shown = PreferencesDialog(
                source=source, paths=env.paths, home=env.home, session_type=env.session_type
            )
            shown.present(window)
        if folders:
            shown.show_folders()

    for name, folders in ((ACTION_NAME, False), (FOLDERS_ACTION_NAME, True)):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", lambda *_a, folders=folders: open_dialog(folders=folders))
        window.window_actions.add_action(action)
    return True
