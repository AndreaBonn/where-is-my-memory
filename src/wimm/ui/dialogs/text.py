"""Italian texts of the confirmation dialogs (spec 8.3, 10)."""

from types import MappingProxyType

from wimm.model.enums import ActionKind
from wimm.ui.format import ACTION_LABELS, format_size

TITLES = MappingProxyType(
    {
        ActionKind.PROCESS_TERMINATE: "Terminare {subject}?",
        ActionKind.PROCESS_KILL: "Forzare la chiusura di {subject}?",
        ActionKind.APP_CLOSE: "Chiudere {subject}?",
        ActionKind.CONTAINER_STOP: "Fermare {subject}?",
        ActionKind.CONTAINER_REMOVE: "Rimuovere {subject}?",
        ActionKind.GROUP_STOP: "Fermare {subject}?",
        ActionKind.COMPOSE_DOWN: "Spegnere il progetto {subject}?",
        ActionKind.COMPOSE_DOWN_VOLUMES: "Spegnere il progetto {subject} e rimuovere i volumi?",
        ActionKind.STOP_ALL_IDLE_SAFE: "Fermare i programmi che non usi?",
        ActionKind.IMAGE_REMOVE: "Rimuovere l'immagine {subject}?",
        ActionKind.IMAGES_PRUNE_DANGLING: "Eliminare le immagini senza nome?",
        ActionKind.IMAGES_PRUNE_UNUSED: "Eliminare le immagini inutilizzate?",
        ActionKind.BUILDER_PRUNE: "Svuotare la cache di build?",
        ActionKind.CONTAINERS_PRUNE_STOPPED: "Eliminare i container fermi?",
        ActionKind.VOLUME_REMOVE: "Rimuovere il volume {subject}?",
        ActionKind.CACHE_CLEAN: "Pulire la cache {subject}?",
        ActionKind.TRASH_EMPTY: "Svuotare il cestino?",
        ActionKind.DEVDIR_DELETE: "Eliminare la cartella {subject}?",
        ActionKind.DISK_FREE_SAFE: "Liberare lo spazio che si ricrea da solo?",
    }
)
CANCEL_LABEL = "Annulla"
EMPTY_TEXT = "Nessuna voce selezionata: non c'è nulla da eseguire."
NO_ESTIMATE_TEXT = "Recupero non stimabile."
TOTAL_PREFIX = "Totale stimato"
SINGLE_TOTAL = "Recupero stimato"
MIXED_NAME = "questi elementi"
PHRASE_HINT = (
    "Ti chiediamo di scrivere il nome perché questa azione cancella dati in modo "
    "definitivo: serve a evitare un clic per sbaglio."
)


def dialog_title(*, kind: ActionKind, subject: str | None) -> str:
    """Question in the header: "Fermare whitebox?"."""
    return TITLES[kind].format(subject=MIXED_NAME if subject is None else subject)


def confirm_label(*, kind: ActionKind) -> str:
    """Label of the confirm button: the action's own label, without the ellipsis."""
    return ACTION_LABELS[kind]


def entry_title(*, phrase: str) -> str:
    """Title of the entry the user types the target name into."""
    return f"Scrivi {phrase} per confermare"


def reclaim_text(*, ram: int, disk: int, total: bool) -> str:
    """The estimated recovery sentence, e.g. "Recupero stimato: libera circa 1,1 GB di RAM"."""
    parts = []
    if ram > 0:
        parts.append(f"{format_size(size=ram)} di RAM")
    if disk > 0:
        parts.append(f"{format_size(size=disk)} di disco")
    if not parts:
        return NO_ESTIMATE_TEXT
    prefix = TOTAL_PREFIX if total else SINGLE_TOTAL
    return f"{prefix}: libera circa {' e '.join(parts)}."
