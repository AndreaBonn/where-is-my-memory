from enum import Enum, IntEnum
from typing import NewType

GroupId = NewType("GroupId", str)
PlanId = NewType("PlanId", str)
TargetId = NewType("TargetId", str)
SCHEMA_VERSION = 1


class Category(Enum):
    SYSTEM = "SYSTEM"
    CONTAINER = "CONTAINER"
    DEV_SERVER = "DEV_SERVER"
    DEV_PROCESS = "DEV_PROCESS"
    AI_CLI = "AI_CLI"
    BROWSER = "BROWSER"
    DESKTOP_APP = "DESKTOP_APP"
    TERMINAL = "TERMINAL"
    SESSION = "SESSION"
    SELF = "SELF"
    OTHER = "OTHER"
    PROJECT = "PROJECT"


class Protection(Enum):
    ACTIONABLE = "actionable"
    PROTECTED = "protected"


class Risk(IntEnum):
    SAFE = 0
    CAUTION = 1
    DANGER = 2


class ActivityState(Enum):
    ACTIVE = "active"
    IDLE = "idle"
    UNKNOWN = "unknown"


class ActionKind(Enum):
    PROCESS_TERMINATE = "process_terminate"
    PROCESS_KILL = "process_kill"
    APP_CLOSE = "app_close"
    CONTAINER_STOP = "container_stop"
    CONTAINER_REMOVE = "container_remove"
    GROUP_STOP = "group_stop"
    COMPOSE_DOWN = "compose_down"
    COMPOSE_DOWN_VOLUMES = "compose_down_volumes"
    STOP_ALL_IDLE_SAFE = "stop_all_idle_safe"
    IMAGE_REMOVE = "image_remove"
    IMAGES_PRUNE_DANGLING = "images_prune_dangling"
    IMAGES_PRUNE_UNUSED = "images_prune_unused"
    BUILDER_PRUNE = "builder_prune"
    CONTAINERS_PRUNE_STOPPED = "containers_prune_stopped"
    VOLUME_REMOVE = "volume_remove"
    CACHE_CLEAN = "cache_clean"
    TRASH_EMPTY = "trash_empty"
    DEVDIR_DELETE = "devdir_delete"
    DISK_FREE_SAFE = "disk_free_safe"


class MetricsSource(Enum):
    CGROUP = "cgroup"
    STATS_API = "stats_api"
    UNAVAILABLE = "unavailable"


class Pressure(Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


class StepOutcome(Enum):
    OK = "ok"
    ALREADY_GONE = "already_gone"
    NOT_RESPONDING = "not_responding"
    FAILED = "failed"


class TargetShape(Enum):
    NONE = "none"
    GROUP = "group"
    TARGET = "target"


def protection_of(category: Category) -> Protection:
    if category in {Category.SYSTEM, Category.SESSION, Category.SELF}:
        return Protection.PROTECTED
    return Protection.ACTIONABLE
