"""Grouping of processes and containers (SPECIFICHE 5.5), pure and PID-free.

A group id hashes (key class, key), where the key class is one of compose,
container, folder, app, root_process, protected. The resolved category is not an
input: a folder group stays the same group when a dev server starts, and a
compose group keeps its id when it fuses with processes into a PROJECT. A key
text shared by two classes still yields different ids.

Protected processes (SYSTEM, SESSION, SELF) form the fixed RF-07 groups of the
System view (audio, GNOME session, other users, system services, this app).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from itertools import chain
from pathlib import PurePosixPath

from wimm.model.enums import Category, GroupId
from wimm.model.raw import RawContainer, RawProcess

from .categorize import is_terminal_shell
from .grouping_keys import (
    APP_CATEGORIES,
    DEV_BUCKET,
    DEV_CATEGORIES,
    DEV_PRIORITY,
    KEY_CLASS_APP,
    KEY_CLASS_FOLDER,
    KEY_CLASS_PROTECTED,
    KEY_CLASS_ROOT_PROCESS,
    KEY_CLASS_TOOL,
    KEY_SEPARATOR,
    PROTECTED_CATEGORIES,
    SHELL_EXEMPT_CATEGORIES,
    Pair,
    Part,
    app_identity,
    container_parts,
    effective_root,
    fuse,
    nearest_terminal,
    protected_label,
    root_process,
    scope_shared_app_keys,
    stable_group_id,
    tool_group,
)
from .text import GroupFacts, explain_group

UNROOTED = ""  # placeholder key: resolved by root process in _resolve_unrooted


@dataclass(frozen=True, slots=True)
class GroupingInput:
    """Everything grouping needs, already collected (no I/O here).

    ``pairs`` excludes processes dropped by categorization (Docker scope).
    A cwd absent from ``project_root_by_cwd`` is its own root; a ``None`` cwd
    has none and is grouped by root process.
    """

    pairs: tuple[Pair, ...]
    containers: tuple[RawContainer, ...]
    project_root_by_cwd: Mapping[str, str]
    desktop_name_by_appid: Mapping[str, str]
    own_home: str
    own_uid: int
    listen_ports_by_pid: Mapping[int, frozenset[int]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GroupDraft:
    """A group before memory, activity and risk are attached by the assembler."""

    id: GroupId
    key: str
    name: str
    category: Category
    process_pids: tuple[int, ...]
    container_ids: tuple[str, ...]
    compose_project: str | None
    working_dir: str | None
    explanation: str


@dataclass(frozen=True, slots=True)
class _Placement:
    proc: RawProcess
    member: Category
    bucket: Category
    key_class: str
    key: str
    name: str
    root: str | None = None
    tool_reason: str | None = None


def _place_app(
    *, pair: Pair, category: Category, by_pid: Mapping[int, Pair], names: Mapping[str, str]
) -> _Placement:
    proc, decision = pair
    if is_terminal_shell(proc=proc) and category not in SHELL_EXEMPT_CATEGORIES:
        terminal = nearest_terminal(proc=proc, by_pid=by_pid)
        if terminal is None:
            return _Placement(
                proc=proc,
                member=Category.TERMINAL,
                bucket=Category.TERMINAL,
                key_class=KEY_CLASS_ROOT_PROCESS,
                key=UNROOTED,
                name="",
            )
        category = Category.TERMINAL
        identity = app_identity(proc=terminal[0], decision=terminal[1])
    else:
        identity = app_identity(proc=proc, decision=decision)
    return _Placement(
        proc=proc,
        member=category,
        bucket=category,
        key_class=KEY_CLASS_APP,
        key=identity,
        name=names.get(identity, identity),
    )


def _place_dev(*, proc: RawProcess, member: Category, grouping: GroupingInput) -> _Placement:
    root = effective_root(
        cwd=proc.cwd,
        project_root_by_cwd=grouping.project_root_by_cwd,
        own_home=grouping.own_home,
    )
    if root is None:
        return _Placement(
            proc=proc,
            member=member,
            bucket=DEV_BUCKET,
            key_class=KEY_CLASS_ROOT_PROCESS,
            key=UNROOTED,
            name="",
        )
    name = PurePosixPath(root).name
    return _Placement(
        proc=proc,
        member=member,
        bucket=DEV_BUCKET,
        key_class=KEY_CLASS_FOLDER,
        key=root,
        name=name,
        root=root,
    )


def _place_other(*, proc: RawProcess, member: Category) -> _Placement:
    """Build daemons gather by tool; anything else waits for its root process (rule 6)."""
    tool = tool_group(proc=proc) if member is Category.OTHER else None
    key, name, reason = tool or (UNROOTED, "", None)
    return _Placement(
        proc=proc,
        member=member,
        bucket=Category.OTHER,
        key_class=KEY_CLASS_ROOT_PROCESS if tool is None else KEY_CLASS_TOOL,
        key=key,
        name=name,
        tool_reason=reason,
    )


def _place(*, pair: Pair, by_pid: Mapping[int, Pair], grouping: GroupingInput) -> _Placement:
    proc, decision = pair
    category = decision.category
    if category is None:
        raise ValueError(f"excluded process {proc.pid} must be removed before grouping")
    if category in PROTECTED_CATEGORIES:
        key, name = protected_label(
            proc=proc,
            category=category,
            own_uid=grouping.own_uid,
            reason_code=decision.reason_code,
        )
        return _Placement(
            proc=proc,
            member=category,
            bucket=category,
            key_class=KEY_CLASS_PROTECTED,
            key=key,
            name=name,
        )
    if category in APP_CATEGORIES or is_terminal_shell(proc=proc):
        return _place_app(
            pair=pair, category=category, by_pid=by_pid, names=grouping.desktop_name_by_appid
        )
    if category in DEV_CATEGORIES:
        return _place_dev(proc=proc, member=category, grouping=grouping)
    return _place_other(proc=proc, member=category)


def _resolve_unrooted(*, placements: list[_Placement]) -> list[_Placement]:
    """Rule 6: unrooted processes group under their topmost ancestor in the same bucket."""
    members: dict[Category, dict[int, RawProcess]] = {}
    for placement in placements:
        if placement.key == UNROOTED:
            members.setdefault(placement.bucket, {})[placement.proc.pid] = placement.proc
    resolved = []
    for placement in placements:
        if placement.key != UNROOTED:
            resolved.append(placement)
            continue
        root = root_process(proc=placement.proc, members=members[placement.bucket])
        key = f"{root.name}{KEY_SEPARATOR}{root.cwd or ''}"
        resolved.append(replace(placement, key=key, name=root.name))
    return resolved


def _group_category(*, bucket: Category, items: list[_Placement]) -> Category:
    if bucket is not DEV_BUCKET:
        return bucket
    present = {item.member for item in items}
    return next(category for category in DEV_PRIORITY if category in present)


def _process_parts(*, grouping: GroupingInput) -> list[Part]:
    by_pid = {pair[0].pid: pair for pair in grouping.pairs}
    placements = [_place(pair=pair, by_pid=by_pid, grouping=grouping) for pair in grouping.pairs]
    grouped: dict[tuple[Category, str], list[_Placement]] = {}
    for placement in _resolve_unrooted(placements=placements):
        grouped.setdefault((placement.bucket, placement.key), []).append(placement)
    ports_by_pid = grouping.listen_ports_by_pid
    parts = []
    for (bucket, key), unsorted in grouped.items():
        items = sorted(unsorted, key=lambda item: item.proc.pid)
        pids = tuple(item.proc.pid for item in items)
        ports = sorted(set(chain.from_iterable(ports_by_pid.get(pid, ()) for pid in pids)))
        parts.append(
            Part(
                category=_group_category(bucket=bucket, items=items),
                key_class=items[0].key_class,
                key=key,
                name=items[0].name,
                pids=pids,
                root=items[0].root,
                ports=tuple(ports),
                lead_process=items[0].proc.name,
                process_names=tuple(item.proc.name for item in items),
                tool_reason=items[0].tool_reason,
                id_scope=bucket.value if items[0].key_class == KEY_CLASS_ROOT_PROCESS else "",
            )
        )
    return scope_shared_app_keys(parts=parts)


def _to_draft(*, part: Part) -> GroupDraft:
    facts = GroupFacts(
        category=part.category,
        name=part.name,
        folder=part.working_dir or part.root,
        containers=len(part.container_ids),
        processes=len(part.pids),
        ports=part.ports,
        compose_project=part.compose_project,
        lead_process=part.lead_process,
        process_names=part.process_names,
        tool_reason=part.tool_reason,
    )
    return GroupDraft(
        id=stable_group_id(key_class=part.key_class, key=part.key, scope=part.id_scope),
        key=part.key,
        name=part.name,
        category=part.category,
        process_pids=part.pids,
        container_ids=part.container_ids,
        compose_project=part.compose_project,
        working_dir=part.working_dir,
        explanation=explain_group(facts=facts),
    )


def build_groups(*, grouping: GroupingInput) -> tuple[GroupDraft, ...]:
    """Group processes and containers following SPECIFICHE 5.5, in order.

    Compose containers form one group per project; apps and terminals gather
    their children; terminal-launched processes group by project root; a project
    root related (equal, ancestor or descendant, per path component) to a compose
    working dir fuses with it into a PROJECT group; the rest groups by root
    process. The result is sorted by category, name and key.

    Parameters
    ----------
    grouping : GroupingInput
        Categorized processes, containers and the precomputed lookups.
    """
    containers = container_parts(containers=grouping.containers)
    parts = fuse(
        containers=containers,
        processes=_process_parts(grouping=grouping),
        own_home=grouping.own_home,
    )
    drafts = [_to_draft(part=part) for part in parts]
    return tuple(sorted(drafts, key=lambda draft: (draft.category.value, draft.name, draft.key)))
