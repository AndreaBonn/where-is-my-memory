"""Fakes and hand-built plans for executor tests. Nothing here touches the system."""

import signal
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from wimm.core.planning import cmdline_hash
from wimm.model.actions import (
    ActionRequest,
    ContainerFingerprint,
    EngineIdentity,
    ImageFingerprint,
    Plan,
    PlanStep,
    ProcessFingerprint,
    VolumeFingerprint,
)
from wimm.model.enums import ActionKind, GroupId, PlanId, Risk, TargetId
from wimm.service.control_protocols import LiveContainer, LiveImage, LiveProcess, LiveVolume
from wimm.service.errors import ControlFailed, TargetGone

OWNER_UID = 1000
WIMM_PID = 900
CREATED_AT = 1_700_000_000.0
GROUP_TARGET_KINDS = frozenset(
    {ActionKind.APP_CLOSE, ActionKind.COMPOSE_DOWN, ActionKind.COMPOSE_DOWN_VOLUMES}
)
CMDLINE = ("python3", "-m", "http.server")
VOLUME_CREATED_AT = "2026-10-01T10:00:00Z"


@dataclass(slots=True)
class FakeProcesses:
    live: dict[int, LiveProcess] = field(default_factory=dict)
    tree: dict[int, tuple[int, ...]] = field(default_factory=dict)
    lineage: frozenset[int] = frozenset({WIMM_PID, 1})
    stubborn: frozenset[int] = frozenset()
    failing: frozenset[int] = frozenset()
    crashing: frozenset[int] = frozenset()
    broken_trees: frozenset[int] = frozenset()
    on_wait: Callable[[], None] = lambda: None
    extra_protected: tuple[str, ...] = ()
    remote_sessions_actionable: bool = False
    signals: list[tuple[int, signal.Signals]] = field(default_factory=list)
    waits: list[tuple[tuple[int, ...], float]] = field(default_factory=list)

    def inspect(self, *, pid: int) -> LiveProcess | None:
        live = self.live.get(pid)
        if live is not None and live.cmdline[:1] and live.cmdline[0] in self.extra_protected:
            return replace(live, protected=True)
        return live

    def set_extra_protected_names(self, *, names: tuple[str, ...]) -> None:
        self.extra_protected = names

    def set_remote_sessions_actionable(self, *, enabled: bool) -> None:
        self.remote_sessions_actionable = enabled

    def self_lineage(self) -> frozenset[int]:
        return self.lineage

    def descendants(self, *, pid: int) -> Sequence[int]:
        if pid in self.broken_trees:
            raise ControlFailed(f"cannot list children of {pid}")
        return self.tree.get(pid, ())

    def send_signal(self, *, pid: int, sig: signal.Signals) -> None:
        if pid in self.crashing:
            raise RuntimeError(f"unexpected failure signalling {pid}")
        if pid in self.failing:
            raise ControlFailed(f"cannot signal {pid}")
        self.signals.append((pid, sig))

    def wait_gone(self, *, pids: Sequence[int], timeout_s: float) -> frozenset[int]:
        self.waits.append((tuple(pids), timeout_s))
        self.on_wait()
        return frozenset(pid for pid in pids if pid in self.stubborn)


@dataclass(slots=True)
class FakeDocker:
    live: dict[str, LiveContainer] = field(default_factory=dict)
    failing: frozenset[str] = frozenset()
    crashing: frozenset[str] = frozenset()
    images: dict[str, LiveImage] = field(default_factory=dict)
    volumes: dict[str, LiveVolume] = field(default_factory=dict)
    cache_freed: int = 0
    failing_disk: frozenset[str] = frozenset()
    digests: dict[str, tuple[str, ...]] = field(default_factory=dict)
    prune_error: BaseException | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)
    identities: tuple[EngineIdentity, ...] = ()

    def engine_identities(self) -> tuple[EngineIdentity, ...]:
        return self.identities

    def inspect(self, *, container_id: str) -> LiveContainer | None:
        return self.live.get(container_id)

    def stop(self, *, container_id: str, timeout_s: int) -> None:
        if container_id in self.crashing:
            raise RuntimeError(f"unexpected failure stopping {container_id}")
        if container_id in self.failing:
            raise ControlFailed(f"cannot stop {container_id}")
        self.calls.append(("stop", f"{container_id}:{timeout_s}"))
        self.live[container_id] = LiveContainer(id=container_id, status="exited")

    def start(self, *, container_id: str) -> None:
        if container_id in self.failing:
            raise ControlFailed(f"cannot start {container_id}")
        self.calls.append(("start", container_id))
        self.live[container_id] = LiveContainer(id=container_id, status="running")

    def remove(self, *, container_id: str, volumes: bool) -> None:
        self.calls.append(("remove", f"{container_id}:v={volumes}"))
        self.live.pop(container_id, None)

    def inspect_image(self, *, image_id: str) -> LiveImage | None:
        return self.images.get(image_id)

    def resolve_image(self, *, ref: str) -> str | None:
        if ref in self.images:
            return ref
        return next((i for i, image in self.images.items() if ref in image.tags), None)

    def remove_image(self, *, ref: str) -> None:
        """Like the daemon: a tag drops that tag, an id with several tags or children is a 409.

        An image that still has a digest reference survives its last tag.
        """
        if ref in self.failing_disk:
            raise ControlFailed(f"cannot remove {ref}")
        owner = self.resolve_image(ref=ref)
        if owner is None:
            raise TargetGone()
        self.calls.append(("remove_image", ref))
        image = self.images[owner]
        if ref == owner:
            if len(image.tags) > 1 or image.has_children:
                raise ControlFailed("conflict: unable to delete, image has dependants")
            del self.images[owner]
            return
        tags = tuple(t for t in image.tags if t != ref)
        if tags or self.digests.get(owner):
            self.images[owner] = replace(image, tags=tags)
        else:
            del self.images[owner]

    def inspect_volume(self, *, name: str) -> LiveVolume | None:
        return self.volumes.get(name)

    def remove_volume(self, *, name: str) -> None:
        if name not in self.volumes:
            raise TargetGone()
        self.calls.append(("remove_volume", name))
        del self.volumes[name]

    def prune_build_cache(self) -> int:
        self.calls.append(("prune_build_cache", ""))
        if self.prune_error is not None:
            raise self.prune_error
        return self.cache_freed


def live_process(*, pid: int, uid: int = OWNER_UID, protected: bool = False) -> LiveProcess:
    return LiveProcess(
        pid=pid, create_time=CREATED_AT, uid=uid, cmdline=CMDLINE, protected=protected
    )


def process_step(
    *, order: int, pid: int, uid: int = OWNER_UID, kind: ActionKind = ActionKind.PROCESS_TERMINATE
) -> PlanStep:
    fingerprint = ProcessFingerprint(
        pid=pid, create_time=CREATED_AT, uid=uid, cmdline_hash=cmdline_hash(cmdline=CMDLINE)
    )
    return PlanStep(
        order=order,
        kind=kind,
        target_label=f"proc {pid}",
        fingerprint=fingerprint,
        risk=Risk.SAFE,
    )


def container_step(
    *, order: int, container_id: str, kind: ActionKind, status: str = "running"
) -> PlanStep:
    return PlanStep(
        order=order,
        kind=kind,
        target_label=container_id,
        fingerprint=ContainerFingerprint(id=container_id, status=status),
        risk=Risk.SAFE,
    )


def image_step(*, order: int, image_id: str) -> PlanStep:
    return PlanStep(
        order=order,
        kind=ActionKind.IMAGE_REMOVE,
        target_label=image_id,
        fingerprint=ImageFingerprint(id=image_id),
        risk=Risk.SAFE,
    )


def volume_step(*, order: int, name: str, created_at: str = VOLUME_CREATED_AT) -> PlanStep:
    return PlanStep(
        order=order,
        kind=ActionKind.VOLUME_REMOVE,
        target_label=name,
        fingerprint=VolumeFingerprint(name=name, created_at=created_at),
        risk=Risk.DANGER,
    )


def builder_step(*, order: int) -> PlanStep:
    return PlanStep(
        order=order,
        kind=ActionKind.BUILDER_PRUNE,
        target_label="build cache",
        fingerprint=None,
        risk=Risk.SAFE,
    )


def make_plan(
    *,
    steps: Sequence[PlanStep],
    request_kind: ActionKind | None = None,
    engines: tuple[EngineIdentity, ...] = (),
) -> Plan:
    if request_kind is not None:
        request = ActionRequest(kind=request_kind)
    elif len(steps) == 1 and steps[0].kind is ActionKind.BUILDER_PRUNE:
        request = ActionRequest(kind=ActionKind.BUILDER_PRUNE)
    elif len(steps) == 1 and steps[0].kind in GROUP_TARGET_KINDS:
        request = ActionRequest(kind=steps[0].kind, group_id=GroupId("g_test"))
    elif len(steps) == 1:
        request = ActionRequest(kind=steps[0].kind, target_id=TargetId("target"))
    else:
        request = ActionRequest(kind=ActionKind.GROUP_STOP, group_id=GroupId("g_test"))
    now = datetime.now(UTC)
    danger = [step.target_label for step in steps if step.risk is Risk.DANGER]
    return Plan(
        plan_id=PlanId("plan-test"),
        request=request,
        created_at=now,
        expires_at=now + timedelta(seconds=120),
        steps=tuple(steps),
        consequences=(),
        estimated_reclaim_ram=0,
        estimated_reclaim_disk=0,
        confirm_phrase=danger[0] if danger else None,
        engines=engines,
    )
