import json
import re

import pytest

from tests.core.docker_endpoint_helpers import (
    DEFAULT_SOCKET,
    DESKTOP_DIGEST,
    DESKTOP_SOCKET,
    HOME,
    PODMAN_SOCKET,
    RUN_SOCKET,
    RUNTIME,
    Fixture,
    meta_for,
    paths,
    reasons,
    runtime_dir,
    sock,
)
from wimm.core.docker_endpoint import (
    EndpointSource,
    PathFacts,
    RejectionReason,
)


def test_unknown_context_is_reported() -> None:
    resolution = Fixture().resolve(environ={"DOCKER_CONTEXT": "ghost"})
    assert reasons(resolution) == [RejectionReason.CONTEXT_NOT_FOUND]


@pytest.mark.parametrize(
    "text",
    ["not json", "[]", json.dumps({"Endpoints": {}}), json.dumps({"Endpoints": {"docker": {}}})],
)
def test_malformed_meta_is_reported(text: str) -> None:
    fixture = Fixture()
    fixture.meta[DESKTOP_DIGEST] = text
    resolution = fixture.resolve(environ={"DOCKER_CONTEXT": "desktop-linux"})
    assert reasons(resolution) == [RejectionReason.CONTEXT_INVALID]


def test_context_pointing_to_tcp_is_rejected() -> None:
    fixture = Fixture()
    fixture.meta[DESKTOP_DIGEST] = meta_for("tcp://10.0.0.5:2376")
    resolution = fixture.resolve(environ={"DOCKER_CONTEXT": "desktop-linux"})
    assert resolution.endpoints == ()
    assert reasons(resolution) == [RejectionReason.UNSUPPORTED_SCHEME]
    assert resolution.rejected[0].source is EndpointSource.DOCKER_CONTEXT


@pytest.mark.parametrize("name", ["../../etc/passwd", "a/b", "ünï", "x" * 500])
def test_context_name_reaches_the_reader_only_as_a_sha256_digest(name: str) -> None:
    fixture = Fixture()
    fixture.resolve(environ={"DOCKER_CONTEXT": name})
    assert len(fixture.meta_calls) == 1
    assert re.fullmatch(r"[0-9a-f]{64}", fixture.meta_calls[0])


@pytest.mark.parametrize("config", ["not json", "[]", json.dumps({"currentContext": 3})])
def test_unusable_config_is_ignored_without_failing(config: str) -> None:
    fixture = Fixture({DEFAULT_SOCKET: sock(DEFAULT_SOCKET)})
    resolution = fixture.resolve(config=config)
    assert paths(resolution) == [DEFAULT_SOCKET]
    assert fixture.meta_calls == []


def test_docker_host_equal_to_the_default_is_listed_once() -> None:
    fixture = Fixture({DEFAULT_SOCKET: sock(DEFAULT_SOCKET)})
    resolution = fixture.resolve(environ={"DOCKER_HOST": f"unix://{DEFAULT_SOCKET}"})
    assert paths(resolution) == [DEFAULT_SOCKET]
    assert resolution.endpoints[0].source is EndpointSource.DOCKER_HOST


def test_sockets_with_the_same_realpath_are_listed_once() -> None:
    fixture = Fixture(
        {
            DEFAULT_SOCKET: sock(DEFAULT_SOCKET, realpath=RUN_SOCKET),
            RUN_SOCKET: sock(RUN_SOCKET),
        }
    )
    resolution = fixture.resolve()
    assert paths(resolution) == [DEFAULT_SOCKET]
    assert resolution.endpoints[0].realpath == RUN_SOCKET


def test_docker_host_pointing_at_podman_is_not_listed_twice() -> None:
    fixture = Fixture({PODMAN_SOCKET: sock(PODMAN_SOCKET)})
    resolution = fixture.resolve(environ={"DOCKER_HOST": f"unix://{PODMAN_SOCKET}"})
    assert paths(resolution) == [PODMAN_SOCKET]


def test_docker_desktop_socket_in_home_is_accepted() -> None:
    fixture = Fixture({DESKTOP_SOCKET: sock(DESKTOP_SOCKET)})
    resolution = fixture.resolve(environ={"DOCKER_HOST": f"unix://{DESKTOP_SOCKET}"})
    assert paths(resolution) == [DESKTOP_SOCKET]


def test_docker_desktop_socket_owned_by_another_uid_is_rejected() -> None:
    foreign = PathFacts(
        exists=True, is_socket=True, realpath=DESKTOP_SOCKET, owned_by_user=False, mode=0o755
    )
    resolution = Fixture({DESKTOP_SOCKET: foreign}).resolve(
        environ={"DOCKER_HOST": f"unix://{DESKTOP_SOCKET}"}
    )
    assert resolution.endpoints == ()
    assert reasons(resolution) == [RejectionReason.LOCATION_NOT_ALLOWED]


def test_docker_desktop_path_that_resolves_elsewhere_is_rejected() -> None:
    fixture = Fixture({DESKTOP_SOCKET: sock(DESKTOP_SOCKET, realpath=f"{HOME}/.docker/x.sock")})
    resolution = fixture.resolve(environ={"DOCKER_HOST": f"unix://{DESKTOP_SOCKET}"})
    assert resolution.endpoints == ()
    assert reasons(resolution) == [RejectionReason.LOCATION_NOT_ALLOWED]


def test_symlink_to_the_docker_desktop_socket_from_elsewhere_is_rejected() -> None:
    link = f"{HOME}/.docker/link.sock"
    fixture = Fixture({link: sock(link, realpath=DESKTOP_SOCKET)})
    resolution = fixture.resolve(environ={"DOCKER_HOST": f"unix://{link}"})
    assert resolution.endpoints == ()
    assert reasons(resolution) == [RejectionReason.LOCATION_NOT_ALLOWED]


def test_docker_desktop_socket_needs_a_valid_home() -> None:
    fixture = Fixture({DESKTOP_SOCKET: sock(DESKTOP_SOCKET)})
    for home in ("", "relative", "/home/../home/user"):
        resolution = fixture.resolve(
            environ={"HOME": home, "DOCKER_HOST": f"unix://{DESKTOP_SOCKET}"}
        )
        assert resolution.endpoints == ()
        assert reasons(resolution) == [RejectionReason.LOCATION_NOT_ALLOWED]


def test_missing_docker_desktop_socket_is_reported_as_missing() -> None:
    resolution = Fixture().resolve(environ={"DOCKER_HOST": f"unix://{DESKTOP_SOCKET}"})
    assert reasons(resolution) == [RejectionReason.SOCKET_MISSING]


def test_docker_desktop_socket_under_a_symlinked_home_is_accepted() -> None:
    # /home is often a link to a data disk: the socket resolves under the real home.
    real_home = "/data/home/user"
    home_facts = PathFacts(
        exists=True, is_socket=False, realpath=real_home, owned_by_user=True, mode=0o755
    )
    real_socket = f"{real_home}/.docker/desktop/docker.sock"
    fixture = Fixture(
        {HOME: home_facts, DESKTOP_SOCKET: sock(DESKTOP_SOCKET, realpath=real_socket)}
    )
    resolution = fixture.resolve(environ={"DOCKER_HOST": f"unix://{DESKTOP_SOCKET}"})
    assert paths(resolution) == [DESKTOP_SOCKET]
    elsewhere = sock(DESKTOP_SOCKET, realpath=f"{real_home}/.docker/x.sock")
    other = Fixture({HOME: home_facts, DESKTOP_SOCKET: elsewhere})
    assert other.resolve(environ={"DOCKER_HOST": f"unix://{DESKTOP_SOCKET}"}).endpoints == ()


def test_docker_host_in_a_sibling_runtime_dir_of_another_user_is_rejected() -> None:
    other = "/run/user/10001/docker.sock"  # shares the "/run/user/1000" prefix, other user
    fixture = Fixture({other: sock(other)})
    resolution = fixture.resolve(environ={"DOCKER_HOST": f"unix://{other}"})
    assert other not in paths(resolution)
    assert RejectionReason.LOCATION_NOT_ALLOWED in reasons(resolution)


def test_default_socket_resolving_into_a_non_private_runtime_dir_is_rejected() -> None:
    target = f"{RUNTIME}/docker.sock"
    fixture = Fixture(
        {
            RUNTIME: runtime_dir(mode=0o755),
            DEFAULT_SOCKET: sock(DEFAULT_SOCKET, realpath=target),
        }
    )
    resolution = fixture.resolve()
    assert DEFAULT_SOCKET not in paths(resolution)
    assert RejectionReason.RUNTIME_DIR_NOT_PRIVATE in reasons(resolution)


def test_default_socket_resolving_into_a_private_runtime_dir_is_accepted() -> None:
    target = f"{RUNTIME}/docker.sock"
    fixture = Fixture({DEFAULT_SOCKET: sock(DEFAULT_SOCKET, realpath=target)})
    resolution = fixture.resolve()
    assert paths(resolution) == [DEFAULT_SOCKET]


def test_nul_in_the_socket_path_is_not_a_valid_path() -> None:
    resolution = Fixture().resolve(environ={"DOCKER_HOST": f"unix://{RUNTIME}/docker\0.sock"})

    assert resolution.endpoints == ()
    assert reasons(resolution) == [RejectionReason.PATH_NOT_ABSOLUTE]


@pytest.mark.parametrize(
    "runtime", ["", "run/user/1000", "/run/user/1000/", "/run/user/../user/1000", "/run//user/1000"]
)
def test_a_runtime_dir_that_is_relative_or_not_normalized_gets_no_podman_candidate(
    runtime: str,
) -> None:
    podman = f"{runtime}/podman/podman.sock"
    fixture = Fixture({podman: sock(podman), runtime: runtime_dir()})

    resolution = fixture.resolve(environ={"XDG_RUNTIME_DIR": runtime})

    assert resolution.endpoints == ()
    assert resolution.rejected == ()


@pytest.mark.parametrize(
    ("home", "desktop"),
    [
        ("/", "/.docker/desktop/docker.sock"),
        ("/home/user/", DESKTOP_SOCKET),
        ("/home/./user", DESKTOP_SOCKET),
    ],
)
def test_docker_desktop_socket_is_refused_when_home_is_root_or_not_normalized(
    home: str, desktop: str
) -> None:
    fixture = Fixture({desktop: sock(desktop)})

    resolution = fixture.resolve(environ={"HOME": home, "DOCKER_HOST": f"unix://{desktop}"})

    assert resolution.endpoints == ()
    assert reasons(resolution) == [RejectionReason.LOCATION_NOT_ALLOWED]
