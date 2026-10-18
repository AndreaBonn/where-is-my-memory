from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from wimm.i18n import N_, _
from wimm.model.disk import CacheKind
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
    CACHE_GIT = "cache_git"
    CACHE_BUILD = "cache_build"
    CACHE_GRADLE = "cache_gradle"
    CACHE_BROWSERS = "cache_browsers"
    CACHE_MAVEN = "cache_maven"
    CACHE_JETBRAINS = "cache_jetbrains"
    CACHE_UNLISTED = "cache_unlisted"
    TRASH = "trash"
    DEVDIR = "devdir"
    DEVDIR_REBUILD = "devdir_rebuild"
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
    ConsequenceKey.CACHE_GIT: N_("I repository git si riscaricano quando servono."),
    ConsequenceKey.CACHE_BUILD: N_("Le prossime compilazioni saranno più lente."),
    ConsequenceKey.CACHE_GRADLE: N_(
        "Le dipendenze si riscaricano e la prossima build sarà più lenta."
    ),
    ConsequenceKey.CACHE_BROWSERS: N_("I browser si riscaricano alla prossima esecuzione."),
    ConsequenceKey.CACHE_MAVEN: N_(
        "Gli artefatti installati in locale con mvn install non si riscaricano da nessuna parte: "
        "per riaverli serve ricostruire i progetti."
    ),
    ConsequenceKey.CACHE_JETBRAINS: N_(
        "Gli IDE JetBrains ricostruiscono gli indici al prossimo avvio: "
        "l'apertura dei progetti sarà più lenta."
    ),
    ConsequenceKey.CACHE_UNLISTED: N_(
        "Questo tipo di cache non è stato classificato: potrebbe contenere dati "
        "che non si riscaricano."
    ),
    ConsequenceKey.TRASH: N_("I file nel cestino vengono eliminati in modo definitivo."),
    ConsequenceKey.DEVDIR: N_(
        "Serve reinstallare le dipendenze (npm install o uv sync) prima di usare il progetto."
    ),
    ConsequenceKey.DEVDIR_REBUILD: N_(
        "Per usare di nuovo il progetto serve ricostruire la cartella con {command}."
    ),
}
# Rebuild command by folder name; ``target`` depends on the project file beside it.
DEVDIR_COMMANDS_BY_NAME: Mapping[str, str] = MappingProxyType(
    {
        "node_modules": "npm install",
        ".venv": "uv sync",
        "venv": "uv sync",
        ".tox": "uv sync",
        ".gradle": "gradle build",
        "build": "gradle build",
        ".next": "npm run build",
        ".nuxt": "npm run build",
        "vendor": "composer install",
    }
)
TARGET_COMMANDS_BY_MARKER: Mapping[str, str] = MappingProxyType(
    {"Cargo.toml": "cargo build", "pom.xml": "mvn package"}
)
TARGET_DIRNAME = "target"


def devdir_consequence(*, folder_name: str, marker: str) -> str:
    """Return the consequence text of deleting a development folder, in the active language.

    Parameters
    ----------
    folder_name : str
        Name of the folder (not a path).
    marker : str
        Project file found beside it, empty when unknown.

    Returns
    -------
    str
        The text naming the rebuild command, or the generic text when the folder kind is
        not recognised (an unlisted name, or ``target`` without a known marker).
    """
    if folder_name == TARGET_DIRNAME:
        command = TARGET_COMMANDS_BY_MARKER.get(marker)
    else:
        command = DEVDIR_COMMANDS_BY_NAME.get(folder_name)
    if command is None:
        return _(CONSEQUENCES[ConsequenceKey.DEVDIR])
    return _(CONSEQUENCES[ConsequenceKey.DEVDIR_REBUILD]).format(command=command)


# R13: cleaning a cache is rated by its type. A type missing here is CAUTION (S18), never SAFE.
CACHE_ASSESSMENTS: dict[CacheKind, tuple[Risk, ConsequenceKey]] = {
    CacheKind.UV: (Risk.SAFE, ConsequenceKey.CACHE),
    CacheKind.NPM: (Risk.SAFE, ConsequenceKey.CACHE),
    CacheKind.PIP: (Risk.SAFE, ConsequenceKey.CACHE),
    CacheKind.THUMBNAILS: (Risk.SAFE, ConsequenceKey.CACHE),
    CacheKind.CARGO_REGISTRY: (Risk.SAFE, ConsequenceKey.CACHE),
    CacheKind.CARGO_GIT: (Risk.SAFE, ConsequenceKey.CACHE_GIT),
    CacheKind.GRADLE: (Risk.SAFE, ConsequenceKey.CACHE_GRADLE),
    CacheKind.MAVEN: (Risk.CAUTION, ConsequenceKey.CACHE_MAVEN),
    CacheKind.GO_MOD: (Risk.SAFE, ConsequenceKey.CACHE),
    CacheKind.GO_BUILD: (Risk.SAFE, ConsequenceKey.CACHE_BUILD),
    CacheKind.YARN: (Risk.SAFE, ConsequenceKey.CACHE),
    CacheKind.PNPM: (Risk.SAFE, ConsequenceKey.CACHE),
    CacheKind.BUN: (Risk.SAFE, ConsequenceKey.CACHE),
    CacheKind.CONDA: (Risk.SAFE, ConsequenceKey.CACHE),
    CacheKind.PLAYWRIGHT: (Risk.SAFE, ConsequenceKey.CACHE_BROWSERS),
    CacheKind.JETBRAINS: (Risk.CAUTION, ConsequenceKey.CACHE_JETBRAINS),
}
UNLISTED_CACHE_ASSESSMENT = (Risk.CAUTION, ConsequenceKey.CACHE_UNLISTED)

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
