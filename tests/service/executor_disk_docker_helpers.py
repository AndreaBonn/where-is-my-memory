from tests.service.executor_fakes import (
    OWNER_UID,
    FakeDocker,
    FakeProcesses,
)
from wimm.service.control_protocols import LiveImage
from wimm.service.executor import PlanExecutor

IMAGE_ID = "sha256:" + "a" * 64


OTHER_ID = "sha256:" + "b" * 64


GB = 1_000_000_000


def executor_for(*, docker: FakeDocker | None) -> PlanExecutor:
    return PlanExecutor(processes=FakeProcesses(), containers=docker, owner_uid=OWNER_UID)


def tagged_docker(*tags: str) -> FakeDocker:
    return FakeDocker(images={IMAGE_ID: LiveImage(id=IMAGE_ID, in_use=False, tags=tags)})
