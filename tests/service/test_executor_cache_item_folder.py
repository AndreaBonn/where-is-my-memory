import os
from dataclasses import replace
from pathlib import Path

import pytest

from tests.service.cache_item_fakes import item_fingerprint, item_plan
from tests.service.cache_item_folder_fakes import (
    BROWSER,
    FILE_BYTES,
    FolderCaches,
    build_folder_caches,
    plan_for,
)
from wimm.service.control_protocols import StepStatus
from wimm.service.errors import ProtectedTarget, TargetChanged


@pytest.fixture
def caches(tmp_path: Path) -> FolderCaches:
    return build_folder_caches(home=tmp_path / "home")


def intact(caches: FolderCaches) -> bool:
    return (caches.browser / "bin" / "tool").exists() and (caches.product / "bin" / "tool").exists()


def test_a_playwright_browser_folder_is_removed_and_its_bytes_freed(caches: FolderCaches) -> None:
    outcomes = caches.rig.executor().execute(plan=plan_for(folder=caches.browser))

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    freed = outcomes[0].freed_bytes
    assert freed is not None and freed >= FILE_BYTES
    assert not caches.browser.exists()
    assert (caches.playwright / "firefox-1490" / "bin" / "tool").exists()
    assert (caches.product / "bin" / "tool").exists()


def test_a_jetbrains_product_folder_is_removed(caches: FolderCaches) -> None:
    outcomes = caches.rig.executor().execute(plan=plan_for(folder=caches.product))

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert not caches.product.exists()
    assert (caches.browser / "bin" / "tool").exists()


def test_a_vanished_browser_folder_is_already_gone(caches: FolderCaches) -> None:
    plan = plan_for(folder=caches.browser)
    caches.rig.executor().execute(plan=plan)

    outcomes = caches.rig.executor().execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.ALREADY_GONE]


def test_a_folder_outside_the_table_is_refused(caches: FolderCaches, tmp_path: Path) -> None:
    stranger = tmp_path / "elsewhere" / BROWSER
    (stranger / "bin").mkdir(parents=True)

    with pytest.raises(ProtectedTarget):
        caches.rig.executor().execute(plan=plan_for(folder=stranger))
    assert stranger.exists()


def test_a_folder_not_directly_inside_the_cache_is_refused(caches: FolderCaches) -> None:
    with pytest.raises(ProtectedTarget):
        caches.rig.executor().execute(plan=plan_for(folder=caches.browser / "bin"))
    assert intact(caches)


def test_a_symlinked_folder_is_refused(caches: FolderCaches) -> None:
    planned_fp = item_fingerprint(folder=caches.browser)
    moved = caches.playwright / "moved"
    caches.browser.rename(moved)
    caches.browser.symlink_to(moved)

    with pytest.raises(TargetChanged):
        caches.rig.executor().execute(plan=item_plan(fingerprint=planned_fp))
    assert (moved / "bin" / "tool").exists()


def test_a_folder_with_another_inode_is_refused(caches: FolderCaches) -> None:
    fingerprint = item_fingerprint(folder=caches.product)
    stale = replace(fingerprint, st_ino=fingerprint.st_ino + 1)

    with pytest.raises(TargetChanged):
        caches.rig.executor().execute(plan=item_plan(fingerprint=stale))
    assert intact(caches)


def test_a_folder_owned_by_someone_else_is_refused(caches: FolderCaches) -> None:
    caches.rig.control = replace(caches.rig.control, owner_of=lambda path: os.getuid() + 1)

    with pytest.raises(ProtectedTarget):
        caches.rig.executor().execute(plan=plan_for(folder=caches.browser))
    assert intact(caches)


def test_a_mount_point_is_refused(caches: FolderCaches) -> None:
    mounted = frozenset({str(caches.browser)})
    caches.rig.control = replace(caches.rig.control, mounts=lambda: mounted)

    with pytest.raises(TargetChanged):
        caches.rig.executor().execute(plan=plan_for(folder=caches.browser))
    assert intact(caches)


def test_a_browser_folder_the_rule_no_longer_recognises_is_refused(caches: FolderCaches) -> None:
    fingerprint = item_fingerprint(folder=caches.browser)
    renamed = caches.playwright / "chromium-next"
    caches.browser.rename(renamed)
    moved_fp = replace(fingerprint, realpath=str(renamed))

    with pytest.raises(ProtectedTarget):
        caches.rig.executor().execute(plan=item_plan(fingerprint=moved_fp))
    assert (renamed / "bin" / "tool").exists()


def test_a_product_folder_the_rule_no_longer_recognises_is_refused(caches: FolderCaches) -> None:
    plain = caches.jetbrains / "scratch"
    (plain / "f").mkdir(parents=True)

    with pytest.raises(ProtectedTarget):
        caches.rig.executor().execute(plan=plan_for(folder=plain))
    assert plain.exists()
