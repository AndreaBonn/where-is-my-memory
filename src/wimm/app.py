import logging
import os
import signal
import sys
from collections.abc import Callable, Mapping
from functools import partial
from typing import TYPE_CHECKING, Any, Protocol

from wimm import __version__

if TYPE_CHECKING:
    from gi.repository import Gio

SUCCESS = 0
STARTUP_FAILED = 1
APPLICATION_ID = "io.github.wimm.WhereIsMyMemory"
LOGGER = logging.getLogger(__name__)


class PresentableWindow(Protocol):
    def show_group(self, group_id: str | None) -> None: ...

    def set_tray_missing(self, missing: bool) -> None: ...


class WindowHost:
    """Owns the panel window, built on the first request so GTK loads only then."""

    def __init__(self, *, factory: Callable[[], PresentableWindow]) -> None:
        self._factory = factory
        self._window: PresentableWindow | None = None
        self._tray_missing = False

    def set_tray_missing(self, *, missing: bool) -> None:
        """Remember whether the icon has no host; a window not built yet is not created."""
        self._tray_missing = missing
        if self._window is not None:
            self._window.set_tray_missing(missing)

    def present(self, group_id: str | None) -> None:
        if group_id is not None:
            LOGGER.info("Window requested for group %s", group_id)
        if self._window is None:
            try:
                self._window = self._factory()
            except Exception:
                # No display (session gone, SSH, tests): monitoring and notifications go on.
                LOGGER.exception("Cannot open the window")
                return
            if self._tray_missing:
                self._window.set_tray_missing(True)
        self._window.show_group(group_id=group_id)


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

    return create_main_window(
        application=application, source=application._service, clock=wall_clock
    )


def _activate(application: Any) -> None:
    application._window_host.present(group_id=None)


def _quit(application: Any) -> bool:
    from gi.repository import GLib

    if application._held:
        application.release()
        application._held = False
    application.quit()
    return GLib.SOURCE_CONTINUE


def _build_actions(*, config: Any, owner_uid: int) -> Any:
    from wimm.service.actions import ActionSetup
    from wimm.service.compose import DockerComposeControl
    from wimm.service.controls import DockerSdkControl, PsutilProcessControl
    from wimm.service.executor import PlanExecutor

    try:
        containers = DockerSdkControl.from_env()
    except Exception:
        LOGGER.warning("Docker client unavailable, container actions disabled", exc_info=True)
        containers = None
    try:
        compose = DockerComposeControl.from_env()
    except Exception:
        LOGGER.warning("Docker compose unavailable, project actions disabled", exc_info=True)
        compose = None
    processes = PsutilProcessControl(
        owner_uid=owner_uid, extra_protected_names=config.extra_protected_names
    )
    executor = PlanExecutor(
        processes=processes,
        containers=containers,
        compose=compose,
        owner_uid=owner_uid,
        terminate_timeout_s=config.terminate_timeout_s,
    )
    return ActionSetup(executor=executor, owner_uid=owner_uid)


def _start_service(application: Any) -> None:
    from wimm.config import load_config
    from wimm.logging_setup import setup_logging
    from wimm.paths import default_user_paths
    from wimm.service.app_service import AppService
    from wimm.service.sampler import Sampler, default_collectors, default_environment

    paths = default_user_paths()
    setup_logging(paths=paths)
    environment = default_environment(paths=paths)
    loaded = load_config(paths=paths, home=environment.home)
    for name, error in loaded.field_errors.items():
        LOGGER.warning("Invalid configuration field %s: %s", name, error)
    sampler = Sampler(
        collectors=default_collectors(environment=environment),
        environment=environment,
        config=loaded.config,
    )
    actions = _build_actions(config=loaded.config, owner_uid=environment.uid)
    application._service = AppService(sampler=sampler, config=loaded.config, actions=actions)


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
    if application._service is None:
        return STARTUP_FAILED
    options = command_line.get_options_dict()
    group = options.lookup_value("group", None)
    background = options.lookup_value("background", None)
    if background is None or not background.get_boolean():
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

    for name, kind, description, argument in (
        ("background", GLib.OptionArg.NONE, "Avvia senza aprire la finestra", None),
        ("group", GLib.OptionArg.STRING, "Mostra un gruppo", "ID"),
        ("version", GLib.OptionArg.NONE, "Mostra la versione", None),
    ):
        application.add_main_option(name, 0, GLib.OptionFlags.NONE, kind, description, argument)
    action = Gio.SimpleAction.new(name="quit", parameter_type=None)
    action.connect("activate", lambda *_: _quit(application=application))
    application.add_action(action=action)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments == ["--version"]:
        print(f"wimm {__version__}")
        return SUCCESS
    application = create_application()
    return application.run(argv=["wimm", *arguments])
