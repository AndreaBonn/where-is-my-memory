"""The name each cache goes by on screen: the Disco page row, the confirmation, the outcome."""

from types import MappingProxyType

from wimm.i18n import N_
from wimm.model.disk import CacheKind

# Tool names stay untranslated; the rest are marked for the catalog.
CACHE_TITLES = MappingProxyType(
    {
        CacheKind.UV: "uv",
        CacheKind.NPM: "npm",
        CacheKind.PIP: "pip",
        CacheKind.THUMBNAILS: N_("Miniature"),
        CacheKind.TRASH: N_("Cestino"),
        CacheKind.CARGO_REGISTRY: N_("Cargo (pacchetti)"),
        CacheKind.CARGO_GIT: N_("Cargo (repository git)"),
        CacheKind.GRADLE: N_("Gradle"),
        CacheKind.MAVEN: N_("Maven"),
        CacheKind.GO_MOD: N_("Go (moduli)"),
        CacheKind.GO_BUILD: N_("Go (compilazione)"),
        CacheKind.YARN: "yarn",
        CacheKind.PNPM: "pnpm",
        CacheKind.BUN: "bun",
        CacheKind.CONDA: "conda",
        CacheKind.PLAYWRIGHT: N_("Playwright"),
        CacheKind.JETBRAINS: "JetBrains",
        # R24: model and Android caches, whose cleaning costs more than a download.
        CacheKind.HUGGINGFACE: N_("Modelli HuggingFace"),
        CacheKind.OLLAMA: N_("Modelli ollama"),
        CacheKind.OLLAMA_SYSTEM: N_("Modelli ollama (sistema)"),
        CacheKind.ANDROID_AVD: N_("Emulatori Android (AVD)"),
        CacheKind.ANDROID_SDK: N_("SDK Android"),
    }
)
