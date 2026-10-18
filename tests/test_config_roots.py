import stat
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from wimm.config_roots import (
    admitted_roots,
    decode_roots,
    default_roots,
    expand_root,
    missing_roots,
    refused_roots,
    validate_roots,
)
from wimm.core.root_policy import DirFacts, RootFacts, RootRefusal

HOME = Path("/home/u")
UID = 1000
PLAIN_DIR = stat.S_IFDIR | 0o755
EXTERNAL = Path("/mnt/data/code")
ROOT_DIR = DirFacts(uid=0, gid=0, mode=PLAIN_DIR)
SAFE_FACTS = RootFacts(
    realpath=EXTERNAL,
    is_symlink=False,
    st_uid=UID,
    st_gid=UID,
    own_uid=UID,
    own_gid=UID,
    mode=PLAIN_DIR,
    ancestors=(ROOT_DIR,) * 3,
    fstype="ext4",
    read_only=False,
)


def test_expand_root_handles_tilde_and_absolute(tmp_path: Path) -> None:
    assert expand_root(value="~", home=tmp_path) == tmp_path.resolve()
    assert expand_root(value="~/a", home=tmp_path) == (tmp_path / "a").resolve()
    assert expand_root(value=str(tmp_path / "b"), home=tmp_path) == (tmp_path / "b").resolve()


@pytest.mark.parametrize("value", ["", "relative/dir"])
def test_expand_root_rejects_empty_and_relative(tmp_path: Path, value: str) -> None:
    with pytest.raises(ValueError, match="Expected an absolute directory path"):
        expand_root(value=value, home=tmp_path)


def test_default_roots_come_from_detection(tmp_path: Path) -> None:
    (tmp_path / "code" / "app" / ".git").mkdir(parents=True)
    (tmp_path / "Documents" / "photos").mkdir(parents=True)
    assert default_roots(home=tmp_path) == ((tmp_path / "code").resolve(),)


def test_default_roots_are_empty_when_nothing_is_detected(tmp_path: Path) -> None:
    assert default_roots(home=tmp_path) == ()


def test_decode_roots_accepts_existing_dir_within_home(tmp_path: Path) -> None:
    (tmp_path / "code").mkdir()
    assert decode_roots(value=["~/code"], home=tmp_path) == ((tmp_path / "code").resolve(),)


def test_decode_roots_rejects_an_empty_list(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Expected at least one directory"):
        decode_roots(value=[], home=tmp_path)


def test_decode_roots_keeps_a_root_outside_home_for_the_policy_to_judge(tmp_path: Path) -> None:
    home = tmp_path / "fakehome"
    home.mkdir()
    (tmp_path / "code").mkdir()
    decoded = decode_roots(value=["~", str(tmp_path / "code"), "/"], home=home)
    assert decoded == (home.resolve(), (tmp_path / "code").resolve(), Path("/"))


@pytest.mark.parametrize("roots", [[Path("/a")], [], (Path("rel"),), ("/a",)])
def test_validate_roots_rejects_non_tuple_relative_or_str(roots: object) -> None:
    with pytest.raises(ValueError, match="devdirs_roots must be a tuple of absolute paths"):
        validate_roots(roots=roots)


def test_validate_roots_accepts_tuple_of_absolute_paths() -> None:
    validate_roots(roots=(Path("/a"),))


def test_validate_roots_accepts_the_empty_tuple_of_an_empty_detection() -> None:
    validate_roots(roots=())


def test_decode_roots_keeps_a_missing_root_within_home(tmp_path: Path) -> None:
    (tmp_path / "code").mkdir()
    decoded = decode_roots(value=["~/gone", "~/code"], home=tmp_path)
    assert decoded == ((tmp_path / "gone").resolve(), (tmp_path / "code").resolve())


def test_decode_roots_rejects_a_root_that_is_a_file(tmp_path: Path) -> None:
    (tmp_path / "file").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="Expected existing directories or paths not yet created"):
        decode_roots(value=["~/file"], home=tmp_path)


def test_missing_roots_lists_only_roots_that_are_not_directories(tmp_path: Path) -> None:
    (tmp_path / "code").mkdir()
    roots = (tmp_path / "gone", tmp_path / "code")
    assert missing_roots(roots=roots) == (tmp_path / "gone",)
    assert missing_roots(roots=(tmp_path / "code",)) == ()


def test_root_outside_home_is_accepted_when_owned_and_safe() -> None:
    refused = refused_roots(roots=(EXTERNAL,), home=HOME, read_facts=lambda *, path: SAFE_FACTS)
    assert refused == ()


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"st_uid": UID + 1}, RootRefusal.NOT_OWNED),
        (
            {"ancestors": (ROOT_DIR, DirFacts(uid=0, gid=0, mode=stat.S_IFDIR | 0o777), ROOT_DIR)},
            RootRefusal.UNSAFE_PARENT,
        ),
        ({"fstype": "nfs4"}, RootRefusal.REMOTE_FS),
    ],
)
def test_root_outside_home_is_refused_with_its_reason(
    changes: dict[str, Any], reason: RootRefusal
) -> None:
    facts = replace(SAFE_FACTS, **changes)
    refused = refused_roots(roots=(EXTERNAL,), home=HOME, read_facts=lambda *, path: facts)
    assert refused == ((EXTERNAL, reason),)


def test_refused_roots_keep_the_order_and_skip_the_accepted_and_the_unreadable() -> None:
    foreign = replace(SAFE_FACTS, st_uid=UID + 1)
    by_path = {Path("/mnt/a/x"): SAFE_FACTS, Path("/mnt/b/y"): foreign, Path("/mnt/c/z"): None}
    refused = refused_roots(
        roots=tuple(by_path), home=HOME, read_facts=lambda *, path: by_path[path]
    )
    assert refused == ((Path("/mnt/b/y"), RootRefusal.NOT_OWNED),)


def test_the_home_itself_is_still_a_valid_root(tmp_path: Path) -> None:
    roots = decode_roots(value=["~"], home=tmp_path)
    assert refused_roots(roots=roots, home=tmp_path.resolve()) == ()


def test_a_system_directory_on_disk_is_refused_by_the_real_reader(tmp_path: Path) -> None:
    refused = refused_roots(roots=(Path("/usr/share/fonts"),), home=tmp_path)
    assert refused == ((Path("/usr/share/fonts"), RootRefusal.SYSTEM_PATH),)


def test_admitted_roots_need_readable_facts_and_no_refusal() -> None:
    unreadable, refused = Path("/mnt/nfs/code"), Path("/mnt/data/other")
    facts = {
        EXTERNAL: SAFE_FACTS,
        refused: replace(SAFE_FACTS, realpath=refused, st_uid=SAFE_FACTS.own_uid + 1),
    }

    # Unreadable facts (no mountinfo, a denied stat) must not pass as an admitted root.
    admitted = admitted_roots(
        roots=(EXTERNAL, unreadable, refused),
        home=HOME,
        read_facts=lambda *, path: facts.get(path),
    )

    assert admitted == (EXTERNAL,)
