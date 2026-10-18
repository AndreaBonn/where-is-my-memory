import pytest

from wimm.core.cache_catalog import (
    COMMAND_ENV_ALLOWLIST,
    COMMAND_ONLY_KINDS,
    command_argv,
    command_env,
    withheld_kinds,
)
from wimm.core.cache_specs import CACHE_COMMANDS
from wimm.model.disk import CacheKind

FOLDER = "/home/u/.cache/thing"
ENVIRON = {
    "PATH": "/usr/bin",
    "HOME": "/home/u",
    "LANG": "it_IT.UTF-8",
    "GOFLAGS": "-mod=mod",
    "YARN_RC_FILENAME": ".evil",
    "LD_PRELOAD": "/opt/inject.so",
}


def _argv(*, kind: CacheKind, folder: str = FOLDER) -> tuple[str, ...]:
    return command_argv(command=CACHE_COMMANDS[kind], tool=f"/bin/{kind.value}", folder=folder)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (CacheKind.UV, ("/bin/uv", "cache", "prune", "--cache-dir", FOLDER)),
        (CacheKind.PIP, ("/bin/pip", "--cache-dir", FOLDER, "cache", "purge")),
        (CacheKind.NPM, ("/bin/npm", "cache", "clean", "--force", "--cache", "/home/u/.cache")),
        (CacheKind.GO_MOD, ("/bin/go_mod", "clean", "-modcache")),
        (CacheKind.GO_BUILD, ("/bin/go_build", "clean", "-cache")),
        (CacheKind.PNPM, ("/bin/pnpm", "store", "prune", "--store-dir", FOLDER)),
        (CacheKind.YARN, ("/bin/yarn", "cache", "clean")),
        (CacheKind.CONDA, ("/bin/conda", "clean", "--packages", "--tarballs", "--yes")),
    ],
)
def test_cache_argv_of_each_tool_starts_with_the_resolved_path(
    kind: CacheKind, expected: tuple[str, ...]
) -> None:
    assert _argv(kind=kind) == expected


def test_cache_argv_keeps_a_folder_with_braces_and_spaces_as_one_argument() -> None:
    folder = "/home/u/{parent} dir/uv"

    argv = _argv(kind=CacheKind.UV, folder=folder)

    assert argv[-1] == folder and len(argv) == 5


@pytest.mark.parametrize(
    ("kind", "variable"),
    [
        (CacheKind.GO_MOD, "GOMODCACHE"),
        (CacheKind.GO_BUILD, "GOCACHE"),
        (CacheKind.YARN, "YARN_CACHE_FOLDER"),
        (CacheKind.CONDA, "CONDA_PKGS_DIRS"),
    ],
)
def test_cache_env_is_the_allowlist_plus_the_one_variable_of_the_tool(
    kind: CacheKind, variable: str
) -> None:
    env = command_env(command=CACHE_COMMANDS[kind], folder=FOLDER, environ=ENVIRON)

    assert env == {"PATH": "/usr/bin", "HOME": "/home/u", "LANG": "it_IT.UTF-8", variable: FOLDER}


@pytest.mark.parametrize("kind", [CacheKind.UV, CacheKind.PIP, CacheKind.NPM, CacheKind.PNPM])
def test_cache_env_of_a_tool_aimed_by_an_option_is_only_the_allowlist(kind: CacheKind) -> None:
    env = command_env(command=CACHE_COMMANDS[kind], folder=FOLDER, environ=ENVIRON)

    assert set(env) == {"PATH", "HOME", "LANG"}


def test_cache_env_skips_an_allowlisted_variable_the_environment_does_not_have() -> None:
    env = command_env(command=CACHE_COMMANDS[CacheKind.UV], folder=FOLDER, environ={"PATH": "/b"})

    assert env == {"PATH": "/b"}


def test_the_allowlist_is_path_home_and_lang() -> None:
    assert COMMAND_ENV_ALLOWLIST == ("PATH", "HOME", "LANG")


def test_the_go_module_cache_is_withheld_only_while_go_is_missing() -> None:
    assert {CacheKind.GO_MOD} == COMMAND_ONLY_KINDS
    assert withheld_kinds(which=lambda _name: None) == {CacheKind.GO_MOD}
    assert withheld_kinds(which=lambda name: f"/usr/bin/{name}") == frozenset()
