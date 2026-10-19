import logging
import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from tests.service.executor_disk_fs_helpers import CLEAN
from tests.service.fs_fakes import (
    FsRig,
    build_rig,
    dir_plan,
    make_cache,
    make_trash,
)
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import StepStatus
from wimm.service.errors import (
    CacheIsLink,
    ProtectedTarget,
)


@pytest.fixture
def rig(tmp_path: Path) -> FsRig:
    return build_rig(home=tmp_path / "home")


# --- TRASH_EMPTY -----------------------------------------------------------------

EMPTY = ActionKind.TRASH_EMPTY


def test_trash_empty_removes_files_and_info_but_keeps_the_folders(rig: FsRig) -> None:
    trash = make_trash(home=rig.home)

    outcomes = rig.executor().execute(plan=dir_plan(kind=EMPTY, path=trash))

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert outcomes[0].freed_bytes is not None and outcomes[0].freed_bytes >= 4096
    assert (trash / "files").is_dir() and list((trash / "files").iterdir()) == []
    assert (trash / "info").is_dir() and list((trash / "info").iterdir()) == []
    assert (trash / "directorysizes").exists()


def test_a_decoy_trash_outside_the_tmpdir_stays_intact(
    rig: FsRig, tmp_path_factory: pytest.TempPathFactory
) -> None:
    decoy = make_trash(home=tmp_path_factory.mktemp("decoy"))
    real = make_trash(home=rig.home)

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=dir_plan(kind=EMPTY, path=decoy))
    assert (decoy / "files" / "y.txt").exists()
    assert (decoy / "info" / "y.txt.trashinfo").exists()
    assert (real / "files" / "y.txt").exists()

    assert rig.executor().execute(plan=dir_plan(kind=EMPTY, path=real))[0].status is StepStatus.DONE
    assert (decoy / "files" / "y.txt").exists()


def test_a_trash_files_symlink_is_not_followed(rig: FsRig, tmp_path: Path) -> None:
    trash = make_trash(home=rig.home)
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "precious.txt").write_text("keep", encoding="utf-8")
    plan = dir_plan(kind=EMPTY, path=trash)
    shutil.rmtree(trash / "files")
    (trash / "files").symlink_to(victim)

    outcomes = rig.executor().execute(plan=plan)

    assert outcomes[0].status is StepStatus.FAILED
    assert (victim / "precious.txt").read_text(encoding="utf-8") == "keep"
    assert not (trash / "info" / "y.txt.trashinfo").exists()


def test_an_already_empty_trash_is_already_gone(rig: FsRig) -> None:
    trash = make_trash(home=rig.home)
    plan = dir_plan(kind=EMPTY, path=trash)
    assert rig.executor().execute(plan=plan)[0].status is StepStatus.DONE

    assert rig.executor().execute(plan=plan)[0].status is StepStatus.ALREADY_GONE
    assert os.path.isdir(trash / "files")


# --- the cache type comes from the table, never from the plan (R15) -------------------


def make_tagged(*, folder: Path) -> Path:
    """A cache folder in a custom place, carrying the tag that proves it is a tool cache."""
    (folder / "sub").mkdir(parents=True)
    (folder / "a.bin").write_bytes(b"a" * 4096)
    (folder / "CACHEDIR.TAG").write_text("Signature: 8a477f597d28d172789f06886806bc55\n")
    return folder


def test_cache_outside_the_table_is_refused(tmp_path: Path) -> None:
    home = tmp_path / "home"
    stray = home / "custom" / "uv"
    (stray / "sub").mkdir(parents=True)
    (stray / "a.bin").write_bytes(b"a" * 4096)
    rig = build_rig(home=home, environ={"UV_CACHE_DIR": str(stray)})
    # Redirected but without a sentinel: the table keeps it for measuring only.
    folder_in_home = home / ".cache" / "elsewhere"
    (folder_in_home / "sub").mkdir(parents=True)

    for target in (stray, folder_in_home):
        with pytest.raises(ProtectedTarget):
            rig.executor().execute(plan=dir_plan(kind=CLEAN, path=target))
        assert target.is_dir()
    assert (stray / "a.bin").exists() and (stray / "sub").exists()
    assert rig.runner.calls == []


def test_a_redirected_cache_that_the_table_lists_is_cleaned_where_it_is(tmp_path: Path) -> None:
    home = tmp_path / "home"
    custom = make_tagged(folder=home / "custom" / "uv")
    rig = build_rig(home=home, environ={"UV_CACHE_DIR": str(custom)})

    outcomes = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=custom))

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert rig.runner.calls == [("/usr/bin/uv", "cache", "prune", "--cache-dir", str(custom))]


def test_a_cache_the_default_place_of_which_the_environment_moved_is_refused(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    custom = make_tagged(folder=home / "custom" / "uv")
    old_place = make_cache(home=home, relative=".cache/uv")
    rig = build_rig(home=home, environ={"UV_CACHE_DIR": str(custom)})

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=dir_plan(kind=CLEAN, path=old_place))
    assert (old_place / "a.bin").exists()


def test_a_new_cache_type_is_emptied_without_a_command(rig: FsRig) -> None:
    folder = make_cache(home=rig.home, relative=".gradle/caches")

    outcomes = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))

    assert outcomes[0].status is StepStatus.DONE
    assert rig.runner.calls == []
    assert folder.is_dir() and list(folder.iterdir()) == []


def test_the_go_module_cache_is_not_touched_without_go_on_the_path(tmp_path: Path) -> None:
    rig = build_rig(home=tmp_path / "home", missing=("go",))
    folder = make_cache(home=rig.home, relative="go/pkg/mod")
    (folder / "sub" / "b.bin").chmod(0o444)

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))
    assert (folder / "sub" / "b.bin").exists() and rig.runner.calls == []


def test_a_cache_that_is_a_symlink_gets_its_own_message_and_is_not_followed(rig: FsRig) -> None:
    folder = make_cache(home=rig.home, relative=".cache/thumbnails")
    plan = dir_plan(kind=CLEAN, path=folder)
    moved = rig.home / "moved"
    folder.rename(moved)
    folder.symlink_to(moved)

    with pytest.raises(CacheIsLink) as caught:
        rig.executor().execute(plan=plan)
    assert caught.value.user_message == (
        "La cache è un collegamento: puliscila con il comando dello strumento"
    )
    assert (moved / "a.bin").exists() and (moved / "sub" / "b.bin").exists()
    assert rig.runner.calls == []


def test_cargo_empties_only_its_four_download_folders_and_never_bin(rig: FsRig) -> None:
    cargo = rig.home / ".cargo"
    for relative in ("registry/cache", "registry/src", "registry/index", "git/db", "git/checkouts"):
        (cargo / relative).mkdir(parents=True)
        (cargo / relative / "x.crate").write_bytes(b"c" * 4096)
    (cargo / "bin").mkdir()
    (cargo / "bin" / "rustfmt").write_bytes(b"b")
    (cargo / "config.toml").write_text("[net]\n", encoding="utf-8")

    for relative in (".cargo/registry", ".cargo/git"):
        outcomes = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=rig.home / relative))
        assert outcomes[0].status is StepStatus.DONE

    for emptied in ("registry/cache", "registry/src", "git/db", "git/checkouts"):
        assert (cargo / emptied).is_dir() and list((cargo / emptied).iterdir()) == []
    assert (cargo / "registry/index" / "x.crate").exists()
    assert (cargo / "bin" / "rustfmt").exists() and (cargo / "config.toml").exists()
    assert rig.runner.calls == []


def test_a_default_cache_symlinked_onto_user_files_is_refused_and_the_files_survive(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    documents = home / "Documents"
    documents.mkdir(parents=True)
    (documents / "thesis.txt").write_text("mine", encoding="utf-8")
    (home / ".cache").mkdir()
    link = home / ".cache" / "thumbnails"
    link.symlink_to(documents, target_is_directory=True)
    rig = build_rig(home=home)

    for target in (documents, link):
        with pytest.raises((CacheIsLink, ProtectedTarget)):
            rig.executor().execute(plan=dir_plan(kind=CLEAN, path=target))
    assert (documents / "thesis.txt").read_text(encoding="utf-8") == "mine"


def test_the_same_cache_as_a_real_folder_is_cleaned(tmp_path: Path) -> None:
    home = tmp_path / "home"
    folder = make_cache(home=home, relative=".cache/thumbnails")
    rig = build_rig(home=home)

    outcomes = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))

    assert outcomes[0].status is StepStatus.DONE


def test_a_cache_left_half_cleaned_names_its_folder_not_its_title(rig: FsRig) -> None:
    # F8 gave cache steps a title ("Miniature") as label: the failure must still say where.
    folder = make_cache(home=rig.home, relative=".cache/thumbnails")
    plan = dir_plan(kind=CLEAN, path=folder)
    titled = replace(plan, steps=(replace(plan.steps[0], target_label="Miniature"),))
    locked = folder / "sub"
    locked.chmod(0o500)
    try:
        outcomes = rig.executor().execute(plan=titled)
    finally:
        locked.chmod(0o700)

    assert outcomes[0].status is StepStatus.FAILED
    assert f"1 entries left in {folder}" in (outcomes[0].message or "")


def test_a_titled_cache_step_is_logged_with_its_folder(
    rig: FsRig, caplog: pytest.LogCaptureFixture
) -> None:
    folder = make_cache(home=rig.home, relative=".cache/thumbnails")
    plan = dir_plan(kind=CLEAN, path=folder)
    titled = replace(plan, steps=(replace(plan.steps[0], target_label="Miniature"),))
    with caplog.at_level(logging.INFO, logger="wimm.service.executor_disk_docker"):
        rig.executor().execute(plan=titled)

    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("disk action=")]
    assert len(lines) == 1
    assert lines[0].startswith(f"disk action=cache_clean target={folder} outcome=done ")
