"""Plain-language texts of the Disco page: section explanations and the header line."""

from collections.abc import Iterable
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
ACTIONS_NOTE = N_("Ogni bottone ti mostra prima cosa succede e chiede conferma.")
# D4: one sentence per section, for someone who has never heard of Docker or caches.
SECTION_DESCRIPTIONS = {
    "docker": N_("Docker serve a far girare programmi in contenitori separati."),
    "images": N_("Copie scaricate per avviare i contenitori. Se servono di nuovo, si riscaricano."),
    "containers": N_("Contenitori spenti che occupano ancora un po' di spazio."),
    "volumes": N_("Dati salvati dai contenitori, per esempio un database."),
    "build_cache": N_("Pezzi salvati per costruire i contenitori più in fretta: si ricreano."),
    "caches": N_("File temporanei dei programmi di sviluppo: si ricreano da soli."),
    "devdirs": N_("Librerie scaricate per progetti vecchi: si reinstallano se riapri il progetto."),
    "trash": N_("File che hai già cancellato: svuotandolo spariscono per sempre."),
}


# R24: the rows of the model and Android caches, whose cleaning costs more than a download.
MODEL_CACHE_TITLES = {
    "huggingface": N_("Modelli HuggingFace"),
    "ollama": N_("Modelli ollama"),
    "android_avd": N_("Emulatori Android (AVD)"),
    "android_sdk": N_("SDK Android"),
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
    "images": "review",
    "containers": "review",
    "docker": "notice",
    "devdirs": "review",
    "volumes": "data",
    "trash": "data",
}
SAFE_CAPTION = N_("Pulisce solo ciò che si ricrea da solo: il cestino e i tuoi dati restano.")


def safe_label(*, sections: Iterable["DiskSectionView"]) -> str:
    """D2: "Libera X senza rischi" over the safe rows, empty when there is none."""
    total = sum(
        row.size_bytes
        for section in sections
        for row in section.rows
        if row.action_kind and row.risk is Risk.SAFE
    )
    return _("Libera {size} senza rischi").format(size=format_size(size=total)) if total > 0 else ""


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
        return _(NOTHING_TO_FREE_TEXT)
    return _("Puoi liberare fino a {size}").format(size=format_size(size=total))
