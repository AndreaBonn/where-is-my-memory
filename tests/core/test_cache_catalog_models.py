"""R24, S5: HuggingFace, ollama and the Android folders resolve like any redirected cache."""

from pathlib import Path

import pytest

from wimm.core.cache_catalog import (
    CLEAN_SUBDIRS,
    CacheAccess,
    CacheObservations,
    CacheResolution,
    RejectReason,
    ResolvedCache,
    resolve_cache_paths,
)
from wimm.model.disk import CacheKind

HOME = Path("/home/u")
ROOTS = (Path("/home/u/projects"),)
HF, OLLAMA, AVD, SDK = "huggingface", "ollama", "android_avd", "android_sdk"
DEFAULTS = {
    HF: HOME / ".cache/huggingface/hub",
    OLLAMA: HOME / ".ollama/models",
    AVD: HOME / ".android/avd",
    SDK: HOME / "Android/Sdk",
}


def _resolve(
    *, environ: dict[str, str], observed: CacheObservations | None = None
) -> CacheResolution:
    return resolve_cache_paths(
        environ=environ, home=HOME, roots=ROOTS, observed=observed or CacheObservations()
    )


def _found(
    *, environ: dict[str, str], observed: CacheObservations | None = None
) -> dict[str, ResolvedCache]:
    result = _resolve(environ=environ, observed=observed)
    return {entry.kind.value: entry for entry in result.caches}


def _unlocked(*, path: Path, names: tuple[str, ...]) -> CacheObservations:
    return CacheObservations(real={path: path}, sentinels=frozenset(path / n for n in names))


def test_cache_kind_has_the_four_model_types() -> None:
    assert {HF, OLLAMA, AVD, SDK} <= {kind.value for kind in CacheKind}


@pytest.mark.parametrize("name", [HF, OLLAMA, AVD, SDK])
def test_the_default_folder_is_cleanable_without_variables(name: str) -> None:
    entry = _found(environ={})[name]

    assert entry.path == DEFAULTS[name]
    assert entry.redirected is False
    assert entry.access is CacheAccess.CLEANABLE


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({"HF_HUB_CACHE": "/home/u/hub", "HF_HOME": "/home/u/hfh"}, "/home/u/hub"),
        ({"HF_HOME": "/home/u/hfh", "XDG_CACHE_HOME": "/home/u/x/cache"}, "/home/u/hfh/hub"),
        ({"XDG_CACHE_HOME": "/home/u/x/cache"}, "/home/u/x/cache/huggingface/hub"),
    ],
)
def test_huggingface_precedence_hub_cache_then_hf_home_then_xdg(
    environ: dict[str, str], expected: str
) -> None:
    assert _found(environ=environ)[HF].path == Path(expected)


def test_huggingface_xdg_folder_named_cache_needs_no_sentinel() -> None:
    entry = _found(environ={"XDG_CACHE_HOME": "/home/u/x/cache"})[HF]

    assert entry.access is CacheAccess.CLEANABLE


def test_huggingface_xdg_folder_with_another_name_is_measure_only() -> None:
    entry = _found(environ={"XDG_CACHE_HOME": "/home/u/x/stuff"})[HF]

    assert entry.path == Path("/home/u/x/stuff/huggingface/hub")
    assert entry.access is CacheAccess.MEASURE_ONLY


def test_huggingface_redirect_is_cleanable_only_with_its_own_marker() -> None:
    path = Path("/home/u/hub")
    bare = _found(environ={"HF_HUB_CACHE": str(path)}, observed=_unlocked(path=path, names=()))
    marked = _found(
        environ={"HF_HUB_CACHE": str(path)}, observed=_unlocked(path=path, names=(".locks",))
    )

    assert bare[HF].access is CacheAccess.MEASURE_ONLY
    assert marked[HF].access is CacheAccess.CLEANABLE


def test_ollama_models_redirect_needs_the_ollama_registry_manifests() -> None:
    path = Path("/home/u/llm")
    environ = {"OLLAMA_MODELS": str(path)}

    # blobs and manifests alone are the generic OCI layout any user folder may have.
    generic = _found(environ=environ, observed=_unlocked(path=path, names=("blobs", "manifests")))[
        OLLAMA
    ]
    ollama = _found(
        environ=environ, observed=_unlocked(path=path, names=("manifests/registry.ollama.ai",))
    )[OLLAMA]

    assert generic.path == path and generic.access is CacheAccess.MEASURE_ONLY
    assert ollama.access is CacheAccess.CLEANABLE


def test_android_home_beats_sdk_root_and_sdk_root_works_alone() -> None:
    both = {"ANDROID_HOME": "/home/u/a", "ANDROID_SDK_ROOT": "/home/u/b"}

    assert _found(environ=both)[SDK].path == Path("/home/u/a")
    assert _found(environ={"ANDROID_SDK_ROOT": "/home/u/b"})[SDK].path == Path("/home/u/b")


def test_android_sdk_redirect_needs_a_file_only_an_sdk_has() -> None:
    path = Path("/home/u/proj")
    environ = {"ANDROID_SDK_ROOT": str(path)}

    # A Cordova or Ionic project also has platforms/ and build-tools/ folders.
    project = _found(
        environ=environ,
        observed=_unlocked(path=path, names=("platforms", "build-tools", "licenses")),
    )[SDK]
    license_ = _found(
        environ=environ, observed=_unlocked(path=path, names=("licenses/android-sdk-license",))
    )[SDK]
    adb = _found(environ=environ, observed=_unlocked(path=path, names=("platform-tools/adb",)))[SDK]

    assert project.access is CacheAccess.MEASURE_ONLY
    assert license_.access is CacheAccess.CLEANABLE
    assert adb.access is CacheAccess.CLEANABLE


@pytest.mark.parametrize(
    ("variable", "name", "value", "reason"),
    [
        ("HF_HUB_CACHE", HF, "/home/u", RejectReason.OUTSIDE_HOME),
        ("HF_HUB_CACHE", HF, "/home", RejectReason.OUTSIDE_HOME),
        ("HF_HOME", HF, "/etc", RejectReason.OUTSIDE_HOME),
        ("HF_HUB_CACHE", HF, "~", RejectReason.NOT_ABSOLUTE),
        ("HF_HUB_CACHE", HF, "/home/u/.cache", RejectReason.COVERS_OTHER_CACHES),
        ("HF_HUB_CACHE", HF, "/home/u/.cache/uv", RejectReason.COVERS_OTHER_CACHES),
        ("OLLAMA_MODELS", OLLAMA, "/usr/share/ollama/.ollama/models", RejectReason.OUTSIDE_HOME),
        ("OLLAMA_MODELS", OLLAMA, "/home/u", RejectReason.OUTSIDE_HOME),
        ("OLLAMA_MODELS", OLLAMA, "models", RejectReason.NOT_ABSOLUTE),
        ("OLLAMA_MODELS", OLLAMA, "/home/u/.config", RejectReason.COVERS_OTHER_CACHES),
        ("OLLAMA_MODELS", OLLAMA, "/home/u/projects/m", RejectReason.ROOT_CONFLICT),
        ("ANDROID_HOME", SDK, "/", RejectReason.OUTSIDE_HOME),
        ("ANDROID_HOME", SDK, "/home/u", RejectReason.OUTSIDE_HOME),
        ("ANDROID_SDK_ROOT", SDK, "/opt/android", RejectReason.OUTSIDE_HOME),
        ("ANDROID_HOME", SDK, "/home/u/.android", RejectReason.COVERS_OTHER_CACHES),
        ("ANDROID_HOME", SDK, "/home/u/.local/share", RejectReason.COVERS_OTHER_CACHES),
        ("ANDROID_HOME", SDK, "/home/u/projects", RejectReason.ROOT_CONFLICT),
    ],
)
def test_a_variable_on_home_system_or_other_caches_is_rejected(
    variable: str, name: str, value: str, reason: RejectReason
) -> None:
    result = _resolve(environ={variable: value})

    assert name not in {entry.kind.value for entry in result.caches}
    rejected = {r.kind.value: r for r in result.rejected}
    assert rejected[name].reason is reason


@pytest.mark.parametrize("name", [HF, OLLAMA, AVD, SDK])
def test_a_default_folder_that_is_a_symlink_is_only_measured(name: str) -> None:
    default = DEFAULTS[name]
    observed = CacheObservations(real={default: Path("/home/u/elsewhere") / name})

    entry = _found(environ={}, observed=observed)[name]

    assert entry.path == default
    assert entry.access is CacheAccess.MEASURE_ONLY


def test_ollama_cleans_only_blobs_and_manifests() -> None:
    assert CLEAN_SUBDIRS[CacheKind.OLLAMA] == ("blobs", "manifests")


def test_the_android_sdk_keeps_its_command_line_tools_and_licenses() -> None:
    subdirs = CLEAN_SUBDIRS[CacheKind.ANDROID_SDK]

    assert {"system-images", "platforms", "build-tools"} <= set(subdirs)
    assert not {"cmdline-tools", "licenses"} & set(subdirs)


def test_huggingface_and_avd_are_emptied_as_a_whole() -> None:
    assert CacheKind.HUGGINGFACE not in CLEAN_SUBDIRS
    assert CacheKind.ANDROID_AVD not in CLEAN_SUBDIRS
