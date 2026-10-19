from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.service.android_item_fakes import android_rig
from tests.service.cache_item_fakes import item_fingerprint, item_plan
from wimm.service.control_protocols import StepStatus
from wimm.service.errors import ControlFailed, ProtectedTarget, TargetChanged
from wimm.service.executor_cache_item import run_cache_item
from wimm.service.fs_controls import CommandResult

AVD_DELETE = ("/usr/bin/avdmanager", "delete", "avd", "-n", "Pixel")


@pytest.mark.parametrize(
    "launch", [["-avd", "Pixel"], ["-avd=Pixel"], ["@Pixel"], ["@Other"], ["-avd", "Other"]]
)
def test_every_emulator_launch_form_of_the_avd_is_refused(
    tmp_path: Path, launch: list[str]
) -> None:
    rig, folder = android_rig(home=tmp_path / "home", avd=True)
    argv = ["/opt/android/emulator/emulator", *launch]
    rig.control = replace(rig.control, processes=lambda: [("emulator", argv)])
    plan = item_plan(fingerprint=item_fingerprint(folder=folder))
    if "Pixel" in " ".join(launch):
        with pytest.raises(ProtectedTarget, match="emulator"):
            rig.executor().execute(plan=plan)
        assert rig.runner.calls == []
    else:
        rig.executor().execute(plan=plan)
        assert rig.runner.calls == [AVD_DELETE]


@pytest.mark.parametrize(
    "content",
    [
        "elsewhere",
        "two",
        "none",
        "missing",
        "symlink",
        "indented",
        "spaced",
        "rel_elsewhere",
        "unknown_key",
        "two_rel",
        "exact",
    ],
)
def test_avd_ini_must_name_exactly_the_checked_folder(tmp_path: Path, content: str) -> None:
    rig, folder = android_rig(home=tmp_path / "home", avd=True)
    ini = folder.parent / "Pixel.ini"
    other = tmp_path / "other.avd"
    other.mkdir()
    texts = {
        "elsewhere": f"path={other}\n",
        "two": f"path={folder}\npath={other}\n",
        "none": "path.rel=avd/Pixel.avd\n",
        "indented": f"path={folder}\n path={other}\n",
        "spaced": f"path={folder}\npath ={other}\n",
        "rel_elsewhere": f"path={folder}\npath.rel=../{other.name}\n",
        "unknown_key": f"path={folder}\nimage.sysdir.1={other}\n",
        "two_rel": f"path={folder}\npath.rel=avd/Pixel.avd\npath.rel=x\n",
    }
    if content in texts:
        ini.write_text(texts[content], encoding="utf-8")
    elif content == "missing":
        ini.unlink()
    elif content == "symlink":
        target = tmp_path / "real.ini"
        target.write_text(ini.read_text(encoding="utf-8"), encoding="utf-8")
        ini.unlink()
        ini.symlink_to(target)
    plan = item_plan(fingerprint=item_fingerprint(folder=folder))
    if content == "exact":
        rig.executor().execute(plan=plan)
        assert rig.runner.calls == [AVD_DELETE]
    else:
        with pytest.raises(ProtectedTarget, match="ini"):
            rig.executor().execute(plan=plan)
        assert rig.runner.calls == []
    assert other.is_dir()


@pytest.mark.parametrize("avd", [False, True])
@pytest.mark.parametrize("replaced", [True, False])
def test_android_folder_replaced_after_the_check_runs_no_tool(
    tmp_path: Path, avd: bool, replaced: bool
) -> None:
    rig, folder = android_rig(home=tmp_path / "home", avd=avd)
    fingerprint = item_fingerprint(folder=folder)
    if replaced:
        fingerprint = replace(fingerprint, st_ino=fingerprint.st_ino + 1)
    step = item_plan(fingerprint=fingerprint).steps[0]
    if replaced:
        with pytest.raises(TargetChanged, match="replaced"):
            run_cache_item(step=step, control=rig.control)
        assert rig.runner.calls == []
    else:
        # The fake tool removes nothing: the executor turns this into a FAILED step.
        with pytest.raises(ControlFailed, match="left"):
            run_cache_item(step=step, control=rig.control)
        assert len(rig.runner.calls) == 1


@pytest.mark.parametrize("returncode", [1, 0])
def test_android_tool_exit_code_decides_even_when_the_folder_is_gone(
    tmp_path: Path, returncode: int
) -> None:
    rig, folder = android_rig(home=tmp_path / "home")

    def removing(**kwargs: object) -> CommandResult:
        (folder / "package.xml").unlink()
        folder.rmdir()
        return CommandResult(returncode=returncode, output="boom")

    runner = Mock()
    runner.run.side_effect = removing
    rig.control = replace(rig.control, runner=runner)
    outcome = rig.executor().execute(plan=item_plan(fingerprint=item_fingerprint(folder=folder)))[0]
    assert not folder.exists()
    if returncode:
        assert outcome.status is StepStatus.FAILED
        assert outcome.message is not None and "exited with code 1" in outcome.message
    else:
        assert outcome.status is StepStatus.DONE
