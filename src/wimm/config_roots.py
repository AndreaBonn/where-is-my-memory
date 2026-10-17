from collections.abc import Sequence
from pathlib import Path

from wimm.collectors.root_candidates import detect_dev_roots


def expand_root(value: str, home: Path) -> Path:
    """Return the resolved absolute path for a ``~``-relative or absolute root."""
    path = home / value.removeprefix("~/") if value.startswith("~/") else Path(value)
    path = home if value == "~" else path
    if not value or not path.is_absolute():
        raise ValueError("Expected an absolute directory path")
    return path.resolve()


def default_roots(home: Path) -> tuple[Path, ...]:
    """Return the project roots detected under ``home``; empty when none is found."""
    return detect_dev_roots(home=home)


def decode_roots(value: Sequence[str], home: Path) -> tuple[Path, ...]:
    """Decode user roots: absolute, within ``home``, and not an existing non-directory.

    A root that no longer exists is kept so the user sees it flagged (``missing_roots``)
    instead of losing the whole list.
    """
    if not value:
        raise ValueError("Expected at least one directory")
    roots = tuple(expand_root(value=item, home=home) for item in value)
    if any(not root.is_relative_to(home.resolve()) or _is_not_directory(root) for root in roots):
        raise ValueError("Expected directories within home")
    return roots


def _is_not_directory(root: Path) -> bool:
    return root.exists() and not root.is_dir()


def missing_roots(roots: Sequence[Path]) -> tuple[Path, ...]:
    """Return the roots that are not directories right now, in their original order."""
    return tuple(root for root in roots if not root.is_dir())


def validate_roots(roots: object) -> None:
    """Raise ``ValueError`` unless ``roots`` is a tuple of absolute paths.

    The tuple may be empty: that is what detection yields on a home without projects.
    A list the user saves is held to ``decode_roots``, which still requires one entry.
    """
    if type(roots) is not tuple or any(
        not isinstance(item, Path) or not item.is_absolute() for item in roots
    ):
        raise ValueError("devdirs_roots must be a tuple of absolute paths")
