from dataclasses import replace
from pathlib import Path

import pytest

from tests.core.disk_helpers import report
from tests.core.planning_disk_helpers import _plan
from tests.service.android_item_fakes import android_rig
from wimm.model import CacheEntry, CacheItem, CacheItemKind, CacheKind
from wimm.model.cache_items import ItemBlob
from wimm.model.enums import ActionKind, Risk
from wimm.model.errors import InvalidRequest
from wimm.service.executor_cache_item_command import planning_report


@pytest.mark.parametrize("avd", [False, True])
@pytest.mark.parametrize("available", [False, True])
def test_android_planning_requires_tool(tmp_path: Path, avd: bool, available: bool) -> None:
    rig, folder = android_rig(home=tmp_path / "home", avd=avd)
    kind = CacheKind.ANDROID_AVD if avd else CacheKind.ANDROID_SDK
    item = CacheItem(
        id="Pixel" if avd else "platforms;android-34",
        title="Android item",
        path=str(folder),
        size=4096,
        st_ino=folder.stat().st_ino,
        st_dev=folder.stat().st_dev,
        kind=CacheItemKind.ANDROID_AVD if avd else CacheItemKind.ANDROID_PACKAGE,
        # A device goes with its .ini (android_rig writes one): without it nothing is offered.
        blobs=(ItemBlob(path="Pixel.ini", size=1, st_ino=7, st_dev=1),) if avd else (),
    )
    entry = CacheEntry(
        kind=kind,
        path=str(folder.parent if avd else folder.parent.parent),
        size=item.size,
        st_ino=1,
        st_dev=1,
        items=(item,),
    )
    disk = report(caches=(entry,))
    control = rig.control if available else replace(rig.control, which=lambda name: None)
    filtered = planning_report(report=disk, control=control)
    if available:
        plan = _plan(
            kind=ActionKind.CACHE_ITEM_REMOVE, disk=filtered, target=f"{kind.value}:{item.id}"
        )
        assert plan.steps[0].risk is (Risk.DANGER if avd else Risk.CAUTION)
    else:
        with pytest.raises(InvalidRequest):
            _plan(
                kind=ActionKind.CACHE_ITEM_REMOVE, disk=filtered, target=f"{kind.value}:{item.id}"
            )
    assert disk.caches[0].items == (item,)


def test_service_context_withholds_android_without_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from tests.core.planning_helpers import NOW, OWNER_UID
    from wimm.service.app_service_disk import DiskMixin

    rig, folder = android_rig(home=tmp_path / "home")
    item = CacheItem(
        id="platforms;android-34",
        title="Android package",
        path=str(folder),
        size=4096,
        st_ino=folder.stat().st_ino,
        st_dev=folder.stat().st_dev,
        kind=CacheItemKind.ANDROID_PACKAGE,
    )
    disk = report(
        caches=(
            CacheEntry(
                kind=CacheKind.ANDROID_SDK,
                path=str(folder.parent.parent),
                size=item.size,
                st_ino=1,
                st_dev=1,
                items=(item,),
            ),
        )
    )
    service = DiskMixin()
    monkeypatch.setattr(
        service, "_actions", SimpleNamespace(executor=rig.executor()), raising=False
    )
    monkeypatch.setattr(service, "_disk_report", disk, raising=False)
    monkeypatch.setattr(service, "_clock", lambda: NOW, raising=False)
    context = service._planning_context(owner_uid=OWNER_UID, stopped={}, engines=())
    assert context.disk_report is not None
    assert context.disk_report.caches[0].items == (item,)
    rig.control = replace(rig.control, which=lambda name: None)
    monkeypatch.setattr(service, "_actions", SimpleNamespace(executor=rig.executor()))
    context = service._planning_context(owner_uid=OWNER_UID, stopped={}, engines=())
    assert context.disk_report is not None
    assert context.disk_report.caches[0].items == ()
