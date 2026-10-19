from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.service.android_item_fakes import android_rig
from tests.service.cache_item_fakes import item_fingerprint, item_plan
from wimm.service.control_protocols import StepStatus
from wimm.service.errors import ControlFailed, ProtectedTarget
from wimm.service.fs_controls import CommandResult


@pytest.mark.parametrize("avd", [False, True])
def test_item_argv_android_sdk(tmp_path: Path, avd: bool) -> None:
    rig, folder = android_rig(home=tmp_path / "home", avd=avd)
    before = sum(p.stat().st_blocks * 512 for p in folder.rglob("*") if p.is_file())

    def removed(**kwargs: object) -> CommandResult:
        for path in folder.iterdir():
            path.unlink()
        folder.rmdir()
        return CommandResult(returncode=0, output="")

    runner = Mock()
    runner.run.side_effect = removed
    rig.control = replace(rig.control, runner=runner)
    outcome = rig.executor().execute(plan=item_plan(fingerprint=item_fingerprint(folder=folder)))[0]
    expected = (
        ("/usr/bin/avdmanager", "delete", "avd", "-n", "Pixel")
        if avd
        else (
            "/usr/bin/sdkmanager",
            f"--sdk_root={rig.home / 'Android/Sdk'}",
            "--uninstall",
            "platforms;android-34",
        )
    )
    assert tuple(runner.run.call_args.kwargs["argv"]) == expected
    assert outcome.status is StepStatus.DONE
    assert outcome.freed_bytes == before
    assert not folder.exists()


@pytest.mark.parametrize("avd", [False, True])
def test_android_missing_tool_refuses_instead_of_deleting(tmp_path: Path, avd: bool) -> None:
    rig, folder = android_rig(home=tmp_path / "home", avd=avd)
    rig.control = replace(rig.control, which=lambda name: None)
    with pytest.raises(ProtectedTarget, match="tool"):
        rig.executor().execute(plan=item_plan(fingerprint=item_fingerprint(folder=folder)))
    assert folder.is_dir()
    assert rig.runner.calls == []


@pytest.mark.parametrize("running", [True, False])
def test_avd_running_emulator_is_refused(tmp_path: Path, running: bool) -> None:
    rig, folder = android_rig(home=tmp_path / "home", avd=True)
    name = "Pixel" if running else "Other"
    rig.control = replace(
        rig.control, processes=lambda: [("qemu-system-x86_64", ["emulator", "-avd", name])]
    )
    plan = item_plan(fingerprint=item_fingerprint(folder=folder))
    if running:
        with pytest.raises(ProtectedTarget, match="emulator"):
            rig.executor().execute(plan=plan)
        assert rig.runner.calls == []
    else:
        assert rig.executor().execute(plan=plan)[0].status is StepStatus.FAILED
        assert rig.runner.calls == [("/usr/bin/avdmanager", "delete", "avd", "-n", "Pixel")]
    assert (folder / "config.ini").is_file()


@pytest.mark.parametrize("avd", [False, True])
@pytest.mark.parametrize("failure", ["remaining", "exit", "timeout"])
def test_android_tool_failure_never_falls_back_to_deletion(
    tmp_path: Path, avd: bool, failure: str
) -> None:
    rig, folder = android_rig(home=tmp_path / "home", avd=avd)
    if failure == "exit":
        rig.runner.result = CommandResult(returncode=1, output="failed")
    elif failure == "timeout":
        rig.runner.error = ControlFailed("timeout")
    outcome = rig.executor().execute(plan=item_plan(fingerprint=item_fingerprint(folder=folder)))[0]
    assert outcome.status is StepStatus.FAILED
    assert outcome.message
    assert outcome.freed_bytes is None
    assert len(rig.runner.calls) == 1
    assert folder.is_dir()


@pytest.mark.parametrize("tool", ["sdkmanager", "avdmanager"])
def test_android_tool_resolves_sdk_before_path(tmp_path: Path, tool: str) -> None:
    rig, folder = android_rig(home=tmp_path / "home", avd=tool == "avdmanager")
    binary = rig.home / "Android/Sdk/cmdline-tools/latest/bin" / tool
    binary.parent.mkdir(parents=True)
    binary.touch(mode=0o755)
    rig.executor().execute(plan=item_plan(fingerprint=item_fingerprint(folder=folder)))
    assert rig.runner.calls[0][0] == str(binary)


@pytest.mark.parametrize("name", ["cmdline-tools", "licenses"])
def test_android_reserved_package_is_refused(tmp_path: Path, name: str) -> None:
    rig, _ = android_rig(home=tmp_path / "home")
    folder = rig.home / "Android/Sdk" / name
    folder.mkdir()
    (folder / "package.xml").touch()
    with pytest.raises(ProtectedTarget, match="recognised"):
        rig.executor().execute(plan=item_plan(fingerprint=item_fingerprint(folder=folder)))
    assert (folder / "package.xml").exists()
    assert rig.runner.calls == []


@pytest.mark.parametrize("avd", [False, True])
def test_android_command_uses_isolated_home(tmp_path: Path, avd: bool) -> None:
    rig, folder = android_rig(home=tmp_path / "home", avd=avd)
    rig.executor().execute(plan=item_plan(fingerprint=item_fingerprint(folder=folder)))
    env = rig.runner.envs[0]
    assert env is not None
    assert env["HOME"] == str(rig.home)
    if avd:
        assert env["ANDROID_AVD_HOME"] == str(folder.parent)


def test_avd_unrelated_process_with_avd_argument_does_not_block(tmp_path: Path) -> None:
    rig, folder = android_rig(home=tmp_path / "home", avd=True)
    rig.control = replace(rig.control, processes=lambda: [("echo", ["echo", "-avd", "Pixel"])])
    outcome = rig.executor().execute(plan=item_plan(fingerprint=item_fingerprint(folder=folder)))[0]
    assert outcome.status is StepStatus.FAILED
    assert rig.runner.calls == [("/usr/bin/avdmanager", "delete", "avd", "-n", "Pixel")]
