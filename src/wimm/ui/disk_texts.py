"""Plain-language texts of the Disco page: section explanations and the header line."""

from collections.abc import Iterable
from typing import TYPE_CHECKING

from wimm.core.sizes import format_size
from wimm.model.enums import Risk

if TYPE_CHECKING:
    from wimm.ui.disk_model import DiskSectionView

NOTHING_TO_FREE_TEXT = "Niente da liberare sul disco"
ACTIONS_NOTE = "Ogni bottone ti mostra prima cosa succede e chiede conferma."
# D4: one sentence per section, for someone who has never heard of Docker or caches.
SECTION_DESCRIPTIONS = {
    "docker": "Docker serve a far girare programmi in contenitori separati.",
    "images": "Copie scaricate per avviare i contenitori. Se servono di nuovo, si riscaricano.",
    "containers": "Contenitori spenti che occupano ancora un po' di spazio.",
    "volumes": "Dati salvati dai contenitori, per esempio un database.",
    "build_cache": "Pezzi salvati per costruire i contenitori più in fretta: si ricreano.",
    "caches": "File temporanei dei programmi di sviluppo: si ricreano da soli.",
    "devdirs": "Librerie scaricate per progetti vecchi: si reinstallano se riapri il progetto.",
    "trash": "File che hai già cancellato: svuotandolo spariscono per sempre.",
}


def disk_headline(*, sections: Iterable["DiskSectionView"]) -> str:
    """The D1 headline: what the listed rows free without deleting user data.

    "Pericolo" rows (volumes, the trash) hold data, so their bytes are not offered here.
    Empty before the first scan.
    """
    listed = tuple(sections)
    if not listed:
        return ""
    total = sum(
        row.size_bytes
        for section in listed
        for row in section.rows
        if row.action_kind and row.risk is not Risk.DANGER
    )
    if total <= 0:
        return NOTHING_TO_FREE_TEXT
    return f"Puoi liberare fino a {format_size(size=total)}"
