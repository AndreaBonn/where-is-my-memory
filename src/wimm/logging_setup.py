import copy
import json
import logging
import os
import sys
from datetime import UTC, datetime
from io import TextIOWrapper
from logging.handlers import RotatingFileHandler
from pathlib import Path

from wimm.paths import PRIVATE_FILE_MODE, UserPaths, ensure_private_dir
from wimm.redaction import REDACTED, SECRET_FIELD, redact_text

LOG_MAX_BYTES = 1024 * 1024
LOG_BACKUP_COUNT = 3
STANDARD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
CMDLINE_FIELDS = frozenset({"cmdline", "command_line"})
OWNED_HANDLER = "_wimm_handler"


def _redact(value: object) -> object:
    if not isinstance(value, str | dict | list | tuple | int | float | bool | type(None)):
        value = str(value)
    if isinstance(value, str):
        return redact_text(text=value)
    if isinstance(value, dict):
        return {
            key: REDACTED if SECRET_FIELD.fullmatch(str(key)) else _redact(value=item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact(value=item) for item in value]
    return value


class RedactionFilter(logging.Filter):
    """Remove credential arguments and secret extra values from a record copy."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact one record in place.

        Parameters
        ----------
        record : logging.LogRecord
            Formatter-owned copy, isolated from other logging handlers.
        """
        record.msg = _redact(value=record.getMessage())
        record.args = ()
        for key in record.__dict__.keys() - STANDARD_FIELDS:
            record.__dict__[key] = (
                REDACTED if SECRET_FIELD.fullmatch(key) else _redact(value=record.__dict__[key])
            )
        return True


def _record_data(record: logging.LogRecord) -> dict[str, object]:
    extras = {
        key: value
        for key, value in record.__dict__.items()
        if key not in STANDARD_FIELDS
        and not (record.levelno >= logging.INFO and key in CMDLINE_FIELDS)
    }
    return {
        **extras,
        "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
        "level": record.levelname,
        "logger": record.name,
        "message": record.getMessage(),
    }


class LogFormatter(logging.Formatter):
    """Format redacted records as JSON or readable terminal lines."""

    def __init__(self, *, readable: bool) -> None:
        super().__init__()
        self.readable = readable
        self.redaction = RedactionFilter()

    def format(self, record: logging.LogRecord) -> str:
        """Render a record without modifying the original.

        Parameters
        ----------
        record : logging.LogRecord
            Event and extra fields to redact and serialize.
        """
        clean = copy.copy(record)
        self.redaction.filter(record=clean)
        data = _record_data(record=clean)
        if clean.exc_info:
            data["exception"] = _redact(value=self.formatException(ei=clean.exc_info))
        if clean.stack_info:
            data["stack"] = _redact(value=clean.stack_info)
        if self.readable:
            line = f"{clean.levelname} {clean.name}: {data['message']}"
            return line + (f"\n{data['exception']}" if "exception" in data else "")
        return json.dumps(data, ensure_ascii=False, default=str)


class PrivateRotatingFileHandler(RotatingFileHandler):
    """Open private logs without target symlinks; XDG parent symlinks are allowed."""

    def _open(self) -> TextIOWrapper:
        path = Path(self.baseFilename)
        if path.is_symlink():
            raise ValueError("Log file must not be a symlink")
        fd = os.open(
            path=path,
            flags=os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
            mode=PRIVATE_FILE_MODE,
        )
        try:
            os.fchmod(fd=fd, mode=PRIVATE_FILE_MODE)
            return os.fdopen(fd, mode="a", encoding="utf-8")
        except BaseException:
            os.close(fd)
            raise

    def doRollover(self) -> None:
        """Rotate private files while retaining the configured backup count."""
        self.secure_backups()
        super().doRollover()
        self.secure_backups()

    def secure_backups(self) -> None:
        """Secure existing backups and refuse symlinks before rotation."""
        for index in range(1, self.backupCount + 1):
            path = Path(f"{self.baseFilename}.{index}")
            if path.is_symlink():
                raise ValueError("Log backup must not be a symlink")
            if path.exists():
                os.chmod(path=path, mode=PRIVATE_FILE_MODE, follow_symlinks=False)


def _create_file_handler(paths: UserPaths) -> logging.Handler:
    ensure_private_dir(path=paths.state_dir)
    file_handler = PrivateRotatingFileHandler(
        filename=paths.state_dir / "wimm.log",
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    try:
        file_handler.secure_backups()
    except BaseException:
        file_handler.close()
        raise
    file_handler.setFormatter(fmt=LogFormatter(readable=False))
    return file_handler


def _create_handlers(paths: UserPaths) -> tuple[list[logging.Handler], str | None]:
    terminal = logging.StreamHandler(stream=sys.stderr)
    terminal.setFormatter(fmt=LogFormatter(readable=sys.stderr.isatty()))
    try:
        return [terminal, _create_file_handler(paths=paths)], None
    except (OSError, ValueError) as error:
        return [terminal], f"Cannot open private log; using stderr only: {error}"


def setup_logging(paths: UserPaths, level_name: str | None = None) -> None:
    """Configure idempotent private file and stderr logging.

    Parameters
    ----------
    paths : UserPaths
        State directory holding the rotating log.
    level_name : str, optional
        Override WIMM_LOG_LEVEL; absent values default to INFO.
    """
    requested = level_name if level_name is not None else os.environ.get("WIMM_LOG_LEVEL", "INFO")
    level = logging.getLevelNamesMapping().get(requested.upper())
    handlers, failure = _create_handlers(paths=paths)
    root = logging.getLogger()
    for handler in root.handlers[:]:
        if getattr(handler, OWNED_HANDLER, False):
            root.removeHandler(hdlr=handler)
            handler.close()
    for handler in handlers:
        setattr(handler, OWNED_HANDLER, True)
        root.addHandler(hdlr=handler)
    root.setLevel(level=logging.INFO if level is None else level)
    if level is None:
        logging.getLogger(__name__).warning("Invalid WIMM_LOG_LEVEL; using INFO")
    if failure is not None:
        logging.getLogger(__name__).warning(failure)
