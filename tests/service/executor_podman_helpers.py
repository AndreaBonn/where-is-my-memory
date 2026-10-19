from dataclasses import dataclass, field

import docker.errors

from tests.service.engine_fakes import FakeProvider, engine_at
from tests.service.executor_fakes import OWNER_UID, FakeProcesses, container_step, make_plan
from wimm.collectors.docker_engines import Engine
from wimm.model.actions import EngineIdentity
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import StepOutcome
from wimm.service.controls import DockerSdkControl
from wimm.service.executor import PlanExecutor

STOP = ActionKind.CONTAINER_STOP
REMOVE = ActionKind.CONTAINER_REMOVE
DOCKER_SOCKET = "/var/run/docker.sock"
PODMAN_SOCKET = "/run/user/1000/podman/podman.sock"
PODMAN_ID = "a" * 64
DOCKER_ID = "b" * 64
RUNNING_LIKE = ("running", "paused")
NOT_RUNNING_STATES = ("exited", "stopped", "created", "initialized")


@dataclass(slots=True)
class PodmanContainer:
    """A container as Podman's compat API shows it: id and status, nothing more."""

    id: str
    status: str = "running"
    calls: list[str] = field(default_factory=list)
    stop_arrives_late: bool = False  # it stopped on its own before the stop call: HTTP 304

    def stop(self, *, timeout: int) -> None:
        self.calls.append(f"stop:{timeout}")
        if self.stop_arrives_late:
            return  # 304 is not an error for docker-py: the call returns, nothing changes
        self.status = "exited"

    def start(self) -> None:
        self.calls.append("start")
        self.status = "running"

    def remove(self, *, v: bool) -> None:
        self.calls.append(f"remove:{v}")
        if self.status in ("running", "paused"):
            raise docker.errors.APIError(
                "cannot remove container as it is running - running or paused containers "
                "cannot be removed without force: container state improper"
            )
        if self.status in ("stopping", "removing"):
            raise docker.errors.APIError(f"container is {self.status}: container state improper")


@dataclass(slots=True)
class PodmanContainers:
    held: dict[str, PodmanContainer] = field(default_factory=dict)

    def get(self, container_id: str) -> PodmanContainer:
        if container_id not in self.held:
            raise docker.errors.NotFound(f"no such container: {container_id}")
        return self.held[container_id]


@dataclass(slots=True)
class PodmanClient:
    containers: PodmanContainers


def _client(*held: PodmanContainer) -> PodmanClient:
    return PodmanClient(containers=PodmanContainers(held={c.id: c for c in held}))


def _executor(*engines: Engine) -> tuple[PlanExecutor, tuple[EngineIdentity, ...]]:
    control = DockerSdkControl(engines=FakeProvider(engines=engines))
    executor = PlanExecutor(processes=FakeProcesses(), containers=control, owner_uid=OWNER_UID)
    return executor, tuple(engine.identity for engine in engines)


def _podman_only(*held: PodmanContainer) -> tuple[PlanExecutor, tuple[EngineIdentity, ...]]:
    return _executor(engine_at(path=PODMAN_SOCKET, client=_client(*held)))


def _run(
    *,
    executor: PlanExecutor,
    identities: tuple[EngineIdentity, ...],
    kind: ActionKind,
    container_id: str,
    planned_status: str = "running",
) -> StepOutcome:
    step = container_step(order=1, container_id=container_id, kind=kind, status=planned_status)
    plan = make_plan(steps=[step], engines=identities)
    return executor.execute(plan=plan)[0]
