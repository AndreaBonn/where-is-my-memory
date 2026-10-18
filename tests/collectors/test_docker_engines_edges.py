import docker.errors

from tests.collectors.test_docker_engines import DOCKER, FakeClient, Rig
from wimm.collectors import docker_engines
from wimm.core.docker_notices import NoticeCode
from wimm.model.actions import EngineIdentity


class RefusingRig(Rig):
    """A pool whose connect() itself fails, before any client exists to close."""

    def connect(self, found: object) -> FakeClient:
        self.connects.append(found.path)  # type: ignore[attr-defined]
        raise docker.errors.DockerException("cannot create the client")


def test_discarding_an_engine_the_pool_does_not_know_closes_nothing() -> None:
    client = FakeClient("docker-id")
    rig = Rig({DOCKER: client}, (DOCKER,))
    known = rig.pool.refresh().engines[0]
    stranger_client = FakeClient("stranger")
    stranger = docker_engines.Engine(
        client=stranger_client,
        engine_id="stranger",
        identity=EngineIdentity(path="/elsewhere.sock", st_ino=99, st_dev=1),
    )

    rig.pool.discard(engine=stranger)

    assert (stranger_client.close_calls, client.close_calls) == (0, 0)
    assert rig.pool.refresh().engines == (known,)
    assert rig.connects == [DOCKER]

    rig.pool.discard(engine=known)  # the known one is forgotten and its client closed

    assert client.close_calls == 1
    assert len(rig.pool.refresh().engines) == 1
    assert rig.connects == [DOCKER, DOCKER]


def test_a_connect_that_fails_is_a_notice_and_enters_the_backoff() -> None:
    rig = RefusingRig({}, (DOCKER,))

    view = rig.pool.refresh()
    again = rig.pool.refresh()

    assert view.engines == () and again.engines == ()
    (notice,) = view.notices
    assert (notice.code, notice.endpoint) == (NoticeCode.UNREACHABLE, DOCKER)
    assert "cannot create the client" in notice.detail
    assert rig.connects == [DOCKER]  # the second refresh is inside the backoff
    assert [item.code for item in again.notices] == [NoticeCode.UNREACHABLE]
