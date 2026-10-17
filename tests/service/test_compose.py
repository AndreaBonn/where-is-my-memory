import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import docker.errors
import pytest

from wimm.service.compose import DockerComposeControl, resolve_docker_binary
from wimm.service.errors import ControlFailed, InvalidRequest

DOCKER = "/usr/bin/docker"
PROJECT = "wimmtest-demo"


@dataclass(slots=True)
class FakeRunner:
    returncode: int = 0
    stderr: str = ""
    raises: Exception | None = None
    calls: list[tuple[list[str], dict[str, Any]]] = field(default_factory=list)

    def __call__(self, args: Sequence[str], **kwargs: Any) -> "subprocess.CompletedProcess[str]":
        self.calls.append((list(args), kwargs))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(
            args=list(args), returncode=self.returncode, stdout="", stderr=self.stderr
        )


@dataclass(slots=True)
class FakeContainer:
    id: str


@dataclass(slots=True)
class FakeContainers:
    by_label: dict[str, list[str]] = field(default_factory=dict)
    error: Exception | None = None
    filters_seen: list[dict[str, str]] = field(default_factory=list)

    def list(self, *, all: bool, filters: dict[str, str]) -> list[FakeContainer]:
        assert all is True
        if self.error is not None:
            raise self.error
        self.filters_seen.append(filters)
        return [FakeContainer(id=i) for i in self.by_label.get(filters["label"], [])]


@dataclass(slots=True)
class FakeClient:
    containers: FakeContainers = field(default_factory=FakeContainers)


def control(*, runner: FakeRunner, client: FakeClient | None = None) -> DockerComposeControl:
    return DockerComposeControl(client=client or FakeClient(), docker_bin=DOCKER, runner=runner)


def test_down_runs_the_exact_argv_with_timeout_and_no_shell() -> None:
    runner = FakeRunner()

    control(runner=runner).down(project=PROJECT, volumes=False)

    [(argv, kwargs)] = runner.calls
    # --context default: the daemon the SDK reads (DOCKER_HOST or the default socket).
    assert argv == [DOCKER, "--context", "default", "compose", "-p", PROJECT, "down"]
    assert kwargs["check"] is False
    assert kwargs["errors"] == "replace"
    assert kwargs["timeout"] == 120
    assert not kwargs.get("shell", False)
    assert Path(kwargs["cwd"]) == Path("/")


def test_down_with_volumes_adds_the_v_flag() -> None:
    runner = FakeRunner()

    control(runner=runner).down(project=PROJECT, volumes=True)

    assert runner.calls[0][0][-2:] == ["down", "-v"]


def test_nonzero_returncode_raises_with_stderr() -> None:
    runner = FakeRunner(returncode=1, stderr="network wimmtest-demo_default has active endpoints")

    with pytest.raises(ControlFailed, match="active endpoints"):
        control(runner=runner).down(project=PROJECT, volumes=False)


def test_timeout_raises_control_failed() -> None:
    runner = FakeRunner(raises=subprocess.TimeoutExpired(cmd="docker", timeout=120))

    with pytest.raises(ControlFailed, match="120"):
        control(runner=runner).down(project=PROJECT, volumes=False)


def test_missing_binary_at_run_time_raises_control_failed() -> None:
    runner = FakeRunner(raises=FileNotFoundError("docker"))

    with pytest.raises(ControlFailed):
        control(runner=runner).down(project=PROJECT, volumes=False)


@pytest.mark.parametrize("project", ["-f", "--help", "", "a b", "A;b", "../x", "x\n", "-p"])
def test_project_name_that_is_not_a_compose_name_never_reaches_the_runner(project: str) -> None:
    runner = FakeRunner()

    with pytest.raises(InvalidRequest):
        control(runner=runner).down(project=project, volumes=False)

    assert runner.calls == []


@pytest.mark.parametrize("project", ["demo", "my-app_2", "0proj"])
def test_valid_compose_project_names_are_accepted(project: str) -> None:
    runner = FakeRunner()

    control(runner=runner).down(project=project, volumes=False)

    argv = runner.calls[0][0]
    assert argv[argv.index("-p") + 1] == project


def test_container_ids_filters_on_the_compose_project_label() -> None:
    client = FakeClient(
        containers=FakeContainers(
            by_label={"com.docker.compose.project=demo": ["c1", "c2"], "x=y": ["other"]}
        )
    )

    ids = control(runner=FakeRunner(), client=client).container_ids(project="demo")

    assert ids == frozenset({"c1", "c2"})
    assert client.containers.filters_seen == [{"label": "com.docker.compose.project=demo"}]


def test_container_ids_of_unknown_project_is_empty() -> None:
    assert control(runner=FakeRunner()).container_ids(project="ghost") == frozenset()


def test_container_ids_wraps_sdk_errors() -> None:
    client = FakeClient(containers=FakeContainers(error=docker.errors.APIError("daemon down")))

    with pytest.raises(ControlFailed, match="daemon down"):
        control(runner=FakeRunner(), client=client).container_ids(project="demo")


def test_container_ids_rejects_an_invalid_project_name() -> None:
    client = FakeClient()

    with pytest.raises(InvalidRequest):
        control(runner=FakeRunner(), client=client).container_ids(project="-f")

    assert client.containers.filters_seen == []


def test_resolve_docker_binary_returns_the_path_found() -> None:
    assert resolve_docker_binary(which=lambda name: f"/opt/{name}") == "/opt/docker"


def test_resolve_docker_binary_without_docker_raises_a_clear_error() -> None:
    with pytest.raises(ControlFailed, match="docker"):
        resolve_docker_binary(which=lambda name: None)


def test_down_runs_without_compose_variables_or_a_selected_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("COMPOSE_FILE", "COMPOSE_PROJECT_NAME", "COMPOSE_PROFILES", "DOCKER_CONTEXT"):
        monkeypatch.setenv(name, "from-the-user-shell")
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1000/docker.sock")
    runner = FakeRunner()

    control(runner=runner).down(project=PROJECT, volumes=False)

    env = runner.calls[0][1]["env"]
    assert not {"COMPOSE_FILE", "COMPOSE_PROJECT_NAME", "COMPOSE_PROFILES", "DOCKER_CONTEXT"} & set(
        env
    )
    # Positive pair: what the SDK also reads is kept, so both talk to the same daemon.
    assert env["DOCKER_HOST"] == "unix:///run/user/1000/docker.sock"


def test_failed_down_redacts_secrets_in_the_stderr_tail() -> None:
    runner = FakeRunner(returncode=1, stderr="pull https://user:hunter2@registry.example/x failed")

    with pytest.raises(ControlFailed) as raised:
        control(runner=runner).down(project=PROJECT, volumes=False)

    assert "hunter2" not in str(raised.value)
    assert "registry.example" in str(raised.value)  # positive pair: the tail is still there
