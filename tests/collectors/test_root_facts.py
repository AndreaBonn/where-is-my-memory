import os
import stat
from collections.abc import Callable
from pathlib import Path

from wimm.collectors.root_facts import read_root_facts

OWN_UID = os.getuid()
OTHER_UID = OWN_UID + 1
ROOT_MOUNT = "25 1 8:1 / / rw,relatime shared:1 - ext4 /dev/sda1 rw\n"


def mount_line(*, point: str, fstype: str, options: str = "rw") -> str:
    return f"90 25 0:50 / {point} {options} - {fstype} src rw\n"


def mounts(text: str) -> Callable[[], str]:
    return lambda: text


def as_owned_by(*, owners: dict[Path, int]) -> Callable[[Path], os.stat_result]:
    """An lstat that reports another owner for the listed paths and the real data otherwise."""

    def read(path: Path) -> os.stat_result:
        real = os.lstat(path)
        if path not in owners:
            return real
        fields = list(real)
        fields[4] = owners[path]
        return os.stat_result(fields)

    return read


def test_read_root_facts_reports_a_plain_directory(tmp_path: Path) -> None:
    root = tmp_path / "code"
    root.mkdir()
    facts = read_root_facts(path=root, read_mounts=mounts(ROOT_MOUNT))
    assert facts is not None
    assert facts.realpath == root.resolve()
    assert facts.is_symlink is False
    assert (facts.st_uid, facts.own_uid) == (OWN_UID, OWN_UID)
    assert stat.S_ISDIR(facts.mode)
    assert (facts.fstype, facts.read_only) == ("ext4", False)


def test_read_root_facts_lists_the_ancestors_from_slash_to_the_parent(tmp_path: Path) -> None:
    root = tmp_path / "a" / "b"
    root.mkdir(parents=True)
    facts = read_root_facts(path=root, read_mounts=mounts(ROOT_MOUNT))
    assert facts is not None
    real = root.resolve()
    assert len(facts.ancestors) == len(real.parts) - 1
    assert facts.ancestors[0].uid == os.lstat("/").st_uid
    assert facts.ancestors[-1].mode == os.lstat(real.parent).st_mode
    assert facts.ancestors[-1].uid == OWN_UID


def test_read_root_facts_flags_a_symlink_and_judges_its_target(tmp_path: Path) -> None:
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    facts = read_root_facts(path=link, read_mounts=mounts(ROOT_MOUNT))
    assert facts is not None
    assert facts.is_symlink is True
    assert facts.realpath == target.resolve()


def test_read_root_facts_returns_none_for_a_missing_path(tmp_path: Path) -> None:
    assert read_root_facts(path=tmp_path / "gone", read_mounts=mounts(ROOT_MOUNT)) is None


def test_read_root_facts_returns_none_when_a_stat_is_denied(tmp_path: Path) -> None:
    def denied(path: Path) -> os.stat_result:
        raise PermissionError(path)

    facts = read_root_facts(path=tmp_path, read_stat=denied, read_mounts=mounts(ROOT_MOUNT))
    assert facts is None


def test_read_root_facts_uses_the_longest_mount_containing_the_root(tmp_path: Path) -> None:
    root = (tmp_path / "code").resolve()
    root.mkdir()
    text = (
        ROOT_MOUNT
        + mount_line(point=str(tmp_path.resolve()), fstype="nfs4", options="rw,noatime")
        + mount_line(point=str(root), fstype="ext4", options="ro,nosuid")
        + mount_line(point=str(root) + "2", fstype="cifs")
    )
    facts = read_root_facts(path=root, read_mounts=mounts(text))
    assert facts is not None
    assert (facts.fstype, facts.read_only) == ("ext4", True)


def test_read_root_facts_reads_the_mount_when_the_root_is_below_it(tmp_path: Path) -> None:
    root = tmp_path / "code"
    root.mkdir()
    text = ROOT_MOUNT + mount_line(point=str(tmp_path.resolve()), fstype="fuse.sshfs")
    facts = read_root_facts(path=root, read_mounts=mounts(text))
    assert facts is not None
    assert facts.fstype == "fuse.sshfs"
    assert facts.read_only is False


def test_read_root_facts_returns_none_when_no_mount_contains_the_root(tmp_path: Path) -> None:
    assert read_root_facts(path=tmp_path, read_mounts=mounts("")) is None


def test_read_root_facts_reports_a_foreign_owner_of_the_root_and_of_an_ancestor(
    tmp_path: Path,
) -> None:
    root = tmp_path / "a" / "b"
    root.mkdir(parents=True)
    real = root.resolve()
    reader = as_owned_by(owners={real: OTHER_UID, real.parent: OTHER_UID})
    facts = read_root_facts(path=root, read_stat=reader, read_mounts=mounts(ROOT_MOUNT))
    assert facts is not None
    assert facts.st_uid == OTHER_UID
    assert facts.ancestors[-1].uid == OTHER_UID
    assert facts.ancestors[0].uid != OTHER_UID


def test_read_root_facts_sees_a_superblock_remounted_read_only(tmp_path: Path) -> None:
    root = (tmp_path / "code").resolve()
    root.mkdir()
    # errors=remount-ro after an I/O error flips the superblock, not the per-mount options.
    line = f"90 25 0:50 / {root} rw,noatime - ext4 /dev/sdb1 ro,errors=remount-ro\n"
    facts = read_root_facts(path=root, read_mounts=mounts(ROOT_MOUNT + line))
    assert facts is not None
    assert facts.read_only is True


def test_read_root_facts_takes_owner_group_and_mode_from_the_symlink_target(
    tmp_path: Path,
) -> None:
    target = (tmp_path / "real").resolve()
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    target_uid, target_gid, target_mode = OWN_UID + 7, OWN_UID + 8, stat.S_IFDIR | 0o750

    def read(path: Path) -> os.stat_result:
        fields = list(os.lstat(path))
        if path == target:
            fields[0], fields[4], fields[5] = target_mode, target_uid, target_gid
        elif path == link:
            fields[4], fields[5] = OWN_UID + 100, OWN_UID + 101
        return os.stat_result(fields)

    facts = read_root_facts(path=link, read_stat=read, read_mounts=mounts(ROOT_MOUNT))
    assert facts is not None
    assert facts.is_symlink is True
    assert (facts.st_uid, facts.st_gid, facts.mode) == (target_uid, target_gid, target_mode)


def test_read_root_facts_lets_the_last_mount_on_the_same_point_win(tmp_path: Path) -> None:
    root = (tmp_path / "code").resolve()
    root.mkdir()
    text = (
        ROOT_MOUNT
        + mount_line(point=str(root), fstype="nfs4", options="ro")
        + mount_line(point=str(root), fstype="ext4", options="rw")
    )
    facts = read_root_facts(path=root, read_mounts=mounts(text))
    assert facts is not None
    assert (facts.fstype, facts.read_only) == ("ext4", False)


def test_read_root_facts_ignores_malformed_mountinfo_lines(tmp_path: Path) -> None:
    root = (tmp_path / "code").resolve()
    root.mkdir()
    malformed = (
        "garbage line\n"
        f"90 25 0:50 / {root} rw nfs4\n"  # no " - " separator
        f"90 25 0:50 / {root} rw - \n"  # nothing after the separator: no filesystem type
        f"90 25 0:50 / {root} - nfs4 srv rw\n"  # too few fields before the separator
    )

    facts = read_root_facts(path=root, read_mounts=mounts(malformed + ROOT_MOUNT))
    assert facts is not None
    assert (facts.fstype, facts.read_only) == ("ext4", False)

    assert read_root_facts(path=root, read_mounts=mounts(malformed)) is None
