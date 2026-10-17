"""Italian texts of the confirmation dialogs (spec 8.3, 10)."""

from types import MappingProxyType

from wimm.i18n import N_, _
from wimm.model.enums import ActionKind
from wimm.ui.format import ACTION_LABELS, format_size

TITLES = MappingProxyType(
    {
        ActionKind.PROCESS_TERMINATE: N_("Terminare {subject}?"),
        ActionKind.PROCESS_KILL: N_("Forzare la chiusura di {subject}?"),
        ActionKind.APP_CLOSE: N_("Chiudere {subject}?"),
        ActionKind.CONTAINER_STOP: N_("Fermare {subject}?"),
        ActionKind.CONTAINER_REMOVE: N_("Rimuovere {subject}?"),
        ActionKind.GROUP_STOP: N_("Fermare {subject}?"),
        ActionKind.COMPOSE_DOWN: N_("Spegnere il progetto {subject}?"),
        ActionKind.COMPOSE_DOWN_VOLUMES: N_("Spegnere il progetto {subject} e rimuovere i volumi?"),
        ActionKind.STOP_ALL_IDLE_SAFE: N_("Fermare i programmi che non usi?"),
        ActionKind.IMAGE_REMOVE: N_("Rimuovere l'immagine {subject}?"),
        ActionKind.IMAGES_PRUNE_DANGLING: N_("Eliminare le immagini senza nome?"),
        ActionKind.IMAGES_PRUNE_UNUSED: N_("Eliminare le immagini inutilizzate?"),
        ActionKind.BUILDER_PRUNE: N_("Svuotare la cache di build?"),
        ActionKind.CONTAINERS_PRUNE_STOPPED: N_("Eliminare i container fermi?"),
        ActionKind.VOLUME_REMOVE: N_("Rimuovere il volume {subject}?"),
        ActionKind.CACHE_CLEAN: N_("Pulire la cache {subject}?"),
        ActionKind.TRASH_EMPTY: N_("Svuotare il cestino?"),
        ActionKind.DEVDIR_DELETE: N_("Eliminare la cartella {subject}?"),
        ActionKind.DISK_FREE_SAFE: N_("Liberare lo spazio che si ricrea da solo?"),
        ActionKind.CONTAINER_START: N_("Riaccendere {subject}?"),
        ActionKind.RESTART_STOPPED: N_("Riaccendere i contenitori appena fermati?"),
    }
)
CANCEL_LABEL = N_("Annulla")
EMPTY_TEXT = N_("Nessuna voce selezionata: non c'è nulla da eseguire.")
# C4: a restart frees nothing, so the body says what it gives back instead.
RESTART_TEXT = N_("Ripartono come prima e tornano a usare la loro memoria.")
NO_ESTIMATE_TEXT = N_("Quanto si libera non si può stimare prima.")
TOTAL_PREFIX = N_("In tutto liberi circa")
SINGLE_TOTAL = N_("Liberi circa")
# C1: a listed amount larger than the plan by more than this share gets explained.
LISTED_TOLERANCE = 1.05
MIXED_NAME = N_("questi elementi")
PHRASE_HINT = N_(
    "Ti chiediamo di scrivere il nome perché questa azione cancella dati in modo "
    "definitivo: serve a evitare un clic per sbaglio."
)


def dialog_title(*, kind: ActionKind, subject: str | None) -> str:
    """Question in the header: "Fermare whitebox?"."""
    return _(TITLES[kind]).format(subject=_(MIXED_NAME) if subject is None else subject)


def confirm_label(*, kind: ActionKind) -> str:
    """Label of the confirm button: the action's own label, without the ellipsis."""
    return _(ACTION_LABELS[kind])


def entry_title(*, phrase: str) -> str:
    """Title of the entry the user types the target name into."""
    return _("Scrivi {phrase} per confermare").format(phrase=phrase)


def reclaim_text(*, ram: int, disk: int, total: bool) -> str:
    """The estimated recovery sentence, e.g. "Liberi circa 1,1 GB di memoria."."""
    prefix = _(TOTAL_PREFIX) if total else _(SINGLE_TOTAL)
    ram_size, disk_size = format_size(size=ram), format_size(size=disk)
    if ram > 0 and disk > 0:
        both = _("{prefix} {ram} di memoria e {disk} di spazio sul disco.")
        return both.format(prefix=prefix, ram=ram_size, disk=disk_size)
    if ram > 0:
        return _("{prefix} {ram} di memoria.").format(prefix=prefix, ram=ram_size)
    if disk > 0:
        return _("{prefix} {disk} di spazio sul disco.").format(prefix=prefix, disk=disk_size)
    return _(NO_ESTIMATE_TEXT)


def listed_note(*, listed: int | None, planned: int) -> str | None:
    """C1: why the list shows more than the plan frees (parts that cannot be stopped here)."""
    if listed is None or listed <= planned * LISTED_TOLERANCE:
        return None
    return _("Nella lista conta {listed}: il resto è di parti che non si fermano da qui.").format(
        listed=format_size(size=listed)
    )
