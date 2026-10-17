import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from itertools import chain
from pathlib import PurePosixPath

from wimm.i18n import N_, _
from wimm.model.enums import Category, GroupId
from wimm.model.raw import RawContainer, RawProcess

from .categorize import CategoryDecision

COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_WORKDIR_LABEL = "com.docker.compose.project.working_dir"
COMPOSE_KEY_PREFIX = "compose:"
CONTAINER_KEY_PREFIX = "container:"
KEY_CLASS_COMPOSE = "compose"
KEY_CLASS_CONTAINER = "container"
KEY_CLASS_FOLDER = "folder"
KEY_CLASS_APP = "app"
KEY_CLASS_ROOT_PROCESS = "root_process"
KEY_CLASS_PROTECTED = "protected"
AUDIO_PROCESS_NAMES = frozenset({"pipewire", "pipewire-pulse", "wireplumber", "pulseaudio"})
ROOT_UID = 0
# RF-07 labels of the System view: (key, display name to translate with ``_`` where shown).
# The key is the identity (it feeds the group id); only the name is user text.
LABEL_AUDIO = ("session-audio", N_("Audio"))
LABEL_SESSION = ("session-gnome", N_("Sessione GNOME"))
LABEL_OTHER_USERS = ("other-users", N_("Altri utenti"))
LABEL_SYSTEM = ("system-services", N_("Servizi di sistema"))
LABEL_SELF = ("self", "where-is-my-memory")
# Apps that already contain their children: an integrated shell is not a terminal one.
SHELL_EXEMPT_CATEGORIES = frozenset({Category.DESKTOP_APP, Category.BROWSER})
ID_PREFIX = "g_"
ID_HEX_LENGTH = 12
ID_SEPARATOR = "\x1f"
KEY_SEPARATOR = "|"
FILESYSTEM_ROOT = "/"
PROTECTED_CATEGORIES = frozenset({Category.SYSTEM, Category.SESSION, Category.SELF})
APP_CATEGORIES = frozenset({Category.BROWSER, Category.DESKTOP_APP, Category.TERMINAL})
DEV_CATEGORIES = frozenset({Category.DEV_SERVER, Category.DEV_PROCESS, Category.AI_CLI})
# Display category of a folder group holding several launch kinds: the most
# actionable one wins.
DEV_PRIORITY = (Category.DEV_SERVER, Category.AI_CLI, Category.DEV_PROCESS)
DEV_BUCKET = Category.DEV_PROCESS

Pair = tuple[RawProcess, CategoryDecision]


def stable_group_id(*, key_class: str, key: str) -> GroupId:
    """Derive a group id from key class and key, never from a PID (SPECIFICHE 5.5).

    The resolved category is deliberately not an input: it changes when a dev
    server starts or a compose project fuses with processes, the id must not.

    Parameters
    ----------
    key_class : str
        Kind of key: compose, container, folder, app, root_process or protected.
    key : str
        Readable grouping key; must not contain PIDs.
    """
    digest = hashlib.sha256(f"{key_class}{ID_SEPARATOR}{key}".encode()).hexdigest()
    return GroupId(ID_PREFIX + digest[:ID_HEX_LENGTH])


def paths_related(*, left: str, right: str) -> bool:
    """Tell whether two paths are equal or one is an ancestor of the other.

    The comparison is per path component: ``/a/b`` is not an ancestor of ``/a/bc``.
    """
    first, second = PurePosixPath(left), PurePosixPath(right)
    return first.is_relative_to(second) or second.is_relative_to(first)


def effective_root(
    *, cwd: str | None, project_root_by_cwd: Mapping[str, str], own_home: str
) -> str | None:
    """Project root of a working directory; the home and ``/`` are never roots.

    A cwd missing from the mapping is its own root (no marker found, 5.5 rule 3).
    """
    if cwd is None:
        return None
    root = project_root_by_cwd.get(cwd, cwd)
    return None if root in {own_home, FILESYSTEM_ROOT} else root


def app_identity(*, proc: RawProcess, decision: CategoryDecision) -> str:
    """Stable identity of an app group: appid, else scope, else process name.

    A child process inherits appid and scope of its app ancestor in the decision,
    so children land in the ancestor's group without walking the process tree.
    """
    return decision.appid or decision.scope or proc.name


def nearest_terminal(*, proc: RawProcess, by_pid: Mapping[int, Pair]) -> Pair | None:
    """Closest ancestor categorized as TERMINAL, or None."""
    current = proc
    for _hop in by_pid:
        parent = by_pid.get(current.ppid)
        if parent is None:
            return None
        if parent[1].category is Category.TERMINAL:
            return parent
        current = parent[0]
    return None


def root_process(*, proc: RawProcess, members: Mapping[int, RawProcess]) -> RawProcess:
    """Topmost ancestor still inside ``members`` (rule 6: group per root process)."""
    current = proc
    for _hop in members:
        parent = members.get(current.ppid)
        if parent is None:
            return current
        current = parent
    return current


@dataclass(frozen=True, slots=True)
class Part:
    """A group under construction: members, key and the facts of its explanation."""

    category: Category
    key_class: str
    key: str
    name: str
    pids: tuple[int, ...] = ()
    container_ids: tuple[str, ...] = ()
    compose_project: str | None = None
    working_dir: str | None = None
    root: str | None = None
    ports: tuple[int, ...] = ()
    lead_process: str | None = None
    process_names: tuple[str, ...] = ()


def compose_part(*, project: str, members: list[RawContainer]) -> Part:
    """Compose group: its working dir is the first one labelled by any container."""
    workdirs = (dict(item.labels).get(COMPOSE_WORKDIR_LABEL) for item in members)
    return Part(
        category=Category.CONTAINER,
        key_class=KEY_CLASS_COMPOSE,
        key=COMPOSE_KEY_PREFIX + project,
        name=project,
        container_ids=tuple(item.id for item in members),
        compose_project=project,
        working_dir=next((workdir for workdir in workdirs if workdir), None),
    )


def container_parts(*, containers: tuple[RawContainer, ...]) -> list[Part]:
    by_project: dict[str, list[RawContainer]] = {}
    parts = []
    for item in sorted(containers, key=lambda container: container.name):
        project = dict(item.labels).get(COMPOSE_PROJECT_LABEL)
        if project:
            by_project.setdefault(project, []).append(item)
            continue
        parts.append(
            Part(
                category=Category.CONTAINER,
                key_class=KEY_CLASS_CONTAINER,
                key=CONTAINER_KEY_PREFIX + item.name,
                name=item.name,
                container_ids=(item.id,),
            )
        )
    parts.extend(
        compose_part(project=name, members=members) for name, members in by_project.items()
    )
    return parts


def matching_compose(*, part: Part, composes: list[Part], own_home: str) -> Part | None:
    """Compose group a folder group fuses into: the most specific related working dir.

    The home and ``/`` are never working dirs that fuse (same rule as for roots);
    ties on depth resolve by key, so the result does not depend on input order.
    """
    if part.root is None:
        return None
    root = part.root
    candidates = [
        (len(PurePosixPath(workdir).parts), compose)
        for compose in composes
        if (workdir := compose.working_dir)
        and workdir not in {own_home, FILESYSTEM_ROOT}
        and paths_related(left=root, right=workdir)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda item: (-item[0], item[1].key))[1]


def merge_project(*, compose: Part, absorbed: list[Part]) -> Part:
    """Fuse folder groups into their compose group, which becomes a PROJECT.

    The compose key class and key are kept, so the group id does not change.
    """
    ordered = sorted(absorbed, key=lambda part: part.key)
    pids = sorted(chain.from_iterable(part.pids for part in ordered))
    ports = sorted(set(chain.from_iterable(part.ports for part in ordered)))
    return replace(
        compose,
        category=Category.PROJECT,
        pids=tuple(pids),
        ports=tuple(ports),
        lead_process=ordered[0].lead_process,
    )


def fuse(*, containers: list[Part], processes: list[Part], own_home: str) -> list[Part]:
    """Rule 4: absorb every folder group related to a compose working dir."""
    absorbed: dict[str, list[Part]] = {}
    result = []
    for part in processes:
        target = matching_compose(part=part, composes=containers, own_home=own_home)
        if target is None:
            result.append(part)
        else:
            absorbed.setdefault(target.key, []).append(part)
    for compose in containers:
        extra = absorbed.get(compose.key)
        result.append(compose if extra is None else merge_project(compose=compose, absorbed=extra))
    return result


def protected_label(*, proc: RawProcess, category: Category, own_uid: int) -> tuple[str, str]:
    """RF-07 (key, name) of the System-view group a protected process belongs to."""
    if category is Category.SELF:
        return LABEL_SELF
    if category is Category.SESSION:
        key, name = LABEL_AUDIO if proc.name in AUDIO_PROCESS_NAMES else LABEL_SESSION
    else:
        key, name = LABEL_SYSTEM if proc.uid in {ROOT_UID, own_uid} else LABEL_OTHER_USERS
    return key, _(name)
