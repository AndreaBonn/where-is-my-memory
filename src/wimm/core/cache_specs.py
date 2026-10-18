"""The cache types of the disk report as data (SPECIFICHE 7.6, R12): no logic here."""

from dataclasses import dataclass
from enum import StrEnum

from wimm.model.disk import CacheKind


class CacheBase(StrEnum):
    HOME = "home"
    XDG_CACHE = "xdg_cache"


@dataclass(frozen=True, slots=True, kw_only=True)
class CacheSpec:
    """One cache type: ``relative`` under ``base``, or where a variable points.

    ``env_var`` (then ``env_aliases``) names the cache folder as ``<value>/<env_subpath>``.
    ``fallback_var`` is read when those are unset: its first entry plus ``fallback_subpath``.
    ``list_separator`` marks a variable that holds a list, of which the first entry counts.
    ``command`` is the tool's own cleaning command, as unverified data.

    Sentinels say a redirected folder really is this tool's cache: one of
    ``sentinel_files`` (specific to the tool) or two of ``sentinel_entries`` (generic names
    that a user folder could have alone). ``CACHEDIR.TAG`` always counts too.
    """

    kind: CacheKind
    base: CacheBase
    relative: str
    env_var: str | None = None
    env_aliases: tuple[str, ...] = ()
    env_subpath: str = ""
    list_separator: str = ""
    fallback_var: str | None = None
    fallback_subpath: str = ""
    command: tuple[str, ...] | None = None
    sentinel_files: tuple[str, ...] = ()
    sentinel_entries: tuple[str, ...] = ()


_HOME = CacheBase.HOME
_XDG = CacheBase.XDG_CACHE

CACHE_SPECS: tuple[CacheSpec, ...] = (
    CacheSpec(kind=CacheKind.UV, base=_XDG, relative="uv", env_var="UV_CACHE_DIR"),
    CacheSpec(
        kind=CacheKind.NPM,
        base=_HOME,
        relative=".npm/_cacache",
        env_var="npm_config_cache",
        env_aliases=("NPM_CONFIG_CACHE",),
        env_subpath="_cacache",
        sentinel_files=("index-v5",),
    ),
    CacheSpec(
        kind=CacheKind.PIP,
        base=_XDG,
        relative="pip",
        env_var="PIP_CACHE_DIR",
        sentinel_entries=("http-v2", "http", "wheels"),
    ),
    CacheSpec(kind=CacheKind.TRASH, base=_HOME, relative=".local/share/Trash"),
    CacheSpec(kind=CacheKind.THUMBNAILS, base=_XDG, relative="thumbnails"),
    CacheSpec(
        kind=CacheKind.CARGO_REGISTRY,
        base=_HOME,
        relative=".cargo/registry",
        env_var="CARGO_HOME",
        env_subpath="registry",
        sentinel_entries=("cache", "index", "src"),
    ),
    CacheSpec(
        kind=CacheKind.CARGO_GIT,
        base=_HOME,
        relative=".cargo/git",
        env_var="CARGO_HOME",
        env_subpath="git",
        sentinel_entries=("db", "checkouts"),
    ),
    CacheSpec(
        kind=CacheKind.GRADLE,
        base=_HOME,
        relative=".gradle/caches",
        env_var="GRADLE_USER_HOME",
        env_subpath="caches",
        sentinel_files=("modules-2/files-2.1",),
    ),
    CacheSpec(kind=CacheKind.MAVEN, base=_HOME, relative=".m2/repository"),
    CacheSpec(
        kind=CacheKind.GO_MOD,
        base=_HOME,
        relative="go/pkg/mod",
        env_var="GOMODCACHE",
        fallback_var="GOPATH",
        fallback_subpath="pkg/mod",
        command=("go", "clean", "-modcache"),
        sentinel_files=("cache/download",),
    ),
    CacheSpec(
        kind=CacheKind.GO_BUILD,
        base=_XDG,
        relative="go-build",
        env_var="GOCACHE",
        command=("go", "clean", "-cache"),
    ),
    CacheSpec(
        kind=CacheKind.YARN,
        base=_XDG,
        relative="yarn",
        env_var="YARN_CACHE_FOLDER",
        command=("yarn", "cache", "clean"),
        sentinel_entries=("v6", ".tmp"),
    ),
    CacheSpec(
        kind=CacheKind.PNPM,
        base=_HOME,
        relative=".local/share/pnpm/store",
        command=("pnpm", "store", "prune"),
        sentinel_files=("v3/files", "v10/files"),
    ),
    CacheSpec(
        kind=CacheKind.BUN,
        base=_HOME,
        relative=".bun/install/cache",
        env_var="BUN_INSTALL_CACHE_DIR",
    ),
    CacheSpec(
        kind=CacheKind.CONDA,
        base=_HOME,
        relative=".conda/pkgs",
        env_var="CONDA_PKGS_DIRS",
        list_separator=",",
        command=("conda", "clean", "--all", "--yes"),
        sentinel_files=("urls.txt",),
    ),
    CacheSpec(
        kind=CacheKind.PLAYWRIGHT,
        base=_XDG,
        relative="ms-playwright",
        env_var="PLAYWRIGHT_BROWSERS_PATH",
        sentinel_files=(".links",),
    ),
    CacheSpec(kind=CacheKind.JETBRAINS, base=_XDG, relative="JetBrains"),
)
_SPECS_BY_KIND = {spec.kind: spec for spec in CACHE_SPECS}


def spec_for(*, kind: CacheKind) -> CacheSpec:
    """The catalog entry of a cache type."""
    return _SPECS_BY_KIND[kind]
