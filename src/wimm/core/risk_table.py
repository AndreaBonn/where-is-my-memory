from enum import StrEnum

from wimm.i18n import N_
from wimm.model.enums import ActionKind, Risk


class ConsequenceKey(StrEnum):
    IDLE = "idle"
    ACTIVE = "active"
    FOREGROUND = "foreground"
    AGENT = "agent"
    BROWSER = "browser"
    DOCUMENTS = "documents"
    APP = "app"
    TERMINAL = "terminal"
    KILL = "kill"
    STOP = "stop"
    STOP_TIMEOUT = "stop_timeout"
    START = "start"
    CONTAINER_REMOVE = "container_remove"
    DOWN = "down"
    DOWN_VOLUMES = "down_volumes"
    REGISTRY = "registry"
    LOCAL_IMAGE = "local_image"
    BUILD = "build"
    VOLUME = "volume"
    CACHE = "cache"
    TRASH = "trash"
    DEVDIR = "devdir"
    OTHER = "other"


CONSEQUENCES: dict[ConsequenceKey, str] = {
    ConsequenceKey.IDLE: N_("Il server si ferma."),
    ConsequenceKey.ACTIVE: N_("È in uso adesso: chi lo sta usando perde la connessione."),
    ConsequenceKey.FOREGROUND: N_(
        "È in esecuzione in primo piano in un terminale: potresti interrompere un lavoro in corso."
    ),
    ConsequenceKey.AGENT: N_(
        "La sessione dell'agente si chiude: il lavoro non salvato nella conversazione si perde."
    ),
    ConsequenceKey.BROWSER: N_(
        # Measured in T-3.8b (docs/DEVIATIONS.md): SIGTERM is not a clean quit, the tabs
        # come back from the periodic crash-recovery file.
        "Il browser si chiude senza la chiusura normale: alla riapertura ripristina le schede "
        "dal salvataggio automatico, che può essere indietro di qualche secondo."
    ),
    ConsequenceKey.DOCUMENTS: N_("Eventuali file non salvati possono andare persi."),
    ConsequenceKey.OTHER: N_(
        "Il programma si ferma: ciò che ha in memoria e non ha salvato va perso. "
        "Se è un servizio, potrebbe riavviarsi da solo."
    ),
    ConsequenceKey.APP: N_("L'applicazione si chiude."),
    ConsequenceKey.TERMINAL: N_(
        "Si chiudono tutte le finestre e le schede del terminale e i programmi al loro interno."
    ),
    ConsequenceKey.KILL: N_("Chiusura immediata senza salvataggio."),
    ConsequenceKey.STOP: N_("Il container si ferma; dati e configurazione restano."),
    ConsequenceKey.STOP_TIMEOUT: N_(
        "Se il container non si ferma da solo, Docker lo termina dopo 10 secondi."
    ),
    ConsequenceKey.START: N_("Il container riparte con la configurazione di prima."),
    ConsequenceKey.CONTAINER_REMOVE: N_(
        "Le modifiche fatte dentro il container fuori dai volumi si perdono."
    ),
    ConsequenceKey.DOWN: N_("I container vengono rimossi; i volumi con i dati restano."),
    ConsequenceKey.DOWN_VOLUMES: N_(
        "I dati dei volumi {volumes} vengono cancellati in modo definitivo."
    ),
    ConsequenceKey.REGISTRY: N_("Si riscarica dal registry quando serve."),
    ConsequenceKey.LOCAL_IMAGE: N_(
        "Immagine costruita in locale, non è su un registry: per riaverla serve ricostruirla."
    ),
    ConsequenceKey.BUILD: N_("Le prossime build saranno più lente."),
    ConsequenceKey.VOLUME: N_("I dati del volume vengono cancellati in modo definitivo."),
    ConsequenceKey.CACHE: N_("I pacchetti si riscaricano quando servono."),
    ConsequenceKey.TRASH: N_("I file nel cestino vengono eliminati in modo definitivo."),
    ConsequenceKey.DEVDIR: N_(
        "Serve reinstallare le dipendenze (npm install o uv sync) prima di usare il progetto."
    ),
}
STATIC_ASSESSMENTS: dict[ActionKind, tuple[Risk, ConsequenceKey]] = {
    ActionKind.CONTAINER_STOP: (Risk.SAFE, ConsequenceKey.STOP),
    ActionKind.CONTAINER_REMOVE: (Risk.CAUTION, ConsequenceKey.CONTAINER_REMOVE),
    ActionKind.GROUP_STOP: (Risk.SAFE, ConsequenceKey.STOP),
    ActionKind.COMPOSE_DOWN: (Risk.CAUTION, ConsequenceKey.DOWN),
    ActionKind.BUILDER_PRUNE: (Risk.SAFE, ConsequenceKey.BUILD),
    ActionKind.VOLUME_REMOVE: (Risk.DANGER, ConsequenceKey.VOLUME),
    ActionKind.CACHE_CLEAN: (Risk.SAFE, ConsequenceKey.CACHE),
    ActionKind.TRASH_EMPTY: (Risk.DANGER, ConsequenceKey.TRASH),
    ActionKind.DEVDIR_DELETE: (Risk.CAUTION, ConsequenceKey.DEVDIR),
}
