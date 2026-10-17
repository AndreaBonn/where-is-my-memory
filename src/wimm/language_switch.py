"""``win.set-language``: save the choice, switch gettext, rebuild what shows text."""

import logging
import os
from pathlib import Path
from typing import Any

from wimm import i18n

LOGGER = logging.getLogger(__name__)
ACTION_NAME = "set-language"
PREFERENCES_ACTION = "win.preferences"
# Applications with a rebuild already queued: quick toggles share one rebuild.
_PENDING: set[int] = set()


def apply_startup_language() -> None:
    """Pick the language before the ``--help`` texts exist; the service start applies it again."""
    from wimm.config import load_config
    from wimm.paths import default_user_paths

    # No logging yet: a warning would hit stderr; the service start logs it to the file.
    config_logger = logging.getLogger(load_config.__module__)
    config_logger.disabled = True
    try:
        saved = load_config(paths=default_user_paths(), home=Path.home()).config.language
    finally:
        config_logger.disabled = False
    i18n.set_language(language=saved or i18n.resolve_default(environ=os.environ))


def switch_language(*, application: Any, language: str) -> None:
    """Make ``language`` the interface language now and for the next starts.

    The window is rebuilt from an idle callback: the toggle that asked for the change
    lives inside it and must not be destroyed while its signal is running.
    """
    from gi.repository import GLib

    if language not in i18n.LANGUAGES:
        LOGGER.warning("Unsupported language requested: %s", language)
        return
    if language == i18n.current_language():
        return
    _save_choice(application=application, language=language)
    i18n.set_language(language=language)
    if id(application) not in _PENDING:
        _PENDING.add(id(application))
        GLib.idle_add(_refresh_views, application)


def _save_choice(*, application: Any, language: str) -> None:
    from wimm.model.errors import WimmError
    from wimm.paths import default_user_paths

    service = application._service
    if service is None:
        return
    try:
        service.update_config(
            changes={"language": language}, paths=default_user_paths(), home=Path.home()
        )
    except (OSError, WimmError):
        LOGGER.warning("Cannot save the language choice; it lasts until exit", exc_info=True)


def _refresh_views(application: Any) -> bool:
    from gi.repository import GLib

    _PENDING.discard(id(application))
    try:
        application._window_host.rebuild(then=_reopen_preferences)
        if application._tray is not None:
            application._tray.refresh()
    finally:
        if application._service is not None:
            # Reasons in the current snapshot were written in the old language (plan R1).
            application._service.retry_now()
    return GLib.SOURCE_REMOVE


def _reopen_preferences(window: Any) -> None:
    window.activate_action(PREFERENCES_ACTION, None)


def register_language_action(*, actions: Any, application: Any) -> None:
    """Add ``set-language`` (a language code as string parameter) to a window's actions.

    A window action, not an ``app.`` one: those are exported on the session bus, and no
    other process needs to change the language (the exported set is pinned by a test).
    """
    from gi.repository import Gio, GLib

    action = Gio.SimpleAction.new(name=ACTION_NAME, parameter_type=GLib.VariantType.new("s"))
    action.connect(
        "activate",
        lambda _a, parameter: switch_language(
            application=application, language=parameter.get_string()
        ),
    )
    actions.add_action(action)
