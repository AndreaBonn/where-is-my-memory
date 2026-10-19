"""Plain-language texts of the Disco page: section explanations and the header line."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from wimm.core.sizes import format_size
from wimm.i18n import N_, _
from wimm.model.enums import Risk

if TYPE_CHECKING:
    from wimm.ui.disk_model import DiskSectionView

MISSING_ROOT_TEXT = N_("La cartella {path} non esiste")
REFUSED_ROOT_TEXT = N_("La cartella {path} non viene usata. {reason}")
NO_ROOTS_TITLE = N_("Nessuna cartella di progetti trovata")
NO_ROOTS_TEXT = N_("Indica dove tieni i tuoi progetti e cerco le librerie che si possono liberare.")
CHOOSE_FOLDER_LABEL = N_("Scegli una cartella")
NOTHING_TO_FREE_TEXT = N_("Niente da liberare sul disco")
NOTHING_SAFE_TEXT = N_("Niente da liberare senza perdere qualcosa")
SAFE_HEADLINE = N_("Puoi liberare {size} senza perdere niente")
REVIEW_MORE_TEXT = N_("Altri {size} se accetti di riscaricare o ricostruire")
REVIEW_ONLY_TEXT = N_("{size} si liberano se accetti di riscaricare o ricostruire")
SELECTED_LABEL = N_("Libera i selezionati")
ACTIONS_NOTE = N_("Ogni bottone ti mostra prima cosa succede e chiede conferma.")
# D4: one sentence per section, for someone who has never heard of Docker or caches.
SECTION_DESCRIPTIONS = {
    "docker": N_("Docker serve a far girare programmi in contenitori separati."),
    "images": N_(
        "Copie per avviare i contenitori: quelle costruite qui si ricostruiscono, "
        "non si riscaricano."
    ),
    "images_safe": N_("Copie scaricate che nessun contenitore usa: si riscaricano quando servono."),
    "caches_review": N_("Si ricreano, ma riscaricarle costa tempo o molti dati."),
    "caches_data": N_(
        "Modelli AI ed emulatori Android: dentro ci sono dati che non tornano uguali."
    ),
    "containers": N_("Contenitori spenti che occupano ancora un po' di spazio."),
    "volumes": N_("Dati salvati dai contenitori, per esempio un database."),
    "build_cache": N_("Pezzi salvati per costruire i contenitori più in fretta: si ricreano."),
    "caches": N_("File temporanei dei programmi di sviluppo: si ricreano da soli."),
    "devdirs": N_("Librerie scaricate per progetti vecchi: si reinstallano se riapri il progetto."),
    "trash": N_("File che hai già cancellato: svuotandolo spariscono per sempre."),
}


# D3: sections grouped by what freeing them costs, cheapest first.
TIER_TITLES = {
    "safe": N_("Si libera senza pensarci"),
    "review": N_("Da guardare prima"),
    "data": N_("Attenzione: cancella dati"),
}
TIER_DESCRIPTIONS = {
    "safe": N_("Si ricrea da solo quando serve."),
    "review": N_("Si può riscaricare o ricreare, ma con un po' di lavoro."),
    "data": N_("Dentro possono esserci database o file che non si recuperano."),
}
SECTION_TIERS = {
    "caches": "safe",
    "build_cache": "safe",
    "images_safe": "safe",
    "caches_review": "review",
    "images": "review",
    "containers": "review",
    "docker": "notice",
    "devdirs": "review",
    "caches_data": "data",
    "volumes": "data",
    "trash": "data",
}
SAFE_CAPTION = N_("Pulisce solo ciò che si ricrea da solo: il cestino e i tuoi dati restano.")


@dataclass(frozen=True, slots=True)
class DiskTotals:
    """What the listed rows free: `safe` without losing anything, `review` at a rebuild cost.

    "Pericolo" rows (volumes, the trash) hold data: their bytes are in neither.
    """

    safe: int
    review: int


def disk_totals(*, sections: Iterable["DiskSectionView"]) -> DiskTotals | None:
    """The two totals over the actionable rows; None before the first scan."""
    listed = tuple(sections)
    if not listed:
        return None
    rows = [row for section in listed for row in section.rows if row.action_kind]
    safe = sum(row.size_bytes for row in rows if row.risk is Risk.SAFE)
    review = sum(row.size_bytes for row in rows if row.risk is Risk.CAUTION)
    return DiskTotals(safe=safe, review=review)


def safe_label(*, sections: Iterable["DiskSectionView"]) -> str:
    """D2: "Libera X senza rischi" over the safe rows, empty when there is none."""
    totals = disk_totals(sections=sections)
    if totals is None or totals.safe <= 0:
        return ""
    return _("Libera {size} senza rischi").format(size=format_size(size=totals.safe))


def selected_label(*, count: int, total_bytes: int) -> str:
    """S16: "Libera i selezionati (2, 1,2 GB)"; the plain action label while nothing is ticked."""
    if count <= 0:
        return _(SELECTED_LABEL)
    return _("Libera i selezionati ({count}, {size})").format(
        count=count, size=format_size(size=total_bytes)
    )


def disk_headline(*, sections: Iterable["DiskSectionView"]) -> str:
    """The D1 headline: what the disk frees without losing anything; empty before a scan."""
    totals = disk_totals(sections=sections)
    if totals is None:
        return ""
    if totals.safe > 0:
        return _(SAFE_HEADLINE).format(size=format_size(size=totals.safe))
    return _(NOTHING_SAFE_TEXT) if totals.review > 0 else _(NOTHING_TO_FREE_TEXT)


def review_text(*, totals: DiskTotals | None) -> str:
    """What else frees at the cost of a download or a rebuild; empty when nothing does."""
    if totals is None or totals.review <= 0:
        return ""
    template = REVIEW_MORE_TEXT if totals.safe > 0 else REVIEW_ONLY_TEXT
    return _(template).format(size=format_size(size=totals.review))


# Sub-rows of a cache with items (S5, S8): the two rows that no single item owns.
SHARED_ROW_TITLE = N_("Condiviso fra più elementi")
SHARED_ROW_TEXT = N_("File usati da più di un elemento: restano finché ne resta uno.")
UNATTRIBUTED_ROW_TITLE = N_("Non attribuito")
UNATTRIBUTED_ROW_TEXT = N_(
    "File che nessun elemento usa, file di blocco e file alla radice della cache. "
    "Si liberano solo pulendo tutta la cache."
)
