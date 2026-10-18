from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from wimm.i18n import N_, _
from wimm.model.disk import CacheKind
from wimm.model.enums import ActionKind, Risk

from .tool_labels import ToolLabel


class ConsequenceKey(StrEnum):
    IDLE = "idle"
    IDLE_PROGRAM = "idle_program"
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
    CACHE_HUGGINGFACE = "cache_huggingface"
    CACHE_OLLAMA = "cache_ollama"
    CACHE_ANDROID_AVD = "cache_android_avd"
    CACHE_ANDROID_SDK = "cache_android_sdk"
    CACHE_UNLISTED = "cache_unlisted"
    TRASH = "trash"
    DEVDIR = "devdir"
    DEVDIR_REBUILD = "devdir_rebuild"
    OTHER = "other"
    TOOL_BUSY = "tool_busy"
    BUILD_DAEMON = "build_daemon"
    LANGUAGE_SERVER = "language_server"
    ANDROID_EMULATOR = "android_emulator"
    VIRTUAL_MACHINE = "virtual_machine"
    LOCAL_CLUSTER = "local_cluster"


CONSEQUENCES: dict[ConsequenceKey, str] = {
    ConsequenceKey.IDLE: N_("Il server si ferma."),
    ConsequenceKey.IDLE_PROGRAM: N_("Il programma si ferma."),
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
    ConsequenceKey.TOOL_BUSY: N_("Sta lavorando adesso: l'operazione in corso si interrompe."),
    ConsequenceKey.BUILD_DAEMON: N_(
        "Il daemon si ferma e riparte da solo alla prossima build, che sarà un po' più lenta."
    ),
    ConsequenceKey.LANGUAGE_SERVER: N_(
        "L'editor lo rilancia da solo; per qualche secondo completamento e controlli "
        "non rispondono."
    ),
    ConsequenceKey.ANDROID_EMULATOR: N_(
        "L'emulatore si chiude senza spegnere il dispositivo: ciò che l'app in prova non ha "
        "salvato si perde."
    ),
    ConsequenceKey.VIRTUAL_MACHINE: N_(
        "La macchina virtuale si ferma di colpo, come staccando la corrente: lo stato del "
        "sistema ospite non salvato si perde e il disco virtuale può danneggiarsi."
    ),
    ConsequenceKey.LOCAL_CLUSTER: N_(
        "Il cluster locale si ferma: i carichi in esecuzione al suo interno si interrompono."
    ),
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
    ConsequenceKey.CACHE_HUGGINGFACE: N_(
        "Modelli di HuggingFace: si riscaricano quando servono, anche diversi GB."
    ),
    ConsequenceKey.CACHE_OLLAMA: N_(
        "Modelli di ollama: si riscaricano con ollama pull, anche diversi GB. "
        "Quelli creati in locale con ollama create non si riscaricano da nessuna parte."
    ),
    ConsequenceKey.CACHE_ANDROID_AVD: N_(
        "Gli emulatori Android vengono cancellati con le app e i dati al loro interno: "
        "non si recuperano. Chiudi prima gli emulatori aperti, altrimenti lo spazio torna "
        "libero solo quando si chiudono."
    ),
    ConsequenceKey.CACHE_ANDROID_SDK: N_(
        "Piattaforme, build-tools e immagini di sistema si riscaricano con sdkmanager: "
        "finché non lo fai le build Android non funzionano."
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
    # Q2=A (R24): a model made locally or an AVD with data does not download again. DANGER
    # asks for the typed confirmation and is never part of "Libera spazio".
    CacheKind.HUGGINGFACE: (Risk.CAUTION, ConsequenceKey.CACHE_HUGGINGFACE),
    CacheKind.OLLAMA: (Risk.DANGER, ConsequenceKey.CACHE_OLLAMA),
    CacheKind.ANDROID_AVD: (Risk.DANGER, ConsequenceKey.CACHE_ANDROID_AVD),
    CacheKind.ANDROID_SDK: (Risk.CAUTION, ConsequenceKey.CACHE_ANDROID_SDK),
}
UNLISTED_CACHE_ASSESSMENT = (Risk.CAUTION, ConsequenceKey.CACHE_UNLISTED)

# R19: risk of terminating a recognised tool. SAFE means it comes back by itself (a build
# daemon on the next build, a language server when the editor relaunches it) and loses no
# user data; it becomes CAUTION while the tool is working. The guest state of a VM is lost.
TOOL_ASSESSMENTS: dict[ToolLabel, tuple[Risk, ConsequenceKey]] = {
    ToolLabel.GRADLE_DAEMON: (Risk.SAFE, ConsequenceKey.BUILD_DAEMON),
    ToolLabel.KOTLIN_DAEMON: (Risk.SAFE, ConsequenceKey.BUILD_DAEMON),
    ToolLabel.LANGUAGE_SERVER: (Risk.SAFE, ConsequenceKey.LANGUAGE_SERVER),
    ToolLabel.ANDROID_EMULATOR: (Risk.CAUTION, ConsequenceKey.ANDROID_EMULATOR),
    ToolLabel.VIRTUAL_MACHINE: (Risk.DANGER, ConsequenceKey.VIRTUAL_MACHINE),
    ToolLabel.KIND_CLUSTER: (Risk.CAUTION, ConsequenceKey.LOCAL_CLUSTER),
    ToolLabel.MINIKUBE_CLUSTER: (Risk.CAUTION, ConsequenceKey.LOCAL_CLUSTER),
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
