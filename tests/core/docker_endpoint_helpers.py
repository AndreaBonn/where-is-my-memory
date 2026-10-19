import json

from wimm.core.docker_endpoint import (
    EndpointResolution,
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
