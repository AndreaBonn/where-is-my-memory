import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from wimm.model.snapshot import Snapshot
from wimm.paths import ensure_private_dir, write_private_atomic

LOGGER = logging.getLogger(__name__)
DEFAULT_WIDTH = 960
DEFAULT_HEIGHT = 720
MIN_WIDTH = 360
MIN_HEIGHT = 294
MAX_WINDOW_SIZE = 16384
STATE_FILE = "window.json"


class SnapshotSource(Protocol):
    """What the window needs from the service; ``AppService`` satisfies it."""

    consecutive_failures: int

    def snapshot(self) -> Snapshot | None: ...

    def connect(self, detailed_signal: str, handler: Callable[..., Any], *args: Any) -> int: ...

    def disconnect(self, handler_id: int) -> None: ...


def _clamp(*, value: int, bounds: tuple[int, int], name: str, path: Path) -> int:
    low, high = bounds
    if value > high:
        LOGGER.warning("Ignoring oversized %s %d in %s, using %d", name, value, path, high)
        return high
    return max(value, low)


def load_window_size(*, path: Path) -> tuple[int, int]:
    """Read the remembered size: bad data gives the default, out-of-range values are clamped."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        width, height = data["width"], data["height"]
    except FileNotFoundError:
        return DEFAULT_WIDTH, DEFAULT_HEIGHT
    except (OSError, ValueError, KeyError, TypeError):
        LOGGER.warning("Ignoring unreadable window state %s", path)
        return DEFAULT_WIDTH, DEFAULT_HEIGHT
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (width, height)):
        return DEFAULT_WIDTH, DEFAULT_HEIGHT
    return (
        _clamp(value=width, bounds=(MIN_WIDTH, MAX_WINDOW_SIZE), name="width", path=path),
        _clamp(value=height, bounds=(MIN_HEIGHT, MAX_WINDOW_SIZE), name="height", path=path),
    )


def save_window_size(*, path: Path, width: int, height: int) -> None:
    """Persist the size atomically with private permissions."""
    try:
        ensure_private_dir(path.parent)
        write_private_atomic(path, json.dumps({"width": width, "height": height}).encode())
    except OSError:
        LOGGER.warning("Could not save window state to %s", path, exc_info=True)
