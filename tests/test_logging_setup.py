import io
import json
import logging
import os
import stat
import sys
from collections.abc import Iterator
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from wimm.logging_setup import LogFormatter, PrivateRotatingFileHandler, setup_logging
from wimm.paths import UserPaths


@pytest.fixture
def log_paths(tmp_path: Path) -> Iterator[UserPaths]:
    root = logging.getLogger()
    previous_handlers, previous_level = root.handlers[:], root.level
    root.handlers = []
    yield UserPaths(
        config_dir=tmp_path / "config", state_dir=tmp_path / "state", cache_dir=tmp_path / "cache"
    )
    for handler in root.handlers:
        handler.close()
    root.handlers = previous_handlers
    root.setLevel(level=previous_level)


def read_records(paths: UserPaths) -> list[dict[str, object]]:
    return [json.loads(line) for line in (paths.state_dir / "wimm.log").read_text().splitlines()]


def test_json_logging_and_idempotence(log_paths: UserPaths) -> None:
    setup_logging(paths=log_paths, level_name="INFO")
    setup_logging(paths=log_paths, level_name="INFO")
    logging.getLogger("test.wimm").info("Normal message", extra={"pid": 42})
    records = read_records(paths=log_paths)
    assert len(records) == 1
    assert records[0]["message"] == "Normal message"
    assert records[0]["pid"] == 42
    assert records[0]["logger"] == "test.wimm"
    assert records[0]["level"] == "INFO"
    assert records[0]["timestamp"]
    assert stat.S_IMODE(log_paths.state_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((log_paths.state_dir / "wimm.log").stat().st_mode) == 0o600
    assert sum(bool(getattr(h, "_wimm_handler", False)) for h in logging.getLogger().handlers) == 2


@pytest.mark.parametrize(
    "secret",
    [
        "--token=hidden",
        "--password hidden",
        "--secret=hidden",
        "API_KEY=hidden",
        "ACCESS_TOKEN=hidden",
        "TOKEN=hidden",
        '--token="hidden value"',
        "PASSWORD=hidden",
    ],
)
def test_secrets_redacted_in_message_and_extras(log_paths: UserPaths, secret: str) -> None:
    setup_logging(paths=log_paths, level_name="DEBUG")
    logging.getLogger("test").debug(
        "arg %s", secret, extra={"detail": [secret], "API_KEY": "hidden"}
    )
    record = read_records(paths=log_paths)[0]
    assert record["message"] == "arg " + secret.split("hidden")[0].rstrip('"') + "[REDACTED]"
    assert record["API_KEY"] == "[REDACTED]"
    assert "hidden" not in json.dumps(record)
    logging.getLogger("test").debug("ordinary text", extra={"detail": ["normal"]})
    normal = read_records(paths=log_paths)[1]
    assert normal["message"] == "ordinary text"
    assert normal["detail"] == ["normal"]


def test_rotation_is_private(log_paths: UserPaths) -> None:
    setup_logging(paths=log_paths, level_name="INFO")
    handler = next(h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler))
    assert handler.maxBytes == 1024 * 1024
    assert handler.backupCount == 3
    handler.maxBytes = 200
    for index in range(8):
        logging.getLogger("test").info("record %s %s", index, "x" * 100)
    files = sorted(log_paths.state_dir.glob(pattern="wimm.log*"))
    assert len(files) == 4
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in files)
    assert read_records(paths=log_paths)[-1]["message"] == "record 7 " + "x" * 100


def test_env_and_invalid_level(log_paths: UserPaths, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(name="WIMM_LOG_LEVEL", value="DEBUG")
    setup_logging(paths=log_paths)
    logging.getLogger("test").debug("debug visible")
    assert read_records(paths=log_paths)[0]["message"] == "debug visible"
    setup_logging(paths=log_paths, level_name="bad")
    records = read_records(paths=log_paths)
    assert records[-1]["level"] == "WARNING"
    assert logging.getLogger().level == logging.INFO


def test_tty_and_exception_redaction(log_paths: UserPaths, monkeypatch: pytest.MonkeyPatch) -> None:
    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    terminal = Terminal()
    monkeypatch.setattr(target=sys, name="stderr", value=terminal)
    setup_logging(paths=log_paths, level_name="DEBUG")
    try:
        raise ValueError("--token=hidden")
    except ValueError:
        logging.getLogger("test").exception("failed", extra={"cmdline": "private arguments"})
    record = read_records(paths=log_paths)[0]
    assert "[REDACTED]" in str(record["exception"])
    assert "hidden" not in terminal.getvalue()
    assert "ERROR test: failed" in terminal.getvalue()
    assert "cmdline" not in record
    logging.getLogger("test").debug("details", extra={"cmdline": "visible --token=hidden"})
    assert read_records(paths=log_paths)[1]["cmdline"] == "visible --token=[REDACTED]"


def test_nested_values_stack_and_normal_assignments(log_paths: UserPaths) -> None:
    setup_logging(paths=log_paths, level_name="DEBUG")
    detail = {"nested": {"TOKEN": "hidden", "normal": 42}, "normal": "keyboard=visible"}
    logging.getLogger("test").debug("keyboard=visible", extra={"detail": detail}, stack_info=True)
    record = read_records(paths=log_paths)[0]
    assert record["message"] == "keyboard=visible"
    assert record["detail"] == {
        "nested": {"TOKEN": "[REDACTED]", "normal": 42},
        "normal": "keyboard=visible",
    }
    assert "Stack" in str(record["stack"])
    assert detail["nested"] == {"TOKEN": "hidden", "normal": 42}


def test_existing_backups_secured_and_symlinks_rejected(
    log_paths: UserPaths, tmp_path: Path
) -> None:
    log_paths.state_dir.mkdir(exist_ok=True)
    backup = log_paths.state_dir / "wimm.log.1"
    backup.write_text("old record\n")
    backup.chmod(mode=0o644)
    setup_logging(paths=log_paths)
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    target = tmp_path / "target"
    target.write_text("original")
    backup.unlink()
    backup.symlink_to(target=target)
    setup_logging(paths=log_paths)
    assert sum(bool(getattr(h, "_wimm_handler", False)) for h in logging.getLogger().handlers) == 1
    assert target.read_text() == "original"


def test_log_symlink_falls_back_to_stderr(
    log_paths: UserPaths, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log_paths.state_dir.mkdir(exist_ok=True)
    target = tmp_path / "target"
    target.write_text("original")
    (log_paths.state_dir / "wimm.log").symlink_to(target=target)
    setup_logging(paths=log_paths)
    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert len(records) == 1
    assert records[0]["level"] == "WARNING"
    assert sum(bool(getattr(h, "_wimm_handler", False)) for h in logging.getLogger().handlers) == 1
    logging.getLogger("test").info("stderr still works")
    assert json.loads(capsys.readouterr().err)["message"] == "stderr still works"
    assert target.read_text() == "original"
    (log_paths.state_dir / "wimm.log").unlink()
    setup_logging(paths=log_paths)
    logging.getLogger("test").info("working")
    assert read_records(paths=log_paths)[0]["message"] == "working"


def test_permission_failure_closes_descriptor(
    log_paths: UserPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    descriptors: list[int] = []
    log_paths.state_dir.mkdir(exist_ok=True)

    def fail_chmod(fd: int, mode: int) -> None:
        descriptors.append(fd)
        raise PermissionError("cannot secure log")

    monkeypatch.setattr(target=os, name="fchmod", value=fail_chmod)
    with pytest.raises(PermissionError, match="cannot secure log"):
        PrivateRotatingFileHandler(filename=log_paths.state_dir / "wimm.log")
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
    monkeypatch.undo()
    setup_logging(paths=log_paths)
    logging.getLogger("test").info("working")
    assert read_records(paths=log_paths)[0]["message"] == "working"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Authorization: Bearer abc123", "Authorization: Bearer [REDACTED]"),
        ("Authorization: Basic dTpw", "Authorization: Basic [REDACTED]"),
        ("https://u:p@host/x", "https://u:[REDACTED]@host/x"),
        ("apikey=abc", "apikey=[REDACTED]"),
        ("password: abc", "password: [REDACTED]"),
        ("token = abc", "token = [REDACTED]"),
        ("token : abc", "token : [REDACTED]"),
        ("Cookie: sid=abc", "Cookie: [REDACTED]"),
        ("Set-Cookie: sid=abc; HttpOnly", "Set-Cookie: [REDACTED]"),
        ("{'password': 'abc'}", "{'password': [REDACTED]}"),
        ("keyboard", "keyboard"),
        ("tokenizer started", "tokenizer started"),
        ("port: 8000", "port: 8000"),
        ("https://host/x", "https://host/x"),
    ],
)
def test_redaction_formats(text: str, expected: str) -> None:
    record = logging.makeLogRecord({"msg": text, "detail": text, "levelno": logging.INFO})
    result = json.loads(LogFormatter(readable=False).format(record=record))
    assert result["message"] == expected
    assert result["detail"] == expected


def test_extra_object_string_is_redacted() -> None:
    class Detail:
        def __str__(self) -> str:
            return "token=zzz"

    record = logging.makeLogRecord({"msg": "event", "detail": Detail(), "levelno": logging.INFO})
    result = json.loads(LogFormatter(readable=False).format(record=record))
    assert result["message"] == "event"
    assert result["detail"] == "token=[REDACTED]"


def test_log_open_does_not_follow_symlink_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.write_text("original")
    log = tmp_path / "wimm.log"
    original_open = os.open

    def race_open(path: Path, flags: int, mode: int) -> int:
        log.symlink_to(target=target)
        return original_open(path=path, flags=flags, mode=mode)

    monkeypatch.setattr(target=os, name="open", value=race_open)
    with pytest.raises(OSError):
        PrivateRotatingFileHandler(filename=log)
    assert target.read_text() == "original"
