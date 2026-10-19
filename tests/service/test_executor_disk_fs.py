import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from tests.service.executor_disk_fs_helpers import DELETE, delete_devdir
from tests.service.fs_fakes import (
    OLD,
    FsRig,
    age,
    build_rig,
    dir_plan,
    fingerprint_of,
    make_project,
    root_facts,
)
from wimm.core import constants
from wimm.core.root_policy import RootFacts
from wimm.model.actions import DirFingerprint
from wimm.service.control_protocols import StepStatus
from wimm.service.errors import (
    ProtectedTarget,
    TargetChanged,
)


@pytest.fixture
def rig(tmp_path: Path) -> FsRig:
    return build_rig(home=tmp_path / "home")


# --- DEVDIR_DELETE ---------------------------------------------------------------


def test_devdir_delete_removes_the_dependency_folder_and_keeps_the_project(rig: FsRig) -> None:
    folder = make_project(root=rig.root)

    outcomes = rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert outcomes[0].freed_bytes is not None and outcomes[0].freed_bytes >= 16384
    assert not folder.exists()
    assert (folder.parent / "src" / "app.js").read_text(encoding="utf-8") == "x"


def test_devdir_delete_also_removes_a_venv(rig: FsRig) -> None:
    folder = make_project(root=rig.root, folder=".venv")
    (folder / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")

    assert delete_devdir(rig=rig, folder=folder) is StepStatus.DONE
    assert not folder.exists()


def make_rust_project(*, rig: FsRig) -> Path:
    """A project with an old `Cargo.toml` and a `target` that carries cargo's cache tag."""
    folder = make_project(root=rig.root, name="crate", folder="target")
    (folder / "CACHEDIR.TAG").write_text("Signature: 8a477f597d28d172789f06886806bc55\n")
    cargo = folder.parent / "Cargo.toml"
    cargo.write_text("[package]\n", encoding="utf-8")
    age(path=cargo, mtime=OLD)
    return folder


def test_devdir_with_its_marker_and_second_signal_is_deleted(rig: FsRig) -> None:
    folder = make_rust_project(rig=rig)

    assert delete_devdir(rig=rig, folder=folder) is StepStatus.DONE
    assert not folder.exists()
    assert (folder.parent / "Cargo.toml").exists()


def test_devdir_without_its_marker_is_refused(rig: FsRig) -> None:
    folder = make_rust_project(rig=rig)
    plan = dir_plan(kind=DELETE, path=folder)
    (folder.parent / "Cargo.toml").unlink()

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=plan)
    assert (folder / "pkg" / "lib" / "util.js").exists()


def test_devdir_that_lost_its_second_signal_is_refused(rig: FsRig) -> None:
    folder = make_rust_project(rig=rig)
    plan = dir_plan(kind=DELETE, path=folder)
    (folder / "CACHEDIR.TAG").unlink()

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=plan)
    assert (folder / "top.txt").exists()


def test_a_venv_without_pyvenv_cfg_is_refused(rig: FsRig) -> None:
    folder = make_project(root=rig.root, folder=".venv")

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))
    assert (folder / "top.txt").exists()


def test_a_project_directly_in_the_home_is_refused(rig: FsRig) -> None:
    rig.control = replace(rig.control, roots=(rig.home,))
    folder = rig.home / "node_modules"
    folder.mkdir()
    (folder / "top.txt").write_text("z", encoding="utf-8")
    age(path=rig.home, mtime=OLD)

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))
    assert (folder / "top.txt").exists()


def test_a_folder_outside_every_root_is_refused_and_survives(rig: FsRig, tmp_path: Path) -> None:
    folder = make_project(root=rig.home / "elsewhere")

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))
    assert (folder / "top.txt").exists()

    inside = make_project(root=rig.root)
    assert delete_devdir(rig=rig, folder=inside) is StepStatus.DONE


def test_a_root_whose_real_path_leaves_the_home_is_not_a_root(rig: FsRig, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    folder = make_project(root=outside)
    link = rig.home / "link"
    link.symlink_to(outside)
    rig.control = replace(rig.control, roots=(link,))

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))
    assert folder.exists()

    rig.control = replace(rig.control, roots=(rig.root,))
    inside = make_project(root=rig.root)
    assert delete_devdir(rig=rig, folder=inside) is StepStatus.DONE


def read_real_facts(*, path: Path) -> RootFacts:
    """Facts of a root owned by the current user, at its real path."""
    return root_facts(real=Path(os.path.realpath(path)))


def test_devdir_under_a_root_no_longer_owned_is_refused(rig: FsRig) -> None:
    folder = make_project(root=rig.root)
    owner = {"uid": os.getuid()}

    def read_facts(*, path: Path) -> RootFacts:
        return root_facts(real=Path(os.path.realpath(path)), st_uid=owner["uid"])

    rig.control = replace(rig.control, read_facts=read_facts)
    plan = dir_plan(kind=DELETE, path=folder)
    owner["uid"] = os.getuid() + 1  # the root changed hands between the plan and the run

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=plan)
    assert (folder / "top.txt").exists()

    owner["uid"] = os.getuid()
    assert rig.executor().execute(plan=plan)[0].status is StepStatus.DONE


def test_a_root_whose_facts_cannot_be_read_now_is_refused(rig: FsRig) -> None:
    folder = make_project(root=rig.root)
    rig.control = replace(rig.control, read_facts=lambda *, path: None)

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))
    assert (folder / "top.txt").exists()


def test_a_system_root_is_refused_and_an_external_one_is_executed(
    rig: FsRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = make_project(root=rig.root)
    outside = replace(rig.control, home=Path("/home/nobody"))
    rig.control = replace(outside, read_facts=read_real_facts)

    # The tmpdir sits under /tmp, a system path ADR-007 refuses outside the home.
    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))
    assert (folder / "top.txt").exists()

    monkeypatch.setattr(constants, "SYSTEM_PATH_PREFIXES", ("/usr",))
    assert delete_devdir(rig=rig, folder=folder) is StepStatus.DONE


def test_a_device_changed_under_the_planned_folder_is_refused(rig: FsRig) -> None:
    folder = make_project(root=rig.root)
    real = fingerprint_of(path=folder)
    other_disk = DirFingerprint(realpath=real.realpath, st_ino=real.st_ino, st_dev=real.st_dev + 1)

    with pytest.raises(TargetChanged):
        rig.executor().execute(plan=dir_plan(kind=DELETE, fingerprint=other_disk))
    assert (folder / "top.txt").exists()


def test_a_symlink_in_place_of_the_folder_is_refused_and_its_target_survives(
    rig: FsRig, tmp_path: Path
) -> None:
    folder = make_project(root=rig.root)
    plan = dir_plan(kind=DELETE, path=folder)
    victim = rig.root / "victim"
    victim.mkdir()
    (victim / "precious.txt").write_text("keep", encoding="utf-8")
    shutil.rmtree(folder)
    folder.symlink_to(victim)

    with pytest.raises(TargetChanged):
        rig.executor().execute(plan=plan)

    assert folder.is_symlink()
    assert (victim / "precious.txt").read_text(encoding="utf-8") == "keep"


def test_a_symlink_inside_the_folder_is_unlinked_not_followed(rig: FsRig) -> None:
    folder = make_project(root=rig.root)
    victim = rig.root / "victim"
    victim.mkdir()
    (victim / "precious.txt").write_text("keep", encoding="utf-8")
    (folder / "pkg" / "escape").symlink_to(victim)

    assert delete_devdir(rig=rig, folder=folder) is StepStatus.DONE

    assert not folder.exists()
    assert (victim / "precious.txt").read_text(encoding="utf-8") == "keep"
