"""Pure rules deciding whether a folder is a rebuildable development directory.

A name alone is not enough: ``target`` or ``vendor`` can hold hand-written data. The
caller reads the project folder and passes what it saw; nothing here touches the disk.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

CACHEDIR_TAG = "CACHEDIR.TAG"
VENV_MARKER = "pyvenv.cfg"
GITIGNORE_COMMENT = "#"
GITIGNORE_NEGATION = "!"
GITIGNORE_SEPARATOR = "/"

# name -> marker files of which at least one must sit next to the folder. An empty tuple
# means the name alone is enough. ``dist`` and any unlisted name never qualify.
MARKERS_BY_NAME: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "node_modules": (),
        ".venv": (),
        "venv": (),
        ".tox": ("tox.ini", "pyproject.toml", "setup.cfg"),
        "target": ("Cargo.toml", "pom.xml"),
        ".gradle": ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"),
        "build": ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"),
        ".next": ("package.json",),
        ".nuxt": ("package.json",),
        "vendor": ("composer.json",),
    }
)
# Virtual environments are recognised by the file inside the folder, not by a sibling.
VENV_NAMES = frozenset({".venv", "venv"})
# Names too generic to trust on a sibling marker alone: they need a second signal.
NEEDS_SECOND_SIGNAL = frozenset({"target", "vendor", "build", ".next", ".nuxt", ".gradle"})


@dataclass(frozen=True)
class DevdirContext:
    """What the caller observed around a candidate folder.

    Attributes
    ----------
    parent_entries : frozenset[str]
        Names of the entries in the folder that contains the candidate.
    has_cachedir_tag : bool
        Whether the candidate holds a ``CACHEDIR.TAG`` file.
    has_pyvenv_cfg : bool
        Whether the candidate holds a ``pyvenv.cfg`` file.
    gitignore_text : str
        Content of the parent's ``.gitignore``, empty when absent.
    parent_is_home : bool
        Whether the parent is the user's home directory.
    """

    parent_entries: frozenset[str]
    has_cachedir_tag: bool = False
    has_pyvenv_cfg: bool = False
    gitignore_text: str = ""
    parent_is_home: bool = False


def gitignore_names(*, text: str) -> frozenset[str]:
    """Return the bare names a ``.gitignore`` lists; a later negation removes a name."""
    names = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(GITIGNORE_COMMENT):
            continue
        # Like git, the last matching line wins: `!target` after `target/` un-ignores it.
        if line.startswith(GITIGNORE_NEGATION):
            names.discard(line[len(GITIGNORE_NEGATION) :].strip(GITIGNORE_SEPARATOR))
            continue
        names.add(line.strip(GITIGNORE_SEPARATOR))
    return frozenset(names)


def _has_marker(*, markers: Iterable[str], entries: frozenset[str]) -> bool:
    return any(marker in entries for marker in markers)


def classify_devdir(*, name: str, context: DevdirContext) -> bool:
    """Tell whether the folder ``name`` is a safe-to-rebuild development directory.

    Parameters
    ----------
    name : str
        Folder name (not a path).
    context : DevdirContext
        What was observed around the folder.

    Returns
    -------
    bool
        ``True`` only when the name is listed and every condition for it holds. A project
        sitting directly in the home directory is always refused.
    """
    if name not in MARKERS_BY_NAME or context.parent_is_home:
        return False
    if name in VENV_NAMES:
        return context.has_pyvenv_cfg
    markers = MARKERS_BY_NAME[name]
    if markers and not _has_marker(markers=markers, entries=context.parent_entries):
        return False
    if name not in NEEDS_SECOND_SIGNAL:
        return True
    return context.has_cachedir_tag or name in gitignore_names(text=context.gitignore_text)


def rebuild_marker(*, name: str, parent_entries: frozenset[str]) -> str:
    """Return the first marker of ``name`` found next to it, or ``""`` when none applies.

    The marker tells which tool rebuilds the folder: ``target`` beside ``pom.xml`` is a
    Maven build, beside ``Cargo.toml`` a Cargo one. Table order breaks a tie.
    """
    markers = MARKERS_BY_NAME.get(name, ())
    return next((marker for marker in markers if marker in parent_entries), "")
