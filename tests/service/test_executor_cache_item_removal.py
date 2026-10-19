import os
from pathlib import Path

import pytest

from tests.service.cache_item_fakes import (
    EXCLUSIVE_BLOB,
    MODEL,
    OTHER,
    SHARED_BLOB,
    HfCache,
    blob_of,
    build_hf_cache,
    item_fingerprint,
    item_plan,
    planned,
)
from tests.service.executor_fakes import OWNER_UID, FakeProcesses
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.service.executor import PlanExecutor


@pytest.fixture
def cache(tmp_path: Path) -> HfCache:
    return build_hf_cache(home=tmp_path / "home")


def disk_bytes(*, folder: Path) -> int:
    """Allocated size of the files under a folder (links not followed; directories free none)."""
    total = 0
    for current, _, files in os.walk(folder):
        for name in files:
            total += os.lstat(Path(current) / name).st_blocks * 512
    return total


def run(cache: HfCache) -> StepOutcome:
    return cache.rig.executor().execute(plan=planned(cache=cache))[0]


def test_the_exclusive_blob_goes_with_the_folder_and_the_shared_one_stays(cache: HfCache) -> None:
    outcome = run(cache)

    assert outcome.status is StepStatus.DONE
    assert not cache.model.exists()
    assert not (cache.hub / EXCLUSIVE_BLOB).exists()
    assert (cache.hub / SHARED_BLOB).exists()
    assert (cache.hub / OTHER / "snapshots" / "rev" / "weights").exists()
    assert outcome.message is None


def test_freed_is_the_bytes_actually_removed(cache: HfCache) -> None:
    folder_bytes = disk_bytes(folder=cache.model)
    blob_bytes = blob_of(hub=cache.hub, relative=EXCLUSIVE_BLOB).size

    outcome = run(cache)

    assert outcome.freed_bytes == folder_bytes + blob_bytes


def test_a_blob_that_became_shared_after_the_plan_is_kept(cache: HfCache) -> None:
    plan = planned(cache=cache)
    link = cache.hub / OTHER / "snapshots" / "rev" / "extra"
    link.symlink_to(os.path.relpath(cache.hub / EXCLUSIVE_BLOB, link.parent))
    folder_bytes = disk_bytes(folder=cache.model)

    outcome = cache.rig.executor().execute(plan=plan)[0]

    assert outcome.status is StepStatus.DONE
    assert not cache.model.exists()
    assert (cache.hub / EXCLUSIVE_BLOB).exists()
    assert outcome.freed_bytes == folder_bytes
    assert outcome.message == "1 store file(s) kept: no longer used only by this model"


def test_a_blob_replaced_after_the_plan_is_kept(cache: HfCache) -> None:
    plan = planned(cache=cache)
    blob = cache.hub / EXCLUSIVE_BLOB
    replacement = blob.with_name("replacement")
    replacement.write_bytes(b"new content")
    os.rename(replacement, blob)

    outcome = cache.rig.executor().execute(plan=plan)[0]

    assert outcome.status is StepStatus.DONE
    assert not cache.model.exists()
    assert blob.read_bytes() == b"new content"
    assert outcome.message == "1 store file(s) kept: no longer used only by this model"


def test_a_planned_blob_that_vanished_is_not_counted_as_kept(cache: HfCache) -> None:
    plan = planned(cache=cache)
    (cache.hub / EXCLUSIVE_BLOB).unlink()

    outcome = cache.rig.executor().execute(plan=plan)[0]

    assert outcome.status is StepStatus.DONE
    assert outcome.message is None


def test_a_blob_not_in_the_plan_is_never_removed(cache: HfCache) -> None:
    plan = item_plan(fingerprint=item_fingerprint(folder=cache.model))

    cache.rig.executor().execute(plan=plan)

    assert (cache.hub / EXCLUSIVE_BLOB).exists()
    assert not cache.model.exists()


def test_a_blob_planned_with_a_shared_path_is_kept(cache: HfCache) -> None:
    shared = blob_of(hub=cache.hub, relative=SHARED_BLOB)
    plan = item_plan(fingerprint=item_fingerprint(folder=cache.model, blobs=(shared,)))

    outcome = cache.rig.executor().execute(plan=plan)[0]

    assert (cache.hub / SHARED_BLOB).exists()
    assert (cache.hub / MODEL).exists() is False
    assert outcome.message == "1 store file(s) kept: no longer used only by this model"


def test_a_cache_item_removal_goes_to_the_disk_fs_control_and_touches_no_process(
    cache: HfCache,
) -> None:
    processes = FakeProcesses()
    executor = PlanExecutor(
        processes=processes, containers=None, owner_uid=OWNER_UID, disk_fs=cache.rig.control
    )

    outcome = executor.execute(plan=planned(cache=cache))[0]

    assert outcome.status is StepStatus.DONE
    assert not cache.model.exists()
    assert processes.signals == []
    assert processes.waits == []
