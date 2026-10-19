from pathlib import Path

from wimm.collectors.cache_table import read_cache_table
from wimm.core.cache_catalog import CacheAccess, RejectReason, ResolvedCache
from wimm.core.item_tools import ITEM_ONLY_KINDS
from wimm.model.disk import CacheKind


def _by_kind(
    *, home: Path, environ: dict[str, str], roots: tuple[Path, ...] = ()
) -> dict[CacheKind, ResolvedCache]:
    table = read_cache_table(environ=environ, home=home, roots=roots)
    return {cache.kind: cache for cache in table.caches}


def test_read_cache_table_lists_every_kind_at_its_default_place(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)

    found = _by_kind(home=home, environ={})

    assert set(found) == set(CacheKind) - ITEM_ONLY_KINDS
    assert not ITEM_ONLY_KINDS & set(found)
    assert found[CacheKind.UV].path == home / ".cache" / "uv"
    assert found[CacheKind.MAVEN].path == home / ".m2" / "repository"
    assert all(cache.access is CacheAccess.CLEANABLE for cache in found.values())


def test_read_cache_table_honours_xdg_cache_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "xdg").mkdir(parents=True)

    found = _by_kind(home=home, environ={"XDG_CACHE_HOME": str(home / "xdg")})

    assert found[CacheKind.UV].path == home / "xdg" / "uv"


def test_a_redirected_cache_with_its_tag_is_cleanable_and_without_it_measure_only(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    tagged, plain = home / "t" / "uv", home / "p" / "pip"
    tagged.mkdir(parents=True)
    plain.mkdir(parents=True)
    (tagged / "CACHEDIR.TAG").write_text("Signature: 8a477f597d28d172789f06886806bc55\n")

    found = _by_kind(home=home, environ={"UV_CACHE_DIR": str(tagged), "PIP_CACHE_DIR": str(plain)})

    assert found[CacheKind.UV].access is CacheAccess.CLEANABLE
    assert found[CacheKind.PIP].access is CacheAccess.MEASURE_ONLY


def test_a_redirected_cache_on_a_missing_folder_is_measure_only(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)

    found = _by_kind(home=home, environ={"UV_CACHE_DIR": str(home / "gone")})

    assert found[CacheKind.UV].access is CacheAccess.MEASURE_ONLY


def test_a_default_cache_that_links_outside_the_home_is_rejected(tmp_path: Path) -> None:
    home = tmp_path / "home"
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (home / ".cache").mkdir(parents=True)
    (home / ".cache" / "uv").symlink_to(outside, target_is_directory=True)

    table = read_cache_table(environ={}, home=home, roots=())

    assert CacheKind.UV not in {cache.kind for cache in table.caches}
    assert [(r.kind, r.reason) for r in table.rejected] == [
        (CacheKind.UV, RejectReason.OUTSIDE_HOME)
    ]


def test_a_redirect_onto_a_project_root_is_rejected(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = home / "work" / "app"
    project.mkdir(parents=True)

    table = read_cache_table(
        environ={"UV_CACHE_DIR": str(project)}, home=home, roots=(home / "work",)
    )

    assert [(r.kind, r.reason) for r in table.rejected] == [
        (CacheKind.UV, RejectReason.ROOT_CONFLICT)
    ]


def test_a_default_cache_that_is_a_symlink_inside_the_home_is_never_cleanable(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    documents = home / "Documents"
    documents.mkdir(parents=True)
    (documents / "thesis.txt").write_text("mine", encoding="utf-8")
    (home / ".cache").mkdir()
    (home / ".cache" / "thumbnails").symlink_to(documents, target_is_directory=True)
    (home / ".cache" / "uv").mkdir()

    found = _by_kind(home=home, environ={})

    assert found[CacheKind.THUMBNAILS].access is not CacheAccess.CLEANABLE
    assert found[CacheKind.THUMBNAILS].path == home / ".cache" / "thumbnails"
    assert found[CacheKind.UV].access is CacheAccess.CLEANABLE


def test_a_cache_below_a_symlinked_folder_is_never_cleanable(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "Documents" / "pip").mkdir(parents=True)
    (home / ".cache").symlink_to(home / "Documents", target_is_directory=True)

    found = _by_kind(home=home, environ={})

    assert found[CacheKind.PIP].access is not CacheAccess.CLEANABLE
    # Positive pair: a cache that does not sit below the symlink stays cleanable.
    assert found[CacheKind.MAVEN].access is CacheAccess.CLEANABLE


def test_xdg_cache_home_on_a_plain_folder_still_needs_the_sentinel(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "Documents" / "thumbnails").mkdir(parents=True)
    (home / "Documents" / "thumbnails" / "report.pdf").write_bytes(b"x")
    (home / ".local" / "cache" / "uv").mkdir(parents=True)

    plain = _by_kind(home=home, environ={"XDG_CACHE_HOME": str(home / "Documents")})
    cache_like = _by_kind(home=home, environ={"XDG_CACHE_HOME": str(home / ".local" / "cache")})

    assert plain[CacheKind.THUMBNAILS].access is CacheAccess.MEASURE_ONLY
    assert cache_like[CacheKind.UV].access is CacheAccess.CLEANABLE


def test_xdg_cache_home_that_only_contains_cache_in_its_name_stays_measure_only(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    (home / "Documents" / "cachet-notes" / "uv").mkdir(parents=True)

    table = _by_kind(
        home=home, environ={"XDG_CACHE_HOME": str(home / "Documents" / "cachet-notes")}
    )

    assert table[CacheKind.UV].access is CacheAccess.MEASURE_ONLY
