import stat
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from wimm.core.constants import SYSTEM_PATH_PREFIXES
from wimm.core.root_policy import DirFacts, RootFacts, RootRefusal, root_refusal

HOME = Path("/home/u")
UID = 1000
GID = 1000
ROOT_DIR = DirFacts(uid=0, gid=0, mode=stat.S_IFDIR | 0o755)


def make_facts(
    path: str, *, ancestors: tuple[DirFacts, ...] | None = None, **over: Any
) -> RootFacts:
    """Facts for a directory of the user whose ancestors are all plain root 755 directories."""
    real = Path(path)
    chain = ancestors if ancestors is not None else (ROOT_DIR,) * (len(real.parts) - 1)
    base = RootFacts(
        realpath=real,
        is_symlink=False,
        st_uid=UID,
        st_gid=GID,
        own_uid=UID,
        own_gid=GID,
        mode=stat.S_IFDIR | 0o755,
        ancestors=chain,
        fstype="ext4",
        read_only=False,
    )
    return replace(base, **over)


def refusal(path: str, **over: Any) -> RootRefusal | None:
    return root_refusal(facts=make_facts(path, **over), home=HOME)


def test_external_root_owned_by_user_under_root_parent_is_allowed() -> None:
    assert refusal("/mnt/data/code") is None


def test_home_itself_is_allowed() -> None:
    home_chain = (ROOT_DIR, ROOT_DIR)
    assert refusal("/home/u", ancestors=home_chain) is None


def test_below_home_is_allowed() -> None:
    chain = (ROOT_DIR, ROOT_DIR, DirFacts(uid=UID, gid=GID, mode=stat.S_IFDIR | 0o700))
    assert refusal("/home/u/code", ancestors=chain) is None


def test_symlink_is_refused_even_when_everything_else_is_fine() -> None:
    assert refusal("/mnt/data/code", is_symlink=True) is RootRefusal.SYMLINK


def test_symlink_wins_over_shallow() -> None:
    assert refusal("/data", is_symlink=True) is RootRefusal.SYMLINK


def test_two_components_are_too_shallow() -> None:
    assert refusal("/mnt/data") is RootRefusal.TOO_SHALLOW
    assert refusal("/data") is RootRefusal.TOO_SHALLOW


def test_three_components_are_not_too_shallow() -> None:
    assert refusal("/mnt/data/code") is None


@pytest.mark.parametrize("prefix", SYSTEM_PATH_PREFIXES)
def test_every_system_prefix_descendant_is_refused(prefix: str) -> None:
    assert refusal(f"{prefix}/a/b") is RootRefusal.SYSTEM_PATH


@pytest.mark.parametrize("path", ["/var/www/proj", "/opt/app/x", "/srv/data/x"])
def test_system_prefix_descendants_are_refused(path: str) -> None:
    assert refusal(path) is RootRefusal.SYSTEM_PATH


def test_similar_name_to_system_prefix_is_not_system() -> None:
    assert refusal("/usr2/data/code") is None


def test_home_parent_is_refused_as_home_ancestor() -> None:
    assert refusal("/home") is RootRefusal.HOME_ANCESTOR


def test_other_user_home_is_refused_even_if_owned() -> None:
    assert refusal("/home/bob/x") is RootRefusal.OTHER_HOME


def test_sibling_of_home_is_other_home() -> None:
    assert refusal("/home/bob/x/y") is RootRefusal.OTHER_HOME


def test_root_owned_by_someone_else_is_refused() -> None:
    assert refusal("/mnt/data/code", st_uid=1001) is RootRefusal.NOT_OWNED


def test_root_owned_by_root_is_refused() -> None:
    assert refusal("/mnt/data/code", st_uid=0) is RootRefusal.NOT_OWNED


def test_sticky_world_writable_parent_is_allowed() -> None:
    shared = DirFacts(uid=0, gid=0, mode=stat.S_IFDIR | 0o1777)
    chain = (ROOT_DIR, ROOT_DIR, shared)
    assert refusal("/mnt/shared/code", ancestors=chain) is None


def test_world_writable_parent_without_sticky_is_refused() -> None:
    shared = DirFacts(uid=0, gid=0, mode=stat.S_IFDIR | 0o777)
    chain = (ROOT_DIR, ROOT_DIR, shared)
    assert refusal("/mnt/shared/code", ancestors=chain) is RootRefusal.UNSAFE_PARENT


def test_parent_owned_by_another_user_is_refused() -> None:
    other = DirFacts(uid=1001, gid=1001, mode=stat.S_IFDIR | 0o755)
    assert refusal("/mnt/data/code", ancestors=(ROOT_DIR, ROOT_DIR, other)) is (
        RootRefusal.UNSAFE_PARENT
    )


def test_parent_owned_by_the_user_is_allowed() -> None:
    mine = DirFacts(uid=UID, gid=GID, mode=stat.S_IFDIR | 0o755)
    assert refusal("/mnt/data/code", ancestors=(ROOT_DIR, ROOT_DIR, mine)) is None


def test_group_writable_parent_with_own_gid_is_allowed() -> None:
    group = DirFacts(uid=0, gid=GID, mode=stat.S_IFDIR | 0o775)
    assert refusal("/mnt/data/code", ancestors=(ROOT_DIR, ROOT_DIR, group)) is None


def test_group_writable_parent_of_root_group_is_allowed() -> None:
    group = DirFacts(uid=0, gid=0, mode=stat.S_IFDIR | 0o775)
    assert refusal("/mnt/data/code", ancestors=(ROOT_DIR, ROOT_DIR, group)) is None


def test_group_writable_parent_with_foreign_gid_is_refused() -> None:
    group = DirFacts(uid=0, gid=50, mode=stat.S_IFDIR | 0o775)
    assert refusal("/mnt/data/code", ancestors=(ROOT_DIR, ROOT_DIR, group)) is (
        RootRefusal.UNSAFE_PARENT
    )


def test_group_writable_foreign_parent_with_sticky_is_allowed() -> None:
    group = DirFacts(uid=0, gid=50, mode=stat.S_IFDIR | 0o1775)
    assert refusal("/mnt/data/code", ancestors=(ROOT_DIR, ROOT_DIR, group)) is None


def test_root_itself_world_writable_without_sticky_is_refused() -> None:
    assert refusal("/mnt/data/code", mode=stat.S_IFDIR | 0o777) is RootRefusal.UNSAFE_PARENT


def test_root_itself_group_writable_with_own_gid_is_allowed() -> None:
    assert refusal("/mnt/data/code", mode=stat.S_IFDIR | 0o775) is None


def test_root_itself_group_writable_with_foreign_gid_is_refused() -> None:
    facts = make_facts("/mnt/data/code", mode=stat.S_IFDIR | 0o775, st_gid=50)
    assert root_refusal(facts=facts, home=HOME) is RootRefusal.UNSAFE_PARENT


@pytest.mark.parametrize("fstype", ["nfs", "nfs4", "cifs", "autofs", "fuse", "fuse.sshfs"])
def test_remote_filesystems_are_refused(fstype: str) -> None:
    assert refusal("/mnt/data/code", fstype=fstype) is RootRefusal.REMOTE_FS


@pytest.mark.parametrize("fstype", ["ext4", "exfat", "vfat", "btrfs", "xfs"])
def test_local_filesystems_are_allowed(fstype: str) -> None:
    assert refusal("/mnt/data/code", fstype=fstype) is None


def test_read_only_mount_is_refused() -> None:
    assert refusal("/mnt/data/code", read_only=True) is RootRefusal.READ_ONLY


def test_remote_wins_over_read_only() -> None:
    assert refusal("/mnt/data/code", fstype="nfs", read_only=True) is RootRefusal.REMOTE_FS


def test_not_owned_wins_over_unsafe_parent() -> None:
    shared = DirFacts(uid=0, gid=0, mode=stat.S_IFDIR | 0o777)
    result = refusal("/mnt/shared/code", st_uid=1001, ancestors=(ROOT_DIR, ROOT_DIR, shared))
    assert result is RootRefusal.NOT_OWNED


def test_every_refusal_has_an_italian_message() -> None:
    from wimm.core.root_policy import ROOT_REFUSAL_MESSAGES

    assert set(ROOT_REFUSAL_MESSAGES) == set(RootRefusal)
    assert all(message for message in ROOT_REFUSAL_MESSAGES.values())


@pytest.mark.parametrize(
    "path", ["/bin/a/b", "/sbin/a/b", "/lib/x/y", "/lib64/x/y", "/lost+found/a/b"]
)
def test_root_policy_refuses_the_merged_usr_links_and_lost_found(path: str) -> None:
    assert refusal(path) is RootRefusal.SYSTEM_PATH


def test_root_policy_refuses_fuseblk_like_any_fuse_mount() -> None:
    # ntfs-3g and exfat through FUSE: owner and mode are declared by the daemon, not the disk.
    assert refusal("/mnt/data/code", fstype="fuseblk") is RootRefusal.REMOTE_FS
