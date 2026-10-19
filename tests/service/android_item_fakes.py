"""Android caches confined to a test home, with a fake command runner."""

from pathlib import Path

from tests.service.fs_fakes import FsRig, build_rig


def android_rig(*, home: Path, avd: bool = False) -> tuple[FsRig, Path]:
    sdk = home / "Android/Sdk"
    folder = home / ".android/avd/Pixel.avd" if avd else sdk / "platforms/android-34"
    folder.mkdir(parents=True)
    (folder / ("config.ini" if avd else "package.xml")).write_text("x", encoding="utf-8")
    if avd:
        # avdmanager deletes the folder this file names (path.rel is not used by the guard).
        ini = f"avd.ini.encoding=UTF-8\npath={folder}\npath.rel=avd/Pixel.avd\n"
        (folder.parent / "Pixel.ini").write_text(ini, encoding="utf-8")
    (sdk / "platform-tools").mkdir(parents=True)
    (sdk / "platform-tools/adb").touch()
    return build_rig(home=home), folder
