import logging
import os
import signal
import sys
from collections.abc import Callable, Mapping
from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING, Any

from wimm import __version__
from wimm.window_host import PresentableWindow as PresentableWindow
from wimm.window_host import WindowHost as WindowHost

if TYPE_CHECKING:
    from gi.repository import Gio

SUCCESS = 0
STARTUP_FAILED = 1
APPLICATION_ID = "io.github.wimm.WhereIsMyMemory"
LOGGER = logging.getLogger(__name__)
# Read by the preferences: following the foreground window needs X11 (R5).
SESSION_TYPE_VARIABLE = "XDG_SESSION_TYPE"


# The GL renderer maps Mesa and LLVM into a process that stays resident all day: with it
# the hidden window costs 227 MB RSS, with Cairo and GL disabled 130 MB (docs/PERF.md).
GRAPHICS_DEFAULTS = {"GSK_RENDERER": "cairo", "GDK_DEBUG": "gl-disable,vulkan-disable"}


def graphics_defaults(environment: Mapping[str, str]) -> dict[str, str]:
    """GTK rendering variables to set, leaving any the user already chose untouched."""
    return {key: value for key, value in GRAPHICS_DEFAULTS.items() if key not in environment}


def _build_window(application: Any) -> PresentableWindow:
    # GDK reads these when GTK initialises, so they must be set before the import below.
    os.environ.update(graphics_defaults(environment=os.environ))
    import gi

    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, Gtk

    # Without a display Adw.init() waits about 25 s for portals before failing, which
    # would freeze the main loop of the resident process. init_check() reports success
    # even then under PyGObject, so the opened display is what tells.
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        raise RuntimeError("No graphical display available")
    # Importing wimm.ui.window pulls in libadwaita (docs/DEVIATIONS.md).
    from wimm.service.sampler import wall_clock
    from wimm.ui.window import create_main_window

    window = create_main_window(
        application=application, source=application._service, clock=wall_clock
    )
    _install_preferences(application=application, window=window)
    return window


def _install_preferences(*, application: Any, window: Any) -> None:
    from pathlib import Path

    from wimm.paths import default_user_paths
    from wimm.ui.window_preferences import PreferencesEnv, install_preferences

    env = PreferencesEnv(
        paths=default_user_paths(),
        home=Path.home(),
        session_type=os.environ.get(SESSION_TYPE_VARIABLE),
    )
    install_preferences(window=window, source=application._service, env=env)


def _activate(application: Any) -> None:
    application._window_host.present(group_id=None)


def _quit(application: Any) -> bool:
    from gi.repository import GLib

    if application._held:
        application.release()
        application._held = False
    application.quit()
    return GLib.SOURCE_CONTINUE


def _log_field_errors(*, errors: Mapping[str, Any]) -> None:
    for name, error in errors.items():
        LOGGER.warning("Invalid configuration field %s: %s", name, error)


def _build_sampler(*, environment: Any, config: Any) -> Any:
    from wimm.service.sampler import Sampler, default_collectors

    collectors = default_collectors(environment=environment)
    return Sampler(collectors=collectors, environment=environment, config=config)


def _start_service(application: Any) -> None:
    from wimm.config import load_config
    from wimm.logging_setup import setup_logging
    from wimm.paths import default_user_paths
    from wimm.service.app_service import AppService
    from wimm.service.build_actions import build_actions
    from wimm.service.disk_scanner import build_disk_scanner
    from wimm.service.notifications import attach_notifications
    from wimm.service.sampler import default_environment, wall_clock
    from wimm.service.state_store import StateSaver, load_state

    paths = default_user_paths()
    setup_logging(paths=paths)
    state = load_state(paths=paths, now=wall_clock())
    environment = replace(default_environment(paths=paths), persisted_last_active=state.last_active)
    loaded = load_config(paths=paths, home=environment.home)
    _log_field_errors(errors=loaded.field_errors)
    sampler = _build_sampler(environment=environment, config=loaded.config)
    actions = build_actions(config=loaded.config, owner_uid=environment.uid)
    service = AppService(sampler=sampler, config=loaded.config, actions=actions)
    service.restore_user_state(state=state)
    service.attach_disk_scanner(
        scanner=build_disk_scanner(home=environment.home, cache_dir=paths.cache_dir)
    )
    saver = StateSaver(paths=paths, state=state, last_active=sampler.export_last_active)
    service.attach_state_saver(saver=saver)
    application._service, application._state_dir = service, paths.state_dir
    application._notifications = attach_notifications(
        service=service, sink=application, saver=saver, state=state
    )


def _tray_missing(application: Any, missing: bool) -> None:
    # No host for the icon: open the window even with --background, so the banner explains why.
    application._window_host.set_tray_missing(missing=missing)
    if missing:
        application._window_host.present(group_id=None)


def _start_tray(application: Any, connection: Any) -> None:
    # Gio and GLib only: the tray must never pull GTK into the resident process.
    from wimm.tray.tray import Tray

    try:
        tray = Tray(
            connection=connection,
            service=application._service,
            on_open=lambda group_id: application._window_host.present(group_id=group_id),
            on_quit=lambda: application.activate_action("quit", None),
        )
        tray.start(on_missing=partial(_tray_missing, application))
    except Exception:
        # Monitoring, notifications and the window still work without the icon.
        LOGGER.exception("Cannot show the tray icon")
        return
    application._tray = tray


def _startup(application: Any) -> None:
    from gi.repository import Gio, GLib

    from wimm.service.inspector_dbus import Inspector

    Gio.Application.do_startup(application)
    connection = application.get_dbus_connection()
    if connection is None:
        LOGGER.error("Session bus is unavailable")
        return
    _start_service(application=application)
    application._inspector = Inspector(connection=connection, service=application._service)
    _start_tray(application=application, connection=connection)
    application.hold()
    application._held = True
    application._signals = tuple(
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, _quit, application)
        for sig in (signal.SIGINT, signal.SIGTERM)
    )
    application._service.start()


def _release(release: Callable[[], None]) -> None:
    # One failing part must not keep the others, or Gio's own shutdown, from running.
    try:
        release()
    except Exception:
        LOGGER.exception("Cannot release %s", release)


def _shutdown(application: Any) -> None:
    from gi.repository import Gio, GLib

    service, tray, inspector = application._service, application._tray, application._inspector
    for release in (
        service and service.stop,
        tray and tray.close,
        inspector and inspector.close,
    ):
        if release is not None:
            _release(release=release)
    for source in application._signals:
        GLib.source_remove(source)
    Gio.Application.do_shutdown(application)


def _command_line(application: Any, command_line: Any) -> int:
    from wimm.first_run import opens_window

    if application._service is None:
        return STARTUP_FAILED
    options = command_line.get_options_dict()
    group = options.lookup_value("group", None)
    background = options.lookup_value("background", None)
    in_background = background is not None and background.get_boolean()
    if opens_window(background=in_background, state_dir=application._state_dir):
        if group is None:
            application.activate()
        else:
            application._window_host.present(group_id=group.get_string())
    return SUCCESS


def create_application() -> "Gio.Application":
    from gi.repository import Gio

    class Application(Gio.Application):
        _window_host: WindowHost
        _held: bool = False
        _service: Any = None
        _state_dir: Any = None
        _notifications: Any = None
        _inspector: Any = None
        _tray: Any = None
        _signals: tuple[int, ...] = ()
        do_startup = _startup
        do_shutdown = _shutdown
        do_command_line = _command_line
        do_activate = _activate

    application = Application(
        application_id=os.environ.get("WIMM_APP_ID", APPLICATION_ID),
        flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
    )
    application._window_host = WindowHost(factory=partial(_build_window, application))
    _configure_options(application=application)
    return application


def _configure_options(application: "Gio.Application") -> None:
    from gi.repository import Gio, GLib

    from wimm.service.group_actions import register_group_actions, register_monitor_action

    for name, kind, description, argument in (
        ("background", GLib.OptionArg.NONE, "Avvia senza aprire la finestra", None),
        ("group", GLib.OptionArg.STRING, "Mostra un gruppo", "ID"),
        ("version", GLib.OptionArg.NONE, "Mostra la versione", None),
    ):
        application.add_main_option(name, 0, GLib.OptionFlags.NONE, kind, description, argument)
    action = Gio.SimpleAction.new(name="quit", parameter_type=None)
    action.connect("activate", lambda *_: _quit(application=application))
    application.add_action(action=action)
    register_group_actions(application=application)
    register_monitor_action(application=application)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments == ["--version"]:
        print(f"wimm {__version__}")
        return SUCCESS
    application = create_application()
    return application.run(argv=["wimm", *arguments])
