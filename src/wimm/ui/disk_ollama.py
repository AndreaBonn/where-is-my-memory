"""When an ollama model row may offer "Rimuovi", and the reason it does not (T-6.39, D1).

`ollama rm` deletes from the store of the server that answers, so the page offers it only
for the models that server owns: the home ones in S1, the system ones in S2. In every other
situation the row stays, without an action, and says why in one line.
"""

from wimm.core.item_tools import is_item_removable
from wimm.core.ollama_names import is_valid_model_name
from wimm.core.ollama_served import ServedStore
from wimm.i18n import N_, _
from wimm.model.cache_items import CacheItem
from wimm.model.disk import CacheKind
from wimm.model.enums import CacheItemKind

OLLAMA_SYSTEM_SUBTITLE = N_("dimensioni stimate da ollama")
_REASONS: dict[ServedStore, str] = {
    ServedStore.NONE: N_("Avvia ollama per rimuovere un modello"),
    ServedStore.USER_OTHER: N_("Il server ollama attivo usa un'altra cartella di modelli"),
    ServedStore.SYSTEM: N_("Il server ollama attivo è quello di sistema e non vede questi modelli"),
    ServedStore.AMBIGUOUS: N_(
        "Con più di un server ollama non so quale risponde: avvia solo il tuo per rimuovere"
    ),
}
# Which server situation owns the models of each ollama cache.
_OWNER: dict[CacheKind, ServedStore] = {
    CacheKind.OLLAMA: ServedStore.USER_HOME,
    CacheKind.OLLAMA_SYSTEM: ServedStore.SYSTEM,
}


def parse_served(*, value: str) -> ServedStore | None:
    """The situation a report carries; None when it is empty or not one we know."""
    try:
        return ServedStore(value)
    except ValueError:
        return None


def ollama_offer(
    *, kind: CacheKind, item: CacheItem, served: ServedStore | None
) -> tuple[bool, str]:
    """(offered, reason): whether this item may offer removal, and the line saying why not.

    Not an ollama model: offered by the other rules, no reason. An invalid name is never
    offered and gets no reason (the name is the problem, not the server).
    """
    if item.kind is not CacheItemKind.OLLAMA_MODEL or kind not in _OWNER:
        return is_item_removable(item=item), ""
    if not is_valid_model_name(name=item.id):
        return False, ""
    if served is _OWNER[kind]:
        return True, ""
    return False, _(_REASONS[served or ServedStore.AMBIGUOUS])
