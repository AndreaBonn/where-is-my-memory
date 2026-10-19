import re
from collections.abc import Sequence
from typing import cast

import docker.errors

from wimm.collectors.docker_source import (
    ContainerReader,
)


class FakeContainer:
    def __init__(self, state: str = "running") -> None:
        self.id = "abc"
        self.state = {"Status": state, "Pid": 42}
        self.attrs: dict[str, object] = {
            "Name": "/example",
            "Config": {"Image": "image:tag", "Labels": {"project": "demo"}},
            "State": self.state,
            "Mounts": [{"Type": "bind", "Source": "/source", "Destination": "/app"}],
            "NetworkSettings": {"Ports": {"80/tcp": [{"HostPort": "8080"}]}},
        }
        self.calls = 0
        self.failure = False

    def stats(self, stream: bool) -> dict[str, object]:
        assert stream is False
        self.calls += 1
        if self.failure:
            raise docker.errors.DockerException("stats failed")
        return {
            "memory_stats": {"usage": 100, "stats": {"inactive_file": 30}},
            "cpu_stats": {"cpu_usage": {"total_usage": 9000}},
            "networks": {
                "eth0": {"rx_bytes": 10, "tx_bytes": 20},
                "lo": {"rx_bytes": 999, "tx_bytes": 999},
            },
        }


class FakeReader:
    def __init__(self, containers: Sequence[FakeContainer] = ()) -> None:
        self.items = list(containers)
        self.containers = self
        self.failure = False

    def list(self, *, all: bool, ignore_removed: bool) -> Sequence[ContainerReader]:
        assert all is True and ignore_removed is True
        if self.failure:
            raise docker.errors.DockerException("socket denied")
        return [cast(ContainerReader, item) for item in self.items]


def _docker_memory_rows(output: str) -> dict[str, float]:
    units = {
        "B": 1,
        "kB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
        "KiB": 1024,
        "MiB": 1024**2,
        "GiB": 1024**3,
    }
    expected: dict[str, float] = {}
    for line in output.splitlines():
        identifier, memory, *_ = line.split()
        match = re.fullmatch(pattern=r"([\d.]+)([A-Za-z]+)", string=memory)
        assert match is not None
        expected[identifier] = float(match[1]) * units[match[2]]
    return expected
