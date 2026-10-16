from pathlib import Path

import pytest

ISOLATED_DIRECTORIES = {
    "HOME": "home",
    "XDG_CONFIG_HOME": "config",
    "XDG_DATA_HOME": "data",
    "XDG_STATE_HOME": "state",
    "XDG_CACHE_HOME": "cache",
}


@pytest.fixture(autouse=True)
def isolate_user_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for variable, directory in ISOLATED_DIRECTORIES.items():
        target = tmp_path / directory
        target.mkdir()
        monkeypatch.setenv(name=variable, value=str(target))
    monkeypatch.setenv(name="WIMM_TEST", value="1")
