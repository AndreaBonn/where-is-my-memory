from collections.abc import Callable, Sequence
from pathlib import Path

from wimm.collectors.root_candidates import detect_dev_roots
from wimm.collectors.root_facts import read_root_facts
from wimm.core.root_policy import RootFacts, RootRefusal, root_refusal


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
    """Decode user roots: absolute and not an existing non-directory.

    Whether a root is allowed is the policy's call (``refused_roots``, ADR-007). A root
    that is missing or refused is kept so the user sees it flagged with its reason
    instead of losing the whole list.
    """
    if not value:
        raise ValueError("Expected at least one directory")
    roots = tuple(expand_root(value=item, home=home) for item in value)
    if any(_is_not_directory(root) for root in roots):
        raise ValueError("Expected existing directories or paths not yet created")
    return roots


def _is_not_directory(root: Path) -> bool:
    return root.exists() and not root.is_dir()


def missing_roots(roots: Sequence[Path]) -> tuple[Path, ...]:
    """Return the roots that are not directories right now, in their original order."""
    return tuple(root for root in roots if not root.is_dir())


def refused_roots(
    *,
    roots: Sequence[Path],
    home: Path,
    read_facts: Callable[..., RootFacts | None] = read_root_facts,
) -> tuple[tuple[Path, RootRefusal], ...]:
    """Return ``(root, reason)`` for each root the ADR-007 policy refuses, in original order.

    A root whose facts cannot be read (missing, unreadable) is not listed: it shows as
    missing. Callers that act on a root must treat unreadable facts as a refusal.
    """
    refused = []
    for root in roots:
        facts = read_facts(path=root)
        reason = None if facts is None else root_refusal(facts=facts, home=home.resolve())
        if reason is not None:
            refused.append((root, reason))
    return tuple(refused)


def admitted_roots(
    *,
    roots: Sequence[Path],
    home: Path,
    read_facts: Callable[..., RootFacts | None] = read_root_facts,
) -> tuple[Path, ...]:
    """Return the roots the scan may walk: facts readable now and no ADR-007 refusal.

    Unreadable facts (a missing root, a denied stat, no mountinfo) are never admitted, so a
    network or read-only mount cannot pass for lack of evidence.
    """
    real_home = home.resolve()
    admitted = []
    for root in roots:
        facts = read_facts(path=root)
        if facts is not None and root_refusal(facts=facts, home=real_home) is None:
            admitted.append(root)
    return tuple(admitted)


def validate_roots(roots: object) -> None:
    """Raise ``ValueError`` unless ``roots`` is a tuple of absolute paths.

    The tuple may be empty: that is what detection yields on a home without projects.
    A list the user saves is held to ``decode_roots``, which still requires one entry.
    """
    if type(roots) is not tuple or any(
        not isinstance(item, Path) or not item.is_absolute() for item in roots
    ):
        raise ValueError("devdirs_roots must be a tuple of absolute paths")
