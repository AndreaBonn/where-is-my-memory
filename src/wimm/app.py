import logging
import os
import signal
import sys
from typing import TYPE_CHECKING, Any

from wimm import __version__

if TYPE_CHECKING:
    from gi.repository import Gio

SUCCESS = 0
STARTUP_FAILED = 1
APPLICATION_ID = "io.github.wimm.WhereIsMyMemory"
LOGGER = logging.getLogger(__name__)


class WindowHost:
    def present(self, group_id: str | None) -> None:
        if group_id is not None:
            LOGGER.info("Requested group %s", group_id)
        LOGGER.info("window not implemented yet")


def _activate(application: Any) -> None:
    application._window_host.present(group_id=None)


def _quit(application: Any) -> bool:
    from gi.repository import GLib

    if application._held:
        application.release()
        application._held = False
    application.quit()
    return GLib.SOURCE_CONTINUE


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
    application._service = AppService(sampler=sampler, config=loaded.config)


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
    application.hold()
    application._held = True
    application._signals = tuple(
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, _quit, application)
        for sig in (signal.SIGINT, signal.SIGTERM)
    )
    application._service.start()


def _shutdown(application: Any) -> None:
    from gi.repository import Gio, GLib

    if application._service is not None:
        application._service.stop()
    if application._inspector is not None:
        application._inspector.close()
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
        _signals: tuple[int, ...] = ()
        do_startup = _startup
        do_shutdown = _shutdown
        do_command_line = _command_line
        do_activate = _activate

    application = Application(
        application_id=os.environ.get("WIMM_APP_ID", APPLICATION_ID),
        flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
    )
    application._window_host = WindowHost()
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
