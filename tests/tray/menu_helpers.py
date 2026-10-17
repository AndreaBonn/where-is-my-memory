from dataclasses import replace
from datetime import datetime
from pathlib import Path

from wimm.model.enums import ActionKind, ActivityState, Category, GroupId, Risk
from wimm.model.memory import MemoryUse
from wimm.model.snapshot import ActionOffer, ActivityAssessment, Group, Snapshot
from wimm.serialize import snapshot_from_json

FIXTURE = Path(__file__).parents[1] / "fixtures" / "snapshot_whitebox.json"
SINCE = datetime.fromisoformat("2026-10-16T05:12:00+02:00")


def base_snapshot() -> Snapshot:
    return snapshot_from_json(text=FIXTURE.read_text())


def make_group(
    name: str,
    *,
    reclaimable: int,
    state: ActivityState = ActivityState.IDLE,
    ignored: bool = False,
    category: Category = Category.DEV_SERVER,
) -> Group:
    actionable = category is not Category.SYSTEM
    return Group(
        id=GroupId(f"id-{name}"),
        name=name,
        category=category,
        activity=ActivityAssessment(state=state, since=SINCE, reason="nessuna connessione"),
        memory=MemoryUse(used=reclaimable * 2, reclaimable=reclaimable),
        ports=(),
        primary_action=ActionOffer(kind=ActionKind.GROUP_STOP, risk=Risk.SAFE)
        if actionable
        else None,
        ignored=ignored,
        snoozed_until=None,
        explanation="spiegazione",
        compose_project=None,
        members=(),
    )


def with_groups(*groups: Group) -> Snapshot:
    return replace(base_snapshot(), groups=groups)
