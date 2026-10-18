import json
import re

import pytest

from wimm.core.docker_endpoint import (
    EndpointResolution,
    EndpointSource,
    PathFacts,
    RejectionReason,
    resolve_docker_endpoints,
)

RUNTIME = "/run/user/1000"
DESKTOP_DIGEST = "fe9c6bd7a66301f49ca9b6a70b217107cd1284598bfc254700c989b916da791e"
DEFAULT_SOCKET = "/var/run/docker.sock"
RUN_SOCKET = "/run/docker.sock"
PODMAN_SOCKET = f"{RUNTIME}/podman/podman.sock"
HOME = "/home/user"
DESKTOP_SOCKET = f"{HOME}/.docker/desktop/docker.sock"


def sock(path: str, *, realpath: str | None = None) -> PathFacts:
    return PathFacts(
        exists=True, is_socket=True, realpath=realpath or path, owned_by_user=True, mode=0o755
    )


def runtime_dir(*, mode: int = 0o700, owned: bool = True) -> PathFacts:
    return PathFacts(exists=True, is_socket=False, realpath=RUNTIME, owned_by_user=owned, mode=mode)


class Fixture:
    def __init__(self, facts: dict[str, PathFacts] | None = None) -> None:
        self.facts = {RUNTIME: runtime_dir(), **(facts or {})}
        self.meta: dict[str, str] = {}
        self.meta_calls: list[str] = []

    def read_meta(self, digest: str) -> str | None:
        self.meta_calls.append(digest)
        return self.meta.get(digest)

    def socket_facts(self, path: str) -> PathFacts:
        return self.facts.get(
            path,
            PathFacts(exists=False, is_socket=False, realpath=path, owned_by_user=False, mode=0),
        )

    def resolve(
        self, *, environ: dict[str, str] | None = None, config: str | None = None
    ) -> EndpointResolution:
        env = {"XDG_RUNTIME_DIR": RUNTIME, "HOME": HOME, **(environ or {})}
        return resolve_docker_endpoints(
            environ=env,
            config_json_text=config,
            read_meta=self.read_meta,
            socket_facts=self.socket_facts,
        )


def paths(resolution: EndpointResolution) -> list[str]:
    return [endpoint.path for endpoint in resolution.endpoints]


def reasons(resolution: EndpointResolution) -> list[RejectionReason]:
    return [rejected.reason for rejected in resolution.rejected]


def meta_for(host: str) -> str:
    return json.dumps({"Name": "x", "Endpoints": {"docker": {"Host": host}}})


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


@pytest.mark.parametrize(("mode", "owned"), [(0o755, True), (0o770, True), (0o700, False)])
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
