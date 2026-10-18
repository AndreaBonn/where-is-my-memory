"""The container executor against a Podman engine reached through its Docker-compatible API.

Podman is not installed on the development machine, so these tests drive the real
`PlanExecutor` and `DockerSdkControl` with a fake SDK client that answers the way Podman's
compat API does. The real run on a real Podman is manual check M-24 (docs/DELIVERY_REPORT.md).

Differences from Docker that the fake reproduces. Source: Podman API reference, swagger
5.0.0 (storage.googleapis.com/libpod-master-releases/swagger-latest.yaml) and
`libpod/define/containerstate.go` on the main branch of github.com/containers/podman.

* States. Podman reports `created` (its internal "configured"), `initialized` (created in the
  OCI runtime, not started; Docker has no such state), `running`, `stopped` (stopped, not yet
  cleaned up), `paused`, `exited`, `removing` and `stopping`. Docker only has `created`,
  `running`, `paused`, `restarting`, `removing`, `exited` and `dead`. After a stop Docker says
  `exited`; Podman can say `stopped` first. Only running, paused and restarting are stoppable.
* Stop of a container that is already stopped: `POST /containers/{name}/stop` answers 304 (also
  in Docker). docker-py does not raise on a 304, so the call returns normally.
* Unknown container: 404 on stop, inspect and delete, which docker-py raises as `NotFound`.
* Remove: `DELETE /containers/{name}` answers 409 on a conflict, for instance a container that
  is still running and was not forced. UNVERIFIED: the exact wording of the 409 message comes
  from training data; the swagger only lists the status code.
* Podman's `/info` is the libpod one (`host`, `store`, `version`...), while the compat `/info`
  carries Docker-style fields; engine identity here comes from the socket (`EngineIdentity`),
  not from `/info`, so the executor does not depend on that difference.
* The fake containers expose only `id`, `status`, `stop`, `start` and `remove`: no `attrs`.
  Podman's inspect lacks or reshapes some Docker fields (UNVERIFIED which ones, not listed by
  the swagger), so the executor must not read anything else.
"""

from dataclasses import dataclass, field

import docker.errors
import pytest

from tests.service.engine_fakes import FakeProvider, engine_at
from tests.service.executor_fakes import OWNER_UID, FakeProcesses, container_step, make_plan
from wimm.collectors.docker_engines import Engine
from wimm.core.constants import CONTAINER_STOP_TIMEOUT_S
from wimm.model.actions import EngineIdentity
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import StepOutcome, StepStatus
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


def test_stop_of_a_running_podman_container_is_done_with_the_stop_timeout() -> None:
    container = PodmanContainer(id=PODMAN_ID)
    executor, identities = _podman_only(container)

    outcome = _run(executor=executor, identities=identities, kind=STOP, container_id=PODMAN_ID)

    assert outcome.status is StepStatus.DONE
    assert container.calls == [f"stop:{CONTAINER_STOP_TIMEOUT_S}"]
    assert container.status == "exited"


def test_stop_of_a_paused_podman_container_is_done() -> None:
    container = PodmanContainer(id=PODMAN_ID, status="paused")
    executor, identities = _podman_only(container)

    outcome = _run(
        executor=executor,
        identities=identities,
        kind=STOP,
        container_id=PODMAN_ID,
        planned_status="paused",
    )

    assert outcome.status is StepStatus.DONE
    assert container.calls == [f"stop:{CONTAINER_STOP_TIMEOUT_S}"]


@pytest.mark.parametrize("state", [*NOT_RUNNING_STATES, "stopping", "removing"])
def test_stop_of_a_podman_container_that_is_not_running_is_already_gone(state: str) -> None:
    # Podman has `stopped`, `initialized` and `stopping`, which Docker never reports.
    container = PodmanContainer(id=PODMAN_ID, status=state)
    executor, identities = _podman_only(container)

    outcome = _run(
        executor=executor,
        identities=identities,
        kind=STOP,
        container_id=PODMAN_ID,
        planned_status=state,
    )

    assert outcome.status is StepStatus.ALREADY_GONE
    assert container.calls == []


def test_stop_that_podman_answers_with_304_counts_as_done() -> None:
    # The container exited between the inspect and the stop: Podman says 304, docker-py returns.
    container = PodmanContainer(id=PODMAN_ID, stop_arrives_late=True)
    executor, identities = _podman_only(container)

    outcome = _run(executor=executor, identities=identities, kind=STOP, container_id=PODMAN_ID)

    assert outcome.status is StepStatus.DONE
    assert container.calls == [f"stop:{CONTAINER_STOP_TIMEOUT_S}"]


@pytest.mark.parametrize("state", NOT_RUNNING_STATES)
def test_remove_of_a_podman_container_that_is_not_running_keeps_the_volumes(state: str) -> None:
    container = PodmanContainer(id=PODMAN_ID, status=state)
    executor, identities = _podman_only(container)

    outcome = _run(
        executor=executor,
        identities=identities,
        kind=REMOVE,
        container_id=PODMAN_ID,
        planned_status=state,
    )

    assert outcome.status is StepStatus.DONE
    assert container.calls == ["remove:False"]


@pytest.mark.parametrize("state", RUNNING_LIKE)
def test_remove_of_a_live_podman_container_is_refused_without_calling_the_engine(
    state: str,
) -> None:
    container = PodmanContainer(id=PODMAN_ID, status=state)
    executor, identities = _podman_only(container)

    outcome = _run(
        executor=executor,
        identities=identities,
        kind=REMOVE,
        container_id=PODMAN_ID,
        planned_status=state,
    )

    assert outcome.status is StepStatus.FAILED
    assert outcome.message is not None and state in outcome.message
    assert container.calls == []


def test_remove_that_podman_refuses_with_409_is_a_failed_step_with_the_engine_message() -> None:
    # `stopping` is not stoppable for the executor, so the remove goes through to the engine,
    # which answers 409: the step fails cleanly instead of raising.
    container = PodmanContainer(id=PODMAN_ID, status="stopping")
    executor, identities = _podman_only(container)

    outcome = _run(
        executor=executor,
        identities=identities,
        kind=REMOVE,
        container_id=PODMAN_ID,
        planned_status="stopping",
    )

    assert outcome.status is StepStatus.FAILED
    assert outcome.message is not None and "container state improper" in outcome.message
    assert container.calls == ["remove:False"]


@pytest.mark.parametrize("kind", [STOP, REMOVE])
def test_container_gone_between_plan_and_execution_is_already_gone(kind: ActionKind) -> None:
    # Podman answers 404 `no such container`, which the SDK raises as NotFound.
    executor, identities = _podman_only()

    outcome = _run(executor=executor, identities=identities, kind=kind, container_id=PODMAN_ID)

    assert outcome.status is StepStatus.ALREADY_GONE


def test_container_that_vanishes_during_the_remove_call_is_not_a_failure() -> None:
    class Vanishing(PodmanContainer):
        def remove(self, *, v: bool) -> None:
            self.calls.append(f"remove:{v}")
            raise docker.errors.NotFound("no such container")

    container = Vanishing(id=PODMAN_ID, status="exited")
    executor, identities = _podman_only(container)

    outcome = _run(
        executor=executor,
        identities=identities,
        kind=REMOVE,
        container_id=PODMAN_ID,
        planned_status="exited",
    )

    assert outcome.status in (StepStatus.DONE, StepStatus.ALREADY_GONE)
    assert container.calls == ["remove:False"]


@pytest.mark.parametrize("podman_first", [True, False])
def test_with_docker_and_podman_the_stop_goes_to_the_engine_that_has_the_id(
    podman_first: bool,
) -> None:
    on_podman = PodmanContainer(id=PODMAN_ID)
    on_docker = PodmanContainer(id=DOCKER_ID)
    podman = engine_at(path=PODMAN_SOCKET, client=_client(on_podman))
    docker_engine = engine_at(path=DOCKER_SOCKET, client=_client(on_docker))
    engines = (podman, docker_engine) if podman_first else (docker_engine, podman)
    executor, identities = _executor(*engines)

    outcome = _run(executor=executor, identities=identities, kind=STOP, container_id=PODMAN_ID)

    assert outcome.status is StepStatus.DONE
    assert on_podman.calls == [f"stop:{CONTAINER_STOP_TIMEOUT_S}"]
    assert on_docker.calls == []


def test_with_docker_and_podman_the_remove_goes_to_the_docker_engine_when_it_has_the_id() -> None:
    on_podman = PodmanContainer(id=PODMAN_ID, status="exited")
    on_docker = PodmanContainer(id=DOCKER_ID, status="exited")
    engines = (
        engine_at(path=PODMAN_SOCKET, client=_client(on_podman)),
        engine_at(path=DOCKER_SOCKET, client=_client(on_docker)),
    )
    executor, identities = _executor(*engines)

    outcome = _run(
        executor=executor,
        identities=identities,
        kind=REMOVE,
        container_id=DOCKER_ID,
        planned_status="exited",
    )

    assert outcome.status is StepStatus.DONE
    assert on_docker.calls == ["remove:False"]
    assert on_podman.calls == []


def test_with_docker_and_podman_an_id_that_neither_has_touches_neither() -> None:
    on_podman = PodmanContainer(id=PODMAN_ID)
    on_docker = PodmanContainer(id=DOCKER_ID)
    engines = (
        engine_at(path=PODMAN_SOCKET, client=_client(on_podman)),
        engine_at(path=DOCKER_SOCKET, client=_client(on_docker)),
    )
    executor, identities = _executor(*engines)

    outcome = _run(executor=executor, identities=identities, kind=STOP, container_id="c" * 64)

    assert outcome.status is StepStatus.ALREADY_GONE
    assert on_podman.calls == [] and on_docker.calls == []
