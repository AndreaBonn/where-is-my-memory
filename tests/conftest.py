import shutil
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

ISOLATED_DIRECTORIES = {
    "HOME": "home",
    "XDG_CONFIG_HOME": "config",
    "XDG_DATA_HOME": "data",
    "XDG_STATE_HOME": "state",
    "XDG_CACHE_HOME": "cache",
}
REMOVAL_ENTRY_POINTS = ("empty_directory", "remove_directory")
EN_CATALOG = Path(__file__).resolve().parents[1] / "po" / "en.po"


@pytest.fixture(autouse=True)
def isolate_user_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for variable, directory in ISOLATED_DIRECTORIES.items():
        target = tmp_path / directory
        target.mkdir()
        monkeypatch.setenv(name=variable, value=str(target))
    monkeypatch.setenv(name="WIMM_TEST", value="1")
    # The app exports the chosen language here for GTK: restore it after every test.
    # setenv first: delenv of an absent variable records nothing to undo.
    monkeypatch.setenv(name="LANGUAGE", value="")
    monkeypatch.delenv(name="LANGUAGE")


@pytest.fixture(autouse=True)
def italian_language() -> Iterator[None]:
    """Run every test in the source language and leave it there for the next one."""
    from wimm import i18n

    i18n.set_language(language=i18n.ITALIAN)
    yield
    i18n.set_language(language=i18n.ITALIAN)


@pytest.fixture
def english_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Compile the real po/en.po and make it the catalog every set_language() call reads."""
    from wimm import i18n

    msgfmt = shutil.which("msgfmt")
    if msgfmt is None:
        pytest.skip("msgfmt not installed (apt package gettext)")
    target = tmp_path / "locale" / i18n.ENGLISH / "LC_MESSAGES"
    target.mkdir(parents=True)
    subprocess.run(  # noqa: S603 - fixed argv, paths created by this fixture
        [msgfmt, "--check-format", "-o", str(target / f"{i18n.DOMAIN}.mo"), str(EN_CATALOG)],
        check=True,
    )
    monkeypatch.setattr(i18n, "LOCALE_DIR", tmp_path / "locale")
    return tmp_path / "locale"


@pytest.fixture
def english(english_catalog: Path) -> Iterator[None]:
    """Switch to English with the shipped catalog; the next test starts in Italian again."""
    from wimm import i18n

    i18n.set_language(language=i18n.ENGLISH)
    yield
    i18n.set_language(language=i18n.ITALIAN)


@pytest.fixture(autouse=True)
def guard_removals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Fail the test if an executor removal is aimed outside its tmpdir (plan S3).

    The removal is refused before it touches anything, and the escape is recorded: the
    executor turns an exception into a failed step, so only this list fails the test.
    A test that provokes an escape on purpose clears the yielded list.
    """
    from wimm.service import executor_disk_fs

    allowed = tmp_path.resolve()
    escapes: list[str] = []

    def guarded(real: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*, fingerprint: Any, **options: Any) -> Any:
            if not Path(fingerprint.realpath).resolve().is_relative_to(allowed):
                escapes.append(fingerprint.realpath)
                raise AssertionError(f"removal aimed outside the tmpdir: {fingerprint.realpath}")
            return real(fingerprint=fingerprint, **options)

        return wrapper

    for name in REMOVAL_ENTRY_POINTS:
        monkeypatch.setattr(executor_disk_fs, name, guarded(getattr(executor_disk_fs, name)))
    yield escapes
    assert escapes == [], f"executor aimed a removal outside the tmpdir: {escapes}"
