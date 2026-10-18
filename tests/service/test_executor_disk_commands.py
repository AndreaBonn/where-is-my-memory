"""The native cleaning command of each cache tool, run through a fake runner only (R14, R15)."""

import logging
from dataclasses import replace
from pathlib import Path

import pytest

from tests.service.fs_fakes import FsRig, build_rig, dir_plan, make_cache
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import StepStatus
from wimm.service.errors import ProtectedTarget
from wimm.service.fs_controls import CommandResult

CLEAN = ActionKind.CACHE_CLEAN
BASE_ENV = {"PATH": "/usr/bin", "HOME": "/home/x", "LANG": "C.UTF-8"}


@pytest.fixture
def rig(tmp_path: Path) -> FsRig:
    return build_rig(home=tmp_path / "home")


@pytest.fixture
def stranger_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A known base environment plus variables that would steer a tool away or run code."""
    for name, value in BASE_ENV.items():
        monkeypatch.setenv(name, value)
    for name in ("GOFLAGS", "GOENV", "YARN_RC_FILENAME", "CONDARC", "PNPM_HOME", "LD_PRELOAD"):
        monkeypatch.setenv(name, "/elsewhere")


def clean(*, rig: FsRig, relative: str) -> tuple[Path, StepStatus]:
    folder = make_cache(home=rig.home, relative=relative)
    outcome = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))[0]
    return folder, outcome.status


def test_cache_argv_go_module_cache_runs_go_clean_modcache_aimed_by_gomodcache(
    rig: FsRig, stranger_env: None
) -> None:
    folder, status = clean(rig=rig, relative="go/pkg/mod")

    assert status is StepStatus.DONE
    assert rig.runner.calls == [("/usr/bin/go", "clean", "-modcache")]
    assert rig.runner.envs == [{**BASE_ENV, "GOMODCACHE": str(folder)}]
    assert (folder / "a.bin").exists()


def test_cache_argv_go_build_cache_runs_go_clean_cache_aimed_by_gocache(
    rig: FsRig, stranger_env: None
) -> None:
    folder, status = clean(rig=rig, relative=".cache/go-build")

    assert status is StepStatus.DONE
    assert rig.runner.calls == [("/usr/bin/go", "clean", "-cache")]
    assert rig.runner.envs == [{**BASE_ENV, "GOCACHE": str(folder)}]


def test_cache_argv_go_build_without_go_is_emptied_instead(tmp_path: Path) -> None:
    rig = build_rig(home=tmp_path / "home", missing=("go",))

    folder, status = clean(rig=rig, relative=".cache/go-build")

    assert status is StepStatus.DONE
    assert rig.runner.calls == []
    assert folder.is_dir() and list(folder.iterdir()) == []


def test_cache_argv_pnpm_yarn_conda(rig: FsRig, stranger_env: None) -> None:
    pnpm, _ = clean(rig=rig, relative=".local/share/pnpm/store")
    yarn, _ = clean(rig=rig, relative=".cache/yarn")
    conda, _ = clean(rig=rig, relative=".conda/pkgs")

    assert rig.runner.calls == [
        ("/usr/bin/pnpm", "store", "prune", "--store-dir", str(pnpm)),
        ("/usr/bin/yarn", "cache", "clean"),
        ("/usr/bin/conda", "clean", "--packages", "--tarballs", "--yes"),
    ]
    assert rig.runner.envs == [
        BASE_ENV,
        {**BASE_ENV, "YARN_CACHE_FOLDER": str(yarn)},
        {**BASE_ENV, "CONDA_PKGS_DIRS": str(conda)},
    ]


@pytest.mark.parametrize(
    "relative", [".local/share/pnpm/store", ".cache/yarn", ".conda/pkgs", ".cache/uv"]
)
def test_cache_argv_tool_missing_empties_the_folder_instead(tmp_path: Path, relative: str) -> None:
    rig = build_rig(home=tmp_path / "home", missing=("pnpm", "yarn", "conda", "uv"))

    folder, status = clean(rig=rig, relative=relative)

    assert status is StepStatus.DONE
    assert rig.runner.calls == []
    assert folder.is_dir() and list(folder.iterdir()) == []


def test_cache_env_for_uv_has_no_variable_that_would_aim_the_tool(
    rig: FsRig, stranger_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UV_CACHE_DIR", "/elsewhere")

    clean(rig=rig, relative=".cache/uv")

    assert rig.runner.envs == [BASE_ENV]


def test_cache_env_for_go_drops_goflags_and_the_go_env_file(rig: FsRig, stranger_env: None) -> None:
    clean(rig=rig, relative="go/pkg/mod")

    (env,) = rig.runner.envs
    assert env is not None
    assert "GOFLAGS" not in env and "GOENV" not in env and "LD_PRELOAD" not in env


def test_cache_env_for_yarn_drops_the_rc_file_variable(rig: FsRig, stranger_env: None) -> None:
    folder, _ = clean(rig=rig, relative=".cache/yarn")

    (env,) = rig.runner.envs
    assert env is not None
    assert "YARN_RC_FILENAME" not in env
    assert env["YARN_CACHE_FOLDER"] == str(folder)


def test_the_go_module_cache_is_refused_without_go_and_no_command_runs(tmp_path: Path) -> None:
    rig = build_rig(home=tmp_path / "home", missing=("go",))
    folder = make_cache(home=rig.home, relative="go/pkg/mod")

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))
    assert rig.runner.calls == [] and (folder / "a.bin").exists()


# --- hardening of the native commands (security review of L3) ---------------------


def test_a_native_command_is_refused_on_a_cache_folder_that_is_a_mount(rig: FsRig) -> None:
    folder = make_cache(home=rig.home, relative=".cache/uv")
    rig.control = replace(rig.control, mounts=lambda: frozenset({str(folder)}))

    outcome = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))[0]

    assert outcome.status is StepStatus.FAILED
    assert "mount point" in (outcome.message or "")
    assert rig.runner.calls == [] and (folder / "a.bin").exists()


def test_a_tool_resolved_to_a_relative_path_is_refused(rig: FsRig) -> None:
    folder = make_cache(home=rig.home, relative=".cache/uv")
    rig.control = replace(rig.control, which=lambda name: f"bin/{name}")

    outcome = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))[0]

    assert outcome.status is StepStatus.FAILED
    assert "relative path" in (outcome.message or "")
    assert rig.runner.calls == [] and (folder / "a.bin").exists()


def test_a_cache_folder_owned_by_someone_else_is_refused_with_or_without_a_command(
    rig: FsRig,
) -> None:
    rig.control = replace(rig.control, owner_of=lambda _path: rig.control.uid + 1)
    for relative in (".cache/uv", ".cache/thumbnails"):
        folder = make_cache(home=rig.home, relative=relative)

        with pytest.raises(ProtectedTarget):
            rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))
        assert (folder / "a.bin").exists()
    assert rig.runner.calls == []


def test_the_go_module_cache_is_refused_when_go_vanishes_between_the_checks(
    rig: FsRig,
) -> None:
    folder = make_cache(home=rig.home, relative="go/pkg/mod")
    # The first three answers feed the cache-kind lookups; the fourth reaches `_tool_path`,
    # the window after the checks in which go can disappear.
    answers = iter(["/usr/bin/go", "/usr/bin/go", "/usr/bin/go", None])
    rig.control = replace(rig.control, which=lambda _name: next(answers, None))

    outcome = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))[0]

    assert outcome.status is StepStatus.FAILED
    assert "own command" in (outcome.message or "")
    assert rig.runner.calls == [] and (folder / "a.bin").exists()


def test_yarn_that_exits_non_zero_falls_back_to_emptying_the_folder(
    rig: FsRig, caplog: pytest.LogCaptureFixture
) -> None:
    folder = make_cache(home=rig.home, relative=".cache/yarn")
    rig.runner.result = CommandResult(returncode=1, output="no project")

    with caplog.at_level(logging.WARNING):
        outcomes = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert len(rig.runner.calls) == 1
    assert folder.is_dir() and list(folder.iterdir()) == []
    assert "yarn" in caplog.text and "emptied" in caplog.text


def test_a_failing_pnpm_still_fails_the_step_and_keeps_the_folder(rig: FsRig) -> None:
    folder = make_cache(home=rig.home, relative=".local/share/pnpm/store")
    rig.runner.result = CommandResult(returncode=1, output="boom")

    outcomes = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))

    assert outcomes[0].status is StepStatus.FAILED
    assert (folder / "a.bin").exists()
