from collections.abc import Sequence
from pathlib import Path

from wimm.core import constants as c


def expand_root(value: str, home: Path) -> Path:
    """Return the resolved absolute path for a ``~``-relative or absolute root."""
    path = home / value.removeprefix("~/") if value.startswith("~/") else Path(value)
    path = home if value == "~" else path
    if not value or not path.is_absolute():
        raise ValueError("Expected an absolute directory path")
    return path.resolve()


def default_roots(home: Path) -> tuple[Path, ...]:
    """Return the built-in project roots expanded against ``home``."""
    return tuple(expand_root(value=value, home=home) for value in c.DEVDIRS_ROOTS)


def decode_roots(value: Sequence[str], home: Path) -> tuple[Path, ...]:
    """Decode user roots; they must be existing directories within ``home``."""
    if not value:
        raise ValueError("Expected at least one directory")
    roots = tuple(expand_root(value=item, home=home) for item in value)
    if any(not root.is_relative_to(home.resolve()) or not root.is_dir() for root in roots):
        raise ValueError("Expected existing directories within home")
    return roots


def validate_roots(roots: object) -> None:
    """Raise ``ValueError`` unless ``roots`` is a nonempty tuple of absolute paths."""
    if (
        type(roots) is not tuple
        or not roots
        or any(not isinstance(item, Path) or not item.is_absolute() for item in roots)
    ):
        raise ValueError("devdirs_roots must be a tuple of absolute paths")
