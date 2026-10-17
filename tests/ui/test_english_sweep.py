"""In English no rendered text is Italian: the check runs on the widgets, not on the code.

A string translated at import time, or a use site that forgot ``_()``, passes every test
that runs in Italian and the source scanner too; only the rendered tree shows it.
"""

import gettext
from pathlib import Path

import pytest
from gi.repository import Adw, Gtk

from scripts.check_i18n import ITALIAN
from tests.core.disk_helpers import docker_disk, report, volume
from tests.ui.conftest import (
    WindowFactory,
    descendants,
    main_context_iterate,
    present_and_settle,
)
from tests.ui.fakes import FakeActionService, FakeDiskSource
from tests.ui.test_group_controls import one_group, open_group
from wimm import i18n
from wimm.config import Config
from wimm.model.snapshot import Snapshot
from wimm.paths import UserPaths
from wimm.ui.dialogs.preferences import PreferencesDialog

pytestmark = [pytest.mark.ui, pytest.mark.usefixtures("english")]


def translated_italian(*, locale_dir: Path) -> set[str]:
    """Italian msgids whose English differs: seeing one in English means it was not translated."""
    path = locale_dir / i18n.ENGLISH / "LC_MESSAGES" / f"{i18n.DOMAIN}.mo"
    with path.open("rb") as handle:
        catalog = gettext.GNUTranslations(handle)._catalog  # type: ignore[attr-defined]
    found = set()
    for key, msgstr in catalog.items():
        msgid = (key[0] if isinstance(key, tuple) else key).split("\x04")[-1]
        if msgid and msgstr != msgid and "{" not in msgid:
            found.add(msgid)
    return found


def shown_texts(widget: Gtk.Widget) -> set[str]:
    """Labels, button labels, tooltips, row and group titles and subtitles of a tree."""
    texts: set[str | None] = set()
    for item in (widget, *descendants(widget)):
        texts.add(item.get_tooltip_text())
        if isinstance(item, Gtk.Label):
            texts.add(item.get_text())
        if isinstance(item, Gtk.Button):
            texts.add(item.get_label())
        if isinstance(item, Adw.PreferencesRow):
            texts.add(item.get_title())
        if isinstance(item, Adw.ActionRow):
            texts.add(item.get_subtitle())
        if isinstance(item, Adw.PreferencesGroup | Adw.StatusPage):
            texts.update((item.get_title(), item.get_description()))
    return {text for text in texts if text}


def italian_left(*, texts: set[str], locale_dir: Path) -> list[str]:
    known = translated_italian(locale_dir=locale_dir)
    return sorted(text for text in texts if text in known or ITALIAN.search(text))


def test_the_overview_with_an_open_group_shows_no_italian(
    window_factory: WindowFactory, english_catalog: Path
) -> None:
    window = window_factory(FakeActionService(snapshot=one_group()))
    present_and_settle(window)
    open_group(window)

    texts = shown_texts(window)

    assert {"Memory (RAM)", "Disk space"} <= texts  # positive pair: the sweep reads English
    left = italian_left(texts=texts, locale_dir=english_catalog)
    assert left == [], "\n".join(left)


def test_the_disk_page_with_a_report_shows_no_italian(
    window_factory: WindowFactory, snapshot: Snapshot, english_catalog: Path
) -> None:
    disk = report(docker=docker_disk(volumes=(volume(name="pgdata"),)))
    window = window_factory(FakeDiskSource(snapshot=snapshot, report=disk))
    present_and_settle(window)

    texts = shown_texts(window.disk)

    assert "Check now" in texts
    left = italian_left(texts=texts, locale_dir=english_catalog)
    assert left == [], "\n".join(left)


def test_the_preferences_and_the_advanced_page_show_no_italian(
    window_factory: WindowFactory,
    snapshot: Snapshot,
    tmp_path: Path,
    english_catalog: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # What the app does on a switch: GTK and libadwaita translate their own texts with it.
    monkeypatch.setenv(name="LANGUAGE", value="en")
    service = FakeActionService(snapshot=snapshot, config=Config())
    window = window_factory(service)
    present_and_settle(window)
    paths = UserPaths(config_dir=tmp_path / "c", state_dir=tmp_path / "s", cache_dir=tmp_path)
    dialog = PreferencesDialog(source=service, paths=paths, home=tmp_path)
    dialog.present(window)
    main_context_iterate()

    texts = shown_texts(dialog) | shown_texts(dialog.advanced)

    assert {"Language", "Advanced settings"} <= texts
    left = italian_left(texts=texts, locale_dir=english_catalog)
    assert left == [], "\n".join(left)


def test_the_sweep_catches_an_untranslated_label(english_catalog: Path) -> None:
    # Positive pair for the assertions above: an Italian label must be reported.
    texts = {"Quit", "Esci", "Ferma il progetto adesso"}
    assert italian_left(texts=texts, locale_dir=english_catalog) == [
        "Esci",
        "Ferma il progetto adesso",
    ]
