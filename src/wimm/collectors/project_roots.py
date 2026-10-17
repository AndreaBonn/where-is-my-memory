from collections.abc import Callable
from pathlib import Path

from wimm.core.constants import PROJECT_ROOT_MARKERS


class ProjectRootResolver:
    """Resolve project roots with a cache that lives as long as the resolver.

    Create one resolver per sampling cycle: markers created while the app is
    resident (for example by `git init`) are then seen on the next cycle.

    Parameters
    ----------
    is_marker : Callable[[Path], bool]
        Injected marker existence predicate.
    home : Path | None
        Home directory; the walk stops below it. Defaults to the current home.
    """

    def __init__(self, is_marker: Callable[[Path], bool], home: Path | None = None) -> None:
        self._is_marker = is_marker
        self._home = Path.home() if home is None else home
        self._cache: dict[Path, Path] = {}

    def resolve(self, cwd: Path) -> Path:
        """Find the nearest ancestor holding a project marker.

        The home directory is never a candidate, so a dotfiles repository in
        `~` cannot merge unrelated processes.

        Parameters
        ----------
        cwd : Path
            Absolute working directory.

        Returns
        -------
        Path
            Nearest project directory, or the original working directory.
        """
        if cwd not in self._cache:
            self._cache[cwd] = self._walk(cwd=cwd)
        return self._cache[cwd]

    def _walk(self, cwd: Path) -> Path:
        inside_home = cwd.is_relative_to(self._home)
        for candidate in (cwd, *cwd.parents):
            if inside_home and candidate == self._home:
                break
            if any(self._is_marker(candidate / marker) for marker in PROJECT_ROOT_MARKERS):
                return candidate
        return cwd
