from enum import StrEnum

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
    ConsequenceKey.IDLE: "Il server si ferma. Si riavvia con lo stesso comando {location}.",
    ConsequenceKey.ACTIVE: "È in uso adesso: chi lo sta usando perde la connessione.",
    ConsequenceKey.FOREGROUND: (
        "È in esecuzione in primo piano in un terminale: potresti interrompere un lavoro in corso."
    ),
    ConsequenceKey.AGENT: (
        "La sessione dell'agente si chiude: il lavoro non salvato nella conversazione si perde."
    ),
    ConsequenceKey.BROWSER: (
        "Il browser si chiude. Le schede si recuperano solo se "
        "il ripristino della sessione è attivo."
    ),
    ConsequenceKey.DOCUMENTS: "Eventuali file non salvati possono andare persi.",
    ConsequenceKey.OTHER: (
        "Il programma si ferma: ciò che ha in memoria e non ha salvato va perso. "
        "Se è un servizio, potrebbe riavviarsi da solo."
    ),
    ConsequenceKey.APP: "L'applicazione si chiude.",
    ConsequenceKey.TERMINAL: (
        "Si chiudono tutte le finestre e le schede del terminale e i programmi al loro interno."
    ),
    ConsequenceKey.KILL: "Chiusura immediata senza salvataggio.",
    ConsequenceKey.STOP: (
        "Il container si ferma; dati e configurazione restano. "
        "Si riavvia con docker start o docker compose up."
    ),
    ConsequenceKey.STOP_TIMEOUT: (
        "Se il container non si ferma da solo, Docker lo termina dopo 10 secondi."
    ),
    ConsequenceKey.CONTAINER_REMOVE: (
        "Le modifiche fatte dentro il container fuori dai volumi si perdono."
    ),
    ConsequenceKey.DOWN: "I container vengono rimossi; i volumi con i dati restano.",
    ConsequenceKey.DOWN_VOLUMES: (
        "I dati dei volumi {volumes} vengono cancellati in modo definitivo."
    ),
    ConsequenceKey.REGISTRY: "Si riscarica dal registry quando serve.",
    ConsequenceKey.LOCAL_IMAGE: (
        "Immagine costruita in locale, non è su un registry: per riaverla serve ricostruirla."
    ),
    ConsequenceKey.BUILD: "Le prossime build saranno più lente.",
    ConsequenceKey.VOLUME: "I dati del volume vengono cancellati in modo definitivo.",
    ConsequenceKey.CACHE: "I pacchetti si riscaricano quando servono.",
    ConsequenceKey.TRASH: "I file nel cestino vengono eliminati in modo definitivo.",
    ConsequenceKey.DEVDIR: (
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
