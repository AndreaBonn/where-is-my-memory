from collections.abc import Callable, Iterable

DEV_ROOT_CANDIDATES = (
    "~/code",
    "~/projects",
    "~/src",
    "~/dev",
    "~/git",
    "~/workspace",
    "~/Documents",
    "~/Documenti",
)


def select_dev_roots(candidates: Iterable[str], has_repo: Callable[[str], bool]) -> tuple[str, ...]:
    """Keep the candidates that contain a repository, in first-seen order.

    Parameters
    ----------
    candidates : Iterable[str]
        Real paths, already resolved by the caller; duplicates are dropped.
    has_repo : Callable[[str], bool]
        Probe supplied by the caller; each distinct candidate is probed once.
    """
    seen: set[str] = set()
    selected: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if has_repo(candidate):
            selected.append(candidate)
    return tuple(selected)
