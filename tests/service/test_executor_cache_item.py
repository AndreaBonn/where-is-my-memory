import os
from dataclasses import replace
from pathlib import Path

import pytest

from tests.service.cache_item_fakes import (
    EXCLUSIVE_BLOB,
    MODEL,
    OTHER,
    HfCache,
    build_hf_cache,
    item_fingerprint,
    item_plan,
    planned,
)
from tests.service.fs_fakes import NOW, age
from wimm.model.disk import CacheKind
from wimm.service.control_protocols import StepStatus
from wimm.service.errors import ProtectedTarget, TargetChanged
from wimm.service.executor_cache_item import DownloadInProgress

FRESH_S = 60
OLD_S = 3600


@pytest.fixture
def cache(tmp_path: Path) -> HfCache:
    return build_hf_cache(home=tmp_path / "home")


def intact(cache: HfCache) -> bool:
    return (cache.model / "refs" / "main").exists() and (cache.hub / EXCLUSIVE_BLOB).exists()


def test_the_plan_runs_when_nothing_changed(cache: HfCache) -> None:
    outcomes = cache.rig.executor().execute(plan=planned(cache=cache))

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert not cache.model.exists()


def test_a_path_with_parent_components_is_refused(cache: HfCache) -> None:
    sneaky = f"{cache.hub}/{OTHER}/../{MODEL}"
    plan = item_plan(fingerprint=item_fingerprint(folder=cache.model, realpath=sneaky))

    with pytest.raises(ProtectedTarget):
        cache.rig.executor().execute(plan=plan)
    assert intact(cache)


def test_a_folder_outside_the_cache_table_is_refused(cache: HfCache, tmp_path: Path) -> None:
    stranger = tmp_path / "elsewhere" / MODEL
    (stranger / "refs").mkdir(parents=True)
    (stranger / "refs" / "main").write_text("rev", encoding="utf-8")

    with pytest.raises(ProtectedTarget):
        cache.rig.executor().execute(plan=item_plan(fingerprint=item_fingerprint(folder=stranger)))
    assert (stranger / "refs" / "main").exists()


def test_a_folder_not_directly_inside_the_cache_is_refused(cache: HfCache) -> None:
    nested = cache.model / "snapshots"

    with pytest.raises(ProtectedTarget):
        cache.rig.executor().execute(plan=item_plan(fingerprint=item_fingerprint(folder=nested)))
    assert intact(cache)


def test_a_folder_that_is_not_a_model_item_is_refused(cache: HfCache) -> None:
    store = cache.hub / "blobs"

    with pytest.raises(ProtectedTarget):
        cache.rig.executor().execute(plan=item_plan(fingerprint=item_fingerprint(folder=store)))
    assert intact(cache)


def test_a_symlinked_folder_is_refused(cache: HfCache) -> None:
    planned_fp = item_fingerprint(folder=cache.model)
    moved = cache.hub / "moved"
    cache.model.rename(moved)
    cache.model.symlink_to(moved)

    with pytest.raises(TargetChanged):
        cache.rig.executor().execute(plan=item_plan(fingerprint=planned_fp))
    assert (moved / "refs" / "main").exists()


def test_a_path_through_a_symlinked_ancestor_is_refused(cache: HfCache, tmp_path: Path) -> None:
    link = tmp_path / "link"
    link.symlink_to(cache.hub.parent)
    via_link = link / "hub"
    table = cache.rig.control.caches
    moved = tuple(
        replace(c, path=via_link) if c.kind is CacheKind.HUGGINGFACE else c for c in table.caches
    )
    cache.rig.control = replace(cache.rig.control, caches=replace(table, caches=moved))
    fingerprint = item_fingerprint(folder=cache.model, realpath=str(via_link / MODEL))

    with pytest.raises(TargetChanged):
        cache.rig.executor().execute(plan=item_plan(fingerprint=fingerprint))
    assert intact(cache)


def test_a_folder_owned_by_someone_else_is_refused(cache: HfCache) -> None:
    other_owner = replace(cache.rig.control, owner_of=lambda path: os.getuid() + 1)
    cache.rig.control = other_owner

    with pytest.raises(ProtectedTarget):
        cache.rig.executor().execute(plan=planned(cache=cache))
    assert intact(cache)


def test_a_folder_with_another_inode_is_refused(cache: HfCache) -> None:
    fingerprint = item_fingerprint(folder=cache.model)
    stale = replace(fingerprint, st_ino=fingerprint.st_ino + 1)

    with pytest.raises(TargetChanged):
        cache.rig.executor().execute(plan=item_plan(fingerprint=stale))
    assert intact(cache)


def test_a_mount_point_is_refused(cache: HfCache) -> None:
    cache.rig.control = replace(cache.rig.control, mounts=lambda: frozenset({str(cache.model)}))

    with pytest.raises(TargetChanged):
        cache.rig.executor().execute(plan=planned(cache=cache))
    assert intact(cache)


def test_a_folder_lost_its_item_shape_is_refused(cache: HfCache) -> None:
    plain = cache.hub / "just-a-folder"
    plain.mkdir()
    (plain / "f.txt").write_text("x", encoding="utf-8")

    with pytest.raises(ProtectedTarget):
        cache.rig.executor().execute(plan=item_plan(fingerprint=item_fingerprint(folder=plain)))
    assert (plain / "f.txt").exists()


def test_a_fresh_lock_is_refused(cache: HfCache) -> None:
    age(path=cache.lock_file(), mtime=NOW - FRESH_S)

    with pytest.raises(DownloadInProgress):
        cache.rig.executor().execute(plan=planned(cache=cache))
    assert intact(cache)


def test_an_old_lock_does_not_stop_the_removal(cache: HfCache) -> None:
    age(path=cache.lock_file(), mtime=NOW - OLD_S)

    outcomes = cache.rig.executor().execute(plan=planned(cache=cache))

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert not cache.model.exists()


def test_a_fresh_lock_of_another_model_does_not_stop_the_removal(cache: HfCache) -> None:
    other_lock = cache.hub / ".locks" / OTHER / "lock"
    other_lock.parent.mkdir(parents=True)
    other_lock.write_text("", encoding="utf-8")
    age(path=other_lock, mtime=NOW - FRESH_S)
    age(path=cache.lock_file(), mtime=NOW - OLD_S)

    outcomes = cache.rig.executor().execute(plan=planned(cache=cache))

    assert [o.status for o in outcomes] == [StepStatus.DONE]


def test_a_vanished_folder_is_already_gone(cache: HfCache) -> None:
    plan = planned(cache=cache)
    cache.rig.executor().execute(plan=plan)

    outcomes = cache.rig.executor().execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.ALREADY_GONE]
