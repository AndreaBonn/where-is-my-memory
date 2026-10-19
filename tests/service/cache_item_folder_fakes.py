"""A Playwright and a JetBrains cache in a tmpdir, and Android folders the executor refuses."""

from dataclasses import dataclass
from pathlib import Path

from tests.service.cache_item_fakes import item_fingerprint, item_plan
from tests.service.fs_fakes import FsRig, build_rig
from wimm.model.actions import Plan

BROWSER = "chromium-1181"
PRODUCT = "PyCharm2025.1"
FILE_BYTES = 8192


@dataclass(slots=True)
class FolderCaches:
    rig: FsRig
    playwright: Path
    jetbrains: Path

    @property
    def browser(self) -> Path:
        return self.playwright / BROWSER

    @property
    def product(self) -> Path:
        return self.jetbrains / PRODUCT


def _fill(folder: Path) -> None:
    (folder / "bin").mkdir(parents=True)
    (folder / "bin" / "tool").write_bytes(b"x" * FILE_BYTES)


def build_folder_caches(*, home: Path) -> FolderCaches:
    playwright = home / ".cache" / "ms-playwright"
    jetbrains = home / ".cache" / "JetBrains"
    _fill(playwright / BROWSER)
    _fill(playwright / "firefox-1490")
    _fill(jetbrains / PRODUCT)
    return FolderCaches(rig=build_rig(home=home), playwright=playwright, jetbrains=jetbrains)


def plan_for(*, folder: Path) -> Plan:
    return item_plan(fingerprint=item_fingerprint(folder=folder))
