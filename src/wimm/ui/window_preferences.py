from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gi.repository import Gio

from wimm.paths import UserPaths
from wimm.ui.dialogs.preferences import PreferencesDialog
from wimm.ui.window_shortcuts import ACTION_PREFERENCES

ACTION_NAME = ACTION_PREFERENCES.removeprefix("win.")


@dataclass(frozen=True)
class PreferencesEnv:
    """Where the preferences file lives and the home its directories must stay in."""

    paths: UserPaths
    home: Path


def can_edit_config(*, source: object) -> bool:
    """True when the source can read and save preferences (the real service)."""
    return all(callable(getattr(source, name, None)) for name in ("config", "update_config"))


def install_preferences(*, window: Any, source: object, env: PreferencesEnv) -> bool:
    """Register `win.preferences` so the menu entry and Ctrl+, open the dialog.

    Without the service the action stays unregistered and the entry stays disabled.
    """
    if not can_edit_config(source=source):
        return False

    def open_dialog(*_args: object) -> None:
        if isinstance(window.get_visible_dialog(), PreferencesDialog):
            return
        PreferencesDialog(source=source, paths=env.paths, home=env.home).present(window)

    action = Gio.SimpleAction.new(ACTION_NAME, None)
    action.connect("activate", open_dialog)
    window.window_actions.add_action(action)
    return True
