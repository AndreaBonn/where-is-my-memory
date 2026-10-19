"""Removal of a model when the cache changes under the executor (F16, F18, F19, F20)."""

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.service.cache_item_fakes import (
    EXCLUSIVE_BLOB,
    OTHER,
    HfCache,
    blob_of,
    build_hf_cache,
    planned,
)
from tests.service.fs_fakes import NOW, age
from tests.service.test_executor_cache_item_removal import disk_bytes
from wimm.collectors.cache_items import list_tree
from wimm.core.cache_items import TreeListing
from wimm.model.actions import DirFingerprint
from wimm.service import executor_cache_item
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.service.executor_cache_item import DownloadInProgress
from wimm.service.safe_tree import TreeRemoval, remove_directory

ITEM_MODULE = "wimm.service.executor_cache_item"
KEPT_NOTE = "1 store file(s) kept: no longer used only by this model"
FRESH_S = 60


@pytest.fixture
def cache(tmp_path: Path) -> HfCache:
    return build_hf_cache(home=tmp_path / "home")


def link_other_to_blob(*, cache: HfCache) -> None:
    link = cache.hub / OTHER / "snapshots" / "rev" / "extra"
    link.symlink_to(os.path.relpath(cache.hub / EXCLUSIVE_BLOB, link.parent))


def after_folder_removal(*, monkeypatch: pytest.MonkeyPatch, hook: Callable[[], None]) -> None:
    """Run `hook` right after the model folder is removed, before any blob is looked at."""

    def remove_then_hook(
        *, fingerprint: DirFingerprint, mountpoints: frozenset[str]
    ) -> TreeRemoval:
        result = remove_directory(fingerprint=fingerprint, mountpoints=mountpoints)
        hook()
        return result

    monkeypatch.setattr(f"{ITEM_MODULE}.remove_directory", remove_then_hook)


def execute(cache: HfCache) -> StepOutcome:
    return cache.rig.executor().execute(plan=planned(cache=cache))[0]


def test_a_blob_linked_by_another_repo_after_the_folder_removal_is_kept(
    cache: HfCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    after_folder_removal(monkeypatch=monkeypatch, hook=lambda: link_other_to_blob(cache=cache))

    outcome = execute(cache)

    assert outcome.status is StepStatus.DONE
    assert not cache.model.exists()
    assert (cache.hub / EXCLUSIVE_BLOB).exists()
    assert (cache.hub / OTHER / "snapshots" / "rev" / "extra").read_bytes()
    assert outcome.message == KEPT_NOTE


def test_a_blob_nobody_links_after_the_folder_removal_is_removed(
    cache: HfCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    after_folder_removal(monkeypatch=monkeypatch, hook=lambda: None)

    outcome = execute(cache)

    assert outcome.status is StepStatus.DONE
    assert not (cache.hub / EXCLUSIVE_BLOB).exists()
    assert outcome.message is None


def record_walks(*, monkeypatch: pytest.MonkeyPatch, cache: HfCache) -> list[bool]:
    """For every walk of the hub, whether the model folder was still there when it started."""
    model_there: list[bool] = []

    def recording(*, root: Path, sleep: Callable[[float], None]) -> TreeListing:
        model_there.append(cache.model.exists())
        return list_tree(root=root, sleep=sleep)

    monkeypatch.setattr(f"{ITEM_MODULE}.list_tree", recording)
    return model_there


def test_the_check_walks_the_hub_once_to_recognise_the_item(
    cache: HfCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    walks = record_walks(monkeypatch=monkeypatch, cache=cache)

    executor_cache_item.check_cache_item(
        step=planned(cache=cache).steps[0], control=cache.rig.control
    )

    assert walks == [True]


def test_the_run_walks_the_hub_once_and_only_after_the_folder_is_gone(
    cache: HfCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    walks = record_walks(monkeypatch=monkeypatch, cache=cache)

    executor_cache_item.run_cache_item(
        step=planned(cache=cache).steps[0], control=cache.rig.control
    )

    assert walks == [False]
    assert not (cache.hub / EXCLUSIVE_BLOB).exists()


def vanishing_lock_lstat(*, monkeypatch: pytest.MonkeyPatch, lock: Path) -> None:
    real = os.lstat

    def lstat(path: str | Path, **kwargs: object) -> os.stat_result:
        if Path(path) == lock:
            raise FileNotFoundError(path)
        return real(path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "lstat", lstat)


def test_a_lock_that_vanishes_during_the_walk_is_skipped(
    cache: HfCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    vanishing_lock_lstat(monkeypatch=monkeypatch, lock=cache.lock_file())

    outcome = execute(cache)

    assert outcome.status is StepStatus.DONE
    assert not cache.model.exists()


def test_a_fresh_lock_still_refuses_beside_a_vanished_one(
    cache: HfCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    fresh = cache.lock_file().with_name("other.lock")
    fresh.write_text("", encoding="utf-8")
    age(path=fresh, mtime=NOW - FRESH_S)
    vanishing_lock_lstat(monkeypatch=monkeypatch, lock=cache.lock_file())

    with pytest.raises(DownloadInProgress):
        execute(cache)
    assert cache.model.exists()


def test_a_blob_that_cannot_be_removed_fails_with_the_bytes_already_freed(
    cache: HfCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder_bytes = disk_bytes(folder=cache.model)
    blob = blob_of(hub=cache.hub, relative=EXCLUSIVE_BLOB)

    def refuse(**kwargs: object) -> TreeRemoval:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(f"{ITEM_MODULE}.remove_file", refuse)

    outcome = execute(cache)

    assert outcome.status is StepStatus.FAILED
    assert not cache.model.exists()
    assert (cache.hub / EXCLUSIVE_BLOB).exists()
    assert outcome.freed_bytes == folder_bytes
    assert outcome.message is not None
    assert outcome.message.startswith("1 store file(s) could not be removed")
    assert blob.path in outcome.message
