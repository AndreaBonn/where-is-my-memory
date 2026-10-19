from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from gi.repository import Adw, Gtk

from tests.ui.conftest import (
    FakeActionService,
    descendants,
)
from wimm.config import Config
from wimm.model.snapshot import Snapshot
from wimm.paths import UserPaths
from wimm.ui.dialogs.preferences import PreferencesDialog


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / "dev").mkdir()
    return tmp_path


@pytest.fixture
def paths(home: Path) -> UserPaths:
    return UserPaths(config_dir=home / "c", state_dir=home / "s", cache_dir=home / "k")


@pytest.fixture
def service(snapshot: Snapshot, home: Path) -> FakeActionService:
    config = replace(
        Config(),
        sample_interval_s=45,
        activity_window_s=1800,
        devdirs_roots=(home / "dev",),
        extra_protected_names=("sshd",),
    )
    return FakeActionService(snapshot=snapshot, config=config)


def spin(dialog: PreferencesDialog, key: str) -> Adw.SpinRow:
    row = dialog.fields[key].row
    assert isinstance(row, Adw.SpinRow)
    return row


def tree(dialog: PreferencesDialog) -> Iterator[Gtk.Widget]:
    child = dialog.get_child()
    assert child is not None
    return descendants(child)
