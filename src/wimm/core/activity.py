from collections.abc import Sequence
from datetime import datetime, timedelta

from wimm.model.enums import ActivityState
from wimm.model.snapshot import ActivityAssessment

from . import text
from .activity_model import ActivityConfig as ActivityConfig
from .activity_model import ActivityInputs as ActivityInputs
from .activity_model import EntityKind as EntityKind
from .activity_model import EntitySample as EntitySample
from .activity_model import GroupMember as GroupMember
from .activity_model import is_measurable as is_measurable
from .activity_model import kind_of as kind_of
from .activity_signals import Step, build_steps, current_run_start, open_port, window_averages
from .activity_signals import sample_is_active as sample_is_active


def _covers_window(*, inputs: ActivityInputs, config: ActivityConfig) -> bool:
    if not inputs.history:
        return False
    # The ring spans at most window - (window mod interval): up to one interval short.
    tolerance = config.interval_s
    oldest_needed = inputs.now - timedelta(seconds=config.window_s - tolerance)
    return inputs.history[0].taken_at <= oldest_needed


def _unknown(*, reason: str) -> ActivityAssessment:
    return ActivityAssessment(state=ActivityState.UNKNOWN, since=None, reason=reason)


def _idle_since(*, inputs: ActivityInputs) -> tuple[datetime, bool]:
    """Idle start and whether it is only the monitor start (no earlier evidence)."""
    if inputs.persisted_last_active is not None:
        return max(inputs.created_at, inputs.persisted_last_active), False
    return max(inputs.created_at, inputs.monitor_started_at), (
        inputs.monitor_started_at >= inputs.created_at
    )


def _assess_idle(
    *, inputs: ActivityInputs, kind: EntityKind, config: ActivityConfig, steps: Sequence[Step]
) -> ActivityAssessment:
    cpu_avg, net_avg = window_averages(steps=steps)
    if cpu_avg is None:
        return _unknown(reason=text.reason_cpu_unavailable())
    since, from_monitor_start = _idle_since(inputs=inputs)
    is_server = kind is EntityKind.SERVER
    forgotten_port = open_port(server_ports=inputs.server_ports, steps=steps) if is_server else None
    facts = text.IdleFacts(
        window_s=config.window_s,
        cpu_avg_pct=cpu_avg,
        net_avg_bps=net_avg if kind is EntityKind.CONTAINER else None,
        watches_connections=kind is EntityKind.SERVER,
        open_port=forgotten_port,
    )
    reason = text.reason_idle(
        idle_for_s=(inputs.now - since).total_seconds(),
        facts=facts,
        from_monitor_start=from_monitor_start,
    )
    return ActivityAssessment(state=ActivityState.IDLE, since=since, reason=reason)


def _assess_short_history(*, inputs: ActivityInputs, config: ActivityConfig) -> ActivityAssessment:
    observed = (inputs.now - inputs.history[0].taken_at).total_seconds() if inputs.history else 0.0
    persisted = inputs.persisted_last_active
    # A persisted instant younger than a window is not yet proof of inactivity.
    if persisted is None or (inputs.now - persisted).total_seconds() < config.window_s:
        return _unknown(reason=text.reason_observing(elapsed_s=observed))
    since, _ = _idle_since(inputs=inputs)
    reason = text.reason_idle_persisted(
        idle_for_s=(inputs.now - since).total_seconds(), observed_s=observed
    )
    return ActivityAssessment(state=ActivityState.IDLE, since=since, reason=reason)


def assess_activity(*, inputs: ActivityInputs, config: ActivityConfig) -> ActivityAssessment:
    """Decide active / idle / unknown for one entity (5.4, state rules).

    Active: some step in the window is active; ``since`` starts the current active run.
    Otherwise, if the history covers the window the entity is idle; if it does not, a
    persisted ``last_active_at`` still yields idle (never over an active sample), and
    without it the entity is unknown ("in osservazione").
    """
    kind = kind_of(category=inputs.category)
    if kind is EntityKind.NOT_EVALUATED:
        return _unknown(reason=text.reason_not_evaluated())
    if kind is EntityKind.UNMEASURABLE:
        return _unknown(reason=text.reason_unmeasurable(category=inputs.category))
    steps = build_steps(inputs=inputs, kind=kind, config=config)
    run_start = current_run_start(steps=steps)
    if run_start is not None:
        reason = text.reason_active(active_for_s=(inputs.now - run_start).total_seconds())
        return ActivityAssessment(state=ActivityState.ACTIVE, since=run_start, reason=reason)
    if not _covers_window(inputs=inputs, config=config):
        return _assess_short_history(inputs=inputs, config=config)
    return _assess_idle(inputs=inputs, kind=kind, config=config, steps=steps)


def last_active_at(*, inputs: ActivityInputs, config: ActivityConfig) -> datetime | None:
    """End of the latest active step in the window, None when nothing was active.

    An entity stays "active" for a whole window after its last activity: this is the
    instant the activity actually stopped, which an idle ``since`` must count from.
    """
    kind = kind_of(category=inputs.category)
    if kind in (EntityKind.NOT_EVALUATED, EntityKind.UNMEASURABLE):
        return None
    steps = build_steps(inputs=inputs, kind=kind, config=config)
    latest = next((step for step in reversed(steps) if step.active), None)
    return None if latest is None else latest.curr.taken_at


def assess_group_activity(*, members: Sequence[GroupMember]) -> ActivityAssessment:
    """Combine member verdicts: any active -> active; all measurable idle -> idle.

    Unmeasurable members are ignored; a still-unknown measurable member blocks "idle".
    """
    measurable = [m.assessment for m in members if m.measurable]
    active = [a for a in measurable if a.state is ActivityState.ACTIVE]
    if active:
        reason = text.reason_group_active(active=len(active), measurable=len(measurable))
        since = min(a.since for a in active if a.since is not None)
        return ActivityAssessment(state=ActivityState.ACTIVE, since=since, reason=reason)
    if measurable and all(a.state is ActivityState.IDLE for a in measurable):
        since = max(a.since for a in measurable if a.since is not None)
        reason = text.reason_group_idle(measurable=len(measurable))
        return ActivityAssessment(state=ActivityState.IDLE, since=since, reason=reason)
    return _unknown(reason=text.reason_group_unknown(measurable=len(measurable)))
