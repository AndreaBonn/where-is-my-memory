import json

import pytest

from tests.core.docker_endpoint_helpers import (
    DEFAULT_SOCKET,
    DESKTOP_DIGEST,
    DESKTOP_SOCKET,
    HOME,
    PODMAN_SOCKET,
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
    resolve_docker_endpoints,
)


def test_default_socket_is_used_when_nothing_is_configured() -> None:
    fixture = Fixture({DEFAULT_SOCKET: sock(DEFAULT_SOCKET)})
    resolution = fixture.resolve()
    assert paths(resolution) == [DEFAULT_SOCKET]
    assert resolution.endpoints[0].source is EndpointSource.DEFAULT_SOCKET
    assert resolution.endpoints[0].url == f"unix://{DEFAULT_SOCKET}"
    assert resolution.rejected == ()


def test_absent_default_socket_yields_nothing_and_no_rejection() -> None:
    resolution = Fixture().resolve()
    assert resolution.endpoints == ()
    assert resolution.rejected == ()


def test_docker_host_unix_in_runtime_dir_is_accepted() -> None:
    runtime_socket = f"{RUNTIME}/docker.sock"
    fixture = Fixture({runtime_socket: sock(runtime_socket)})
    resolution = fixture.resolve(environ={"DOCKER_HOST": f"unix://{runtime_socket}"})
    assert paths(resolution) == [runtime_socket]
    assert resolution.endpoints[0].source is EndpointSource.DOCKER_HOST


@pytest.mark.parametrize(
    "host",
    ["tcp://127.0.0.1:2375", "tcp://10.0.0.5:2376", "ssh://user@server", "npipe:////./pipe/x"],
)
def test_remote_docker_host_is_rejected(host: str) -> None:
    resolution = Fixture().resolve(environ={"DOCKER_HOST": host})
    assert resolution.endpoints == ()
    assert reasons(resolution) == [RejectionReason.UNSUPPORTED_SCHEME]
    assert resolution.rejected[0].source is EndpointSource.DOCKER_HOST
    assert resolution.rejected[0].endpoint == host


def test_rejected_docker_host_does_not_hide_the_default_socket() -> None:
    fixture = Fixture({DEFAULT_SOCKET: sock(DEFAULT_SOCKET)})
    resolution = fixture.resolve(environ={"DOCKER_HOST": "tcp://127.0.0.1:2375"})
    assert paths(resolution) == [DEFAULT_SOCKET]
    assert reasons(resolution) == [RejectionReason.UNSUPPORTED_SCHEME]


@pytest.mark.parametrize(
    "host", ["unix://relative/docker.sock", f"unix://{RUNTIME}/../../etc/x.sock", "unix://"]
)
def test_unix_endpoint_must_be_absolute_and_normalized(host: str) -> None:
    resolution = Fixture().resolve(environ={"DOCKER_HOST": host})
    assert resolution.endpoints == ()
    assert reasons(resolution) == [RejectionReason.PATH_NOT_ABSOLUTE]


def test_socket_outside_allowed_locations_is_rejected() -> None:
    elsewhere = f"{HOME}/.docker/other.sock"
    fixture = Fixture({elsewhere: sock(elsewhere)})
    resolution = fixture.resolve(environ={"DOCKER_HOST": f"unix://{elsewhere}"})
    assert resolution.endpoints == ()
    assert reasons(resolution) == [RejectionReason.LOCATION_NOT_ALLOWED]


def test_rootful_podman_socket_is_never_used() -> None:
    rootful = "/run/podman/podman.sock"
    fixture = Fixture({rootful: sock(rootful)})
    resolution = fixture.resolve(environ={"DOCKER_HOST": f"unix://{rootful}"})
    assert resolution.endpoints == ()
    assert reasons(resolution) == [RejectionReason.LOCATION_NOT_ALLOWED]


def test_default_socket_that_resolves_to_rootful_podman_is_rejected() -> None:
    target = "/run/podman/podman.sock"
    fixture = Fixture({DEFAULT_SOCKET: sock(DEFAULT_SOCKET, realpath=target)})
    resolution = fixture.resolve()
    assert resolution.endpoints == ()
    assert reasons(resolution) == [RejectionReason.LOCATION_NOT_ALLOWED]


def test_symlink_in_runtime_dir_pointing_outside_is_rejected() -> None:
    link = f"{RUNTIME}/docker.sock"
    fixture = Fixture({link: sock(link, realpath="/srv/evil.sock")})
    resolution = fixture.resolve(environ={"DOCKER_HOST": f"unix://{link}"})
    assert resolution.endpoints == ()
    assert reasons(resolution) == [RejectionReason.LOCATION_NOT_ALLOWED]


@pytest.mark.parametrize(
    ("mode", "owned"),
    [
        (0o755, True),
        (0o770, True),
        (0o700, False),
        (0o1700, True),
        (0o2700, True),
        (0o4700, True),
    ],
)
def test_runtime_dir_must_be_private_and_owned(mode: int, owned: bool) -> None:
    fixture = Fixture({PODMAN_SOCKET: sock(PODMAN_SOCKET)})
    fixture.facts[RUNTIME] = runtime_dir(mode=mode, owned=owned)
    resolution = fixture.resolve()
    assert resolution.endpoints == ()
    assert reasons(resolution) == [RejectionReason.RUNTIME_DIR_NOT_PRIVATE]


def test_runtime_dir_private_and_owned_accepts_the_podman_socket() -> None:
    fixture = Fixture({PODMAN_SOCKET: sock(PODMAN_SOCKET)})
    resolution = fixture.resolve()
    assert paths(resolution) == [PODMAN_SOCKET]
    assert resolution.endpoints[0].source is EndpointSource.PODMAN_ROOTLESS


def test_runtime_sockets_are_refused_without_runtime_dir() -> None:
    runtime_socket = f"{RUNTIME}/docker.sock"
    fixture = Fixture({runtime_socket: sock(runtime_socket)})
    resolution = resolve_docker_endpoints(
        environ={"DOCKER_HOST": f"unix://{runtime_socket}"},
        config_json_text=None,
        read_meta=fixture.read_meta,
        socket_facts=fixture.socket_facts,
    )
    assert resolution.endpoints == ()
    assert reasons(resolution) == [RejectionReason.LOCATION_NOT_ALLOWED]


def test_path_that_is_not_a_socket_is_rejected() -> None:
    not_socket = PathFacts(
        exists=True, is_socket=False, realpath=DEFAULT_SOCKET, owned_by_user=True, mode=0o644
    )
    resolution = Fixture({DEFAULT_SOCKET: not_socket}).resolve()
    assert resolution.endpoints == ()
    assert reasons(resolution) == [RejectionReason.NOT_A_SOCKET]


def test_explicit_endpoint_with_missing_socket_is_reported() -> None:
    resolution = Fixture().resolve(environ={"DOCKER_HOST": f"unix://{DESKTOP_SOCKET}"})
    assert resolution.endpoints == ()
    assert reasons(resolution) == [RejectionReason.SOCKET_MISSING]


def test_docker_context_env_reads_meta_by_sha256_of_the_name() -> None:
    fixture = Fixture({DESKTOP_SOCKET: sock(DESKTOP_SOCKET)})
    fixture.meta[DESKTOP_DIGEST] = meta_for(f"unix://{DESKTOP_SOCKET}")
    resolution = fixture.resolve(environ={"DOCKER_CONTEXT": "desktop-linux"})
    assert fixture.meta_calls == [DESKTOP_DIGEST]
    assert paths(resolution) == [DESKTOP_SOCKET]
    assert resolution.endpoints[0].source is EndpointSource.DOCKER_CONTEXT


def test_current_context_from_config_is_resolved_via_meta() -> None:
    fixture = Fixture({DESKTOP_SOCKET: sock(DESKTOP_SOCKET)})
    fixture.meta[DESKTOP_DIGEST] = meta_for(f"unix://{DESKTOP_SOCKET}")
    resolution = fixture.resolve(config=json.dumps({"currentContext": "desktop-linux"}))
    assert paths(resolution) == [DESKTOP_SOCKET]
    assert resolution.endpoints[0].source is EndpointSource.CONFIG_CONTEXT


def test_docker_context_env_takes_precedence_over_config() -> None:
    fixture = Fixture()
    fixture.resolve(
        environ={"DOCKER_CONTEXT": "desktop-linux"},
        config=json.dumps({"currentContext": "other"}),
    )
    assert fixture.meta_calls == [DESKTOP_DIGEST]


def test_candidate_order_is_host_then_context_then_default_then_podman() -> None:
    host_socket = f"{RUNTIME}/host.sock"
    fixture = Fixture(
        {
            host_socket: sock(host_socket),
            DESKTOP_SOCKET: sock(DESKTOP_SOCKET),
            DEFAULT_SOCKET: sock(DEFAULT_SOCKET),
            PODMAN_SOCKET: sock(PODMAN_SOCKET),
        }
    )
    fixture.meta[DESKTOP_DIGEST] = meta_for(f"unix://{DESKTOP_SOCKET}")
    resolution = fixture.resolve(
        environ={"DOCKER_HOST": f"unix://{host_socket}", "DOCKER_CONTEXT": "desktop-linux"}
    )
    assert paths(resolution) == [host_socket, DESKTOP_SOCKET, DEFAULT_SOCKET, PODMAN_SOCKET]


def test_default_context_name_points_to_the_default_socket_not_to_meta() -> None:
    fixture = Fixture({DEFAULT_SOCKET: sock(DEFAULT_SOCKET)})
    resolution = fixture.resolve(config=json.dumps({"currentContext": "default"}))
    assert fixture.meta_calls == []
    assert paths(resolution) == [DEFAULT_SOCKET]
    assert resolution.rejected == ()
