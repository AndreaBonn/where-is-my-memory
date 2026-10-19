from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from .cache_items import ItemBlob, require_unique_blob_paths
from .enums import ActionKind, GroupId, PlanId, Risk, TargetId, TargetShape
from .validation import ImmutableModel, require_aware, require_bytes, require_nonnegative

ACTION_TARGET_SHAPES: Mapping[ActionKind, TargetShape] = MappingProxyType(
    {
        ActionKind.PROCESS_TERMINATE: TargetShape.TARGET,
        ActionKind.PROCESS_KILL: TargetShape.TARGET,
        ActionKind.APP_CLOSE: TargetShape.GROUP,
        ActionKind.CONTAINER_STOP: TargetShape.TARGET,
        ActionKind.CONTAINER_REMOVE: TargetShape.TARGET,
        ActionKind.GROUP_STOP: TargetShape.GROUP,
        ActionKind.COMPOSE_DOWN: TargetShape.GROUP,
        ActionKind.COMPOSE_DOWN_VOLUMES: TargetShape.GROUP,
        ActionKind.STOP_ALL_IDLE_SAFE: TargetShape.NONE,
        ActionKind.IMAGE_REMOVE: TargetShape.TARGET,
        ActionKind.IMAGES_PRUNE_DANGLING: TargetShape.NONE,
        ActionKind.IMAGES_PRUNE_UNUSED: TargetShape.NONE,
        ActionKind.BUILDER_PRUNE: TargetShape.NONE,
        ActionKind.CONTAINERS_PRUNE_STOPPED: TargetShape.NONE,
        ActionKind.VOLUME_REMOVE: TargetShape.TARGET,
        ActionKind.CACHE_CLEAN: TargetShape.TARGET,
        ActionKind.CACHE_ITEM_REMOVE: TargetShape.TARGET,
        ActionKind.TRASH_EMPTY: TargetShape.NONE,
        ActionKind.DEVDIR_DELETE: TargetShape.TARGET,
        ActionKind.DISK_FREE_SAFE: TargetShape.NONE,
        ActionKind.CONTAINER_START: TargetShape.TARGET,
        # C4: the target is the stop plan whose containers start again.
        ActionKind.RESTART_STOPPED: TargetShape.TARGET,
    }
)
# The prunes expand to one step per image or container id (Q-13), so the user can drop single ones.
EXCLUDABLE_ACTIONS = frozenset(
    {
        ActionKind.GROUP_STOP,
        ActionKind.STOP_ALL_IDLE_SAFE,
        ActionKind.IMAGES_PRUNE_DANGLING,
        ActionKind.IMAGES_PRUNE_UNUSED,
        ActionKind.CONTAINERS_PRUNE_STOPPED,
        ActionKind.DISK_FREE_SAFE,
    }
)


@dataclass(frozen=True, slots=True)
class ActionRequest(ImmutableModel):
    kind: ActionKind
    group_id: GroupId | None = None
    target_id: TargetId | None = None
    excluded_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        shape = ACTION_TARGET_SHAPES[self.kind]
        actual = (self.group_id is not None, self.target_id is not None)
        expected = (shape is TargetShape.GROUP, shape is TargetShape.TARGET)
        if actual != expected or self.group_id == "" or self.target_id == "":
            raise ValueError("group_id and target_id do not match action target shape")
        if self.excluded_ids and self.kind not in EXCLUDABLE_ACTIONS:
            raise ValueError("excluded_ids is not allowed for this action")


@dataclass(frozen=True, slots=True)
class ProcessFingerprint(ImmutableModel):
    pid: int
    create_time: float
    uid: int
    cmdline_hash: str

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_nonnegative(value=self.pid, field="pid")


@dataclass(frozen=True, slots=True)
class ContainerFingerprint(ImmutableModel):
    id: str
    status: str


@dataclass(frozen=True, slots=True)
class ComposeFingerprint(ImmutableModel):
    project: str
    container_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class ImageFingerprint(ImmutableModel):
    id: str


@dataclass(frozen=True, slots=True)
class VolumeFingerprint(ImmutableModel):
    """Identity of a volume: its name and Docker's `CreatedAt`, to tell a recreated one."""

    name: str
    created_at: str


@dataclass(frozen=True, slots=True)
class EngineIdentity(ImmutableModel):
    """A container engine's socket: its path and the inode and device it had at planning time."""

    path: str
    st_ino: int
    st_dev: int


@dataclass(frozen=True, slots=True)
class DirFingerprint(ImmutableModel):
    realpath: str
    st_ino: int
    st_dev: int


@dataclass(frozen=True, slots=True)
class ItemFingerprint(ImmutableModel):
    """One cache item (a model folder) and the exclusive store blobs removed with it."""

    realpath: str
    st_ino: int
    st_dev: int
    blobs: tuple[ItemBlob, ...] = ()

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_unique_blob_paths(blobs=self.blobs)


Fingerprint = (
    ProcessFingerprint
    | ContainerFingerprint
    | ComposeFingerprint
    | ImageFingerprint
    | VolumeFingerprint
    | DirFingerprint
    | ItemFingerprint
)


# Aggregate stop requests expand into process/container steps (spec 8.1).
# Global prune commands have no single identity in spec 8.2; None is explicit.
# Cache and trash steps identify each directory, without devdir name restrictions.
ACTION_FINGERPRINT_TYPES: Mapping[ActionKind, tuple[type, ...]] = MappingProxyType(
    {
        ActionKind.PROCESS_TERMINATE: (ProcessFingerprint,),
        ActionKind.PROCESS_KILL: (ProcessFingerprint,),
        ActionKind.APP_CLOSE: (ProcessFingerprint,),
        ActionKind.CONTAINER_STOP: (ContainerFingerprint,),
        ActionKind.CONTAINER_REMOVE: (ContainerFingerprint,),
        ActionKind.GROUP_STOP: (),
        ActionKind.STOP_ALL_IDLE_SAFE: (),
        ActionKind.COMPOSE_DOWN: (ComposeFingerprint,),
        ActionKind.COMPOSE_DOWN_VOLUMES: (ComposeFingerprint,),
        ActionKind.IMAGE_REMOVE: (ImageFingerprint,),
        ActionKind.VOLUME_REMOVE: (VolumeFingerprint,),
        ActionKind.DEVDIR_DELETE: (DirFingerprint,),
        ActionKind.CACHE_CLEAN: (DirFingerprint,),
        ActionKind.CACHE_ITEM_REMOVE: (ItemFingerprint,),
        ActionKind.TRASH_EMPTY: (DirFingerprint,),
        ActionKind.IMAGES_PRUNE_DANGLING: (type(None),),
        ActionKind.IMAGES_PRUNE_UNUSED: (type(None),),
        ActionKind.BUILDER_PRUNE: (type(None),),
        ActionKind.CONTAINERS_PRUNE_STOPPED: (type(None),),
        ActionKind.DISK_FREE_SAFE: (),
        ActionKind.CONTAINER_START: (ContainerFingerprint,),
        ActionKind.RESTART_STOPPED: (),
    }
)


@dataclass(frozen=True, slots=True)
class PlanStep(ImmutableModel):
    order: int
    kind: ActionKind
    target_label: str
    fingerprint: Fingerprint | None
    risk: Risk

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        if type(self.fingerprint) not in ACTION_FINGERPRINT_TYPES[self.kind]:
            raise ValueError("fingerprint does not match executable action kind")


@dataclass(frozen=True, slots=True)
class Plan(ImmutableModel):
    plan_id: PlanId
    request: ActionRequest
    created_at: datetime
    expires_at: datetime
    steps: tuple[PlanStep, ...]
    consequences: tuple[str, ...]
    estimated_reclaim_ram: int
    estimated_reclaim_disk: int
    confirm_phrase: str | None = None
    # The engine sockets in use when the plan was built (S9): a container or compose step
    # runs only if the executor finds the same ones.
    engines: tuple[EngineIdentity, ...] = ()

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_aware(value=self.created_at, field="created_at")
        require_aware(value=self.expires_at, field="expires_at")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        if not self.steps:
            raise ValueError("steps must not be empty")
        if tuple(step.order for step in self.steps) != tuple(range(1, len(self.steps) + 1)):
            raise ValueError("steps order must be consecutive from 1")
        if (bool(self.confirm_phrase)) != (self.risk is Risk.DANGER):
            raise ValueError("confirm_phrase is required exactly for danger plans")
        if self.confirm_phrase is not None and not self.confirm_phrase.strip():
            raise ValueError("confirm_phrase must not be blank")
        require_bytes(value=self.estimated_reclaim_ram, field="estimated_reclaim_ram")
        require_bytes(value=self.estimated_reclaim_disk, field="estimated_reclaim_disk")

    @property
    def risk(self) -> Risk:
        return max(step.risk for step in self.steps)
