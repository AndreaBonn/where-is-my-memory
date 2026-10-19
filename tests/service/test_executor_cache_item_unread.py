"""Removal of a model when the post-removal walk of the hub could not see everything (F23, F26)."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.service.cache_item_fakes import EXCLUSIVE_BLOB, OTHER, HfCache, build_hf_cache, planned
from wimm.service import executor_cache_item
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.service.safe_tree import TreeRemoval

KEPT_UNREAD_NOTE = "1 store file(s) kept: 1 cache entries could not be read after the removal"
PARTIAL_FREED = 8192


@pytest.fixture
def cache(tmp_path: Path) -> HfCache:
    return build_hf_cache(home=tmp_path / "home")


def hide_directory(*, monkeypatch: pytest.MonkeyPatch, hidden: Path) -> None:
    """Make listing `hidden` fail the way an unreadable directory does (not portable otherwise)."""
    real_scandir = os.scandir

    def scandir(fd: int) -> Iterator[os.DirEntry[str]]:
        if os.readlink(f"/proc/self/fd/{fd}") == str(hidden):
            raise PermissionError(13, "Permission denied", str(hidden))
        return real_scandir(fd)

    monkeypatch.setattr(os, "scandir", scandir)


def execute(cache: HfCache) -> StepOutcome:
    return cache.rig.executor().execute(plan=planned(cache=cache))[0]


def test_a_link_of_another_model_the_walk_could_not_see_keeps_the_blob(
    cache: HfCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = cache.hub / OTHER / "snapshots" / "rev"
    (snapshot / "extra").symlink_to(os.path.relpath(cache.hub / EXCLUSIVE_BLOB, snapshot))
    hide_directory(monkeypatch=monkeypatch, hidden=snapshot)

    outcome = execute(cache)

    assert outcome.status is StepStatus.DONE
    assert not cache.model.exists()
    assert (cache.hub / EXCLUSIVE_BLOB).exists()
    assert outcome.message == KEPT_UNREAD_NOTE


def test_a_blob_nobody_links_is_removed_when_the_walk_saw_everything(cache: HfCache) -> None:
    outcome = execute(cache)

    assert outcome.status is StepStatus.DONE
    assert not (cache.hub / EXCLUSIVE_BLOB).exists()
    assert outcome.message is None


def test_an_unread_directory_keeps_even_a_blob_no_one_links(
    cache: HfCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    hide_directory(monkeypatch=monkeypatch, hidden=cache.hub / OTHER / "snapshots" / "rev")

    outcome = execute(cache)

    assert (cache.hub / EXCLUSIVE_BLOB).exists()
    assert outcome.message == KEPT_UNREAD_NOTE


def test_a_folder_left_with_entries_fails_with_the_bytes_freed_and_touches_no_blob(
    cache: HfCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    partial = TreeRemoval(
        removed=3, freed_bytes=PARTIAL_FREED, error_count=2, error_samples=("snap: busy",)
    )
    monkeypatch.setattr(executor_cache_item, "remove_directory", lambda **_: partial)

    outcome = execute(cache)

    assert outcome.status is StepStatus.FAILED
    assert outcome.freed_bytes == PARTIAL_FREED
    assert outcome.message is not None
    assert outcome.message.startswith("2 entries left in ")
    assert "snap: busy" in outcome.message
    assert (cache.hub / EXCLUSIVE_BLOB).exists()
