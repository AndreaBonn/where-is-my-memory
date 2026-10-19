from pathlib import Path

import pytest

from tests.service.cache_item_fakes import item_fingerprint, item_plan
from tests.service.fs_fakes import build_rig
from wimm.service.errors import InvalidRequest

NOT_YET = "not supported yet"


def test_an_android_avd_folder_is_refused_as_not_supported_yet(tmp_path: Path) -> None:
    home = tmp_path / "home"
    avd = home / ".android" / "avd" / "Pixel.avd"
    (avd / "data").mkdir(parents=True)
    (avd.parent / "Pixel.ini").write_text("path=x", encoding="utf-8")
    rig = build_rig(home=home)

    with pytest.raises(InvalidRequest, match=NOT_YET):
        rig.executor().execute(plan=item_plan(fingerprint=item_fingerprint(folder=avd)))
    assert (avd / "data").exists()


def test_an_android_sdk_package_folder_is_refused_as_not_supported_yet(tmp_path: Path) -> None:
    home = tmp_path / "home"
    package = home / "Android" / "Sdk" / "platforms" / "android-34"
    package.mkdir(parents=True)
    (package / "package.xml").write_text("<x/>", encoding="utf-8")
    (home / "Android" / "Sdk" / "platform-tools").mkdir()
    (home / "Android" / "Sdk" / "platform-tools" / "adb").write_text("", encoding="utf-8")
    rig = build_rig(home=home)

    with pytest.raises(InvalidRequest, match=NOT_YET):
        rig.executor().execute(plan=item_plan(fingerprint=item_fingerprint(folder=package)))
    assert (package / "package.xml").exists()
