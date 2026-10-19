from pathlib import Path

MOUNTINFO = (
    "36 35 98:0 /mnt1 /mnt2 rw,noatime master:1 - ext3 /dev/root rw,errors=continue\n"
    "40 36 8:1 / /home/u/with\\040space rw - ext4 /dev/sda1 rw\n"
    "garbage\n"
)


def tree(*, base: Path) -> Path:
    (base / "a" / "b").mkdir(parents=True)
    (base / "a" / "b" / "deep.txt").write_text("d" * 4096, encoding="utf-8")
    (base / "top.txt").write_text("t", encoding="utf-8")
    return base


def _trash_like(*, base: Path) -> Path:
    for name in ("files", "info"):
        (base / name).mkdir(parents=True)
        (base / name / "x.txt").write_text("x" * 4096, encoding="utf-8")
    return base
