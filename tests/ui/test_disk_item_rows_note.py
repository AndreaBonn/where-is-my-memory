"""An item sub-row without action says why, on the line where the consequence would be."""

from wimm.ui.disk_model import DiskRowView
from wimm.ui.pages.disk_item_rows import item_accessible_name, item_subtitle

REASON = "Il server ollama attivo è quello di sistema e non vede questi modelli"


def _row(*, consequence: str = "", note: str = "") -> DiskRowView:
    return DiskRowView(
        title="tinymodel:latest",
        subtitle="/home/u/.ollama/models/manifests/registry.ollama.ai/library/tinymodel/latest",
        size_text="209 kB",
        consequence=consequence,
        note=note,
    )


def test_an_item_without_action_shows_its_reason_under_the_path() -> None:
    row = _row(note=REASON)
    assert item_subtitle(row=row) == f"{row.subtitle}\n{REASON}"
    assert REASON in item_accessible_name(row=row)


def test_an_item_with_an_action_shows_its_consequence_and_no_reason() -> None:
    row = _row(consequence="Il modello si riscarica con ollama pull.")
    assert item_subtitle(row=row) == f"{row.subtitle}\nIl modello si riscarica con ollama pull."
    assert REASON not in item_accessible_name(row=row)


def test_an_item_with_neither_shows_only_the_path() -> None:
    row = _row()
    assert item_subtitle(row=row) == row.subtitle
