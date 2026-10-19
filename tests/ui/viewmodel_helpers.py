from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import TypedDict, Unpack

from wimm.model.enums import ActionKind, ActivityState, Category, GroupId, Risk
from wimm.model.memory import MemoryUse
from wimm.model.snapshot import (
    ActionOffer,
    ActivityAssessment,
    Group,
    Member,
    Snapshot,
)
from wimm.ui.viewmodel import (
    build_rows,
)
from wimm.ui.views import RowFilters

FIXTURE = Path(__file__).parents[1] / "fixtures" / "snapshot_whitebox.json"


IDLE_SINCE = datetime.fromisoformat("2026-10-16T05:12:00+02:00")


class GroupOverrides(TypedDict, total=False):
    id: GroupId
    ports: tuple[int, ...]
    explanation: str
    members: tuple[Member, ...]
    snoozed_until: datetime | None
    ignored: bool


def make_group(
    name: str = "g",
    *,
    category: Category = Category.DEV_SERVER,
    state: ActivityState = ActivityState.IDLE,
    reclaimable: int = 100,
    used: int = 200,
    risk: Risk | None = Risk.SAFE,
    reason: str = "reason",
    since: datetime | None = IDLE_SINCE,
    **overrides: Unpack[GroupOverrides],
) -> Group:
    primary = None if risk is None else ActionOffer(kind=ActionKind.GROUP_STOP, risk=risk)
    base = Group(
        id=GroupId(f"id-{name}"),
        name=name,
        category=category,
        activity=ActivityAssessment(state=state, since=since, reason=reason),
        memory=MemoryUse(used=used, reclaimable=reclaimable),
        ports=(),
        primary_action=primary,
        ignored=False,
        snoozed_until=None,
        explanation="explanation",
        compose_project=None,
        members=(),
    )
    return replace(base, **overrides)


def with_groups(snapshot: Snapshot, *groups: Group) -> Snapshot:
    return replace(snapshot, groups=groups)


def titles(
    snapshot: Snapshot,
    now: datetime,
    *,
    only_idle: bool = False,
    categories: frozenset[Category] = frozenset(),
    risks: frozenset[Risk] = frozenset(),
    query: str = "",
) -> list[str]:
    filters = RowFilters(only_idle=only_idle, categories=categories, risks=risks, query=query)
    return [row.title for row in build_rows(snapshot=snapshot, filters=filters, now=now)]


def roomy_disk(snapshot: Snapshot) -> Snapshot:
    """The fixture with half the disk free, so the RAM drives the pressure."""
    half = snapshot.disk.total // 2
    return replace(snapshot, disk=replace(snapshot.disk, used=half, free=half))
