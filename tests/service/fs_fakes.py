"""Fakes and builders for the folder, cache and trash executor tests (tmpdir only)."""

import os
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tests.service.executor_fakes import OWNER_UID, FakeProcesses, make_plan
from wimm.collectors.cache_table import read_cache_table
from wimm.model.actions import DirFingerprint, Plan, PlanStep
from wimm.model.enums import ActionKind, Risk
from wimm.service.errors import ControlFailed
from wimm.service.executor import PlanExecutor
from wimm.service.fs_controls import CommandResult, DiskFsControl

DAY_S = 86400
NOW = 1_800_000_000.0
OLD = NOW - 200 * DAY_S
MIN_AGE_DAYS = 90


@dataclass(slots=True)
class FakeRunner:
    """Records the argument lists; replies with `result`, or raises `error`."""

    result: CommandResult = field(default_factory=lambda: CommandResult(returncode=0, output=""))
    error: ControlFailed | None = None
    calls: list[tuple[str, ...]] = field(default_factory=list)
    timeouts: list[float] = field(default_factory=list)
    envs: list[Mapping[str, str] | None] = field(default_factory=list)

    def run(
        self, *, argv: Sequence[str], timeout_s: float, env: Mapping[str, str] | None = None
    ) -> CommandResult:
        self.calls.append(tuple(argv))
        self.envs.append(env)
        self.timeouts.append(timeout_s)
        if self.error is not None:
            raise self.error
        return self.result


@dataclass(slots=True)
class FakeCwds:
    paths: list[Path] = field(default_factory=list)

    def cwds(self) -> Sequence[Path]:
        return list(self.paths)


@dataclass(slots=True)
class FsRig:
    """A home in a tmpdir with a development root under it, and the control wired to it."""

    home: Path
    runner: FakeRunner
    cwds: FakeCwds
    control: DiskFsControl

    @property
    def root(self) -> Path:
        return self.home / "work"

    def executor(self) -> PlanExecutor:
        return PlanExecutor(
            processes=FakeProcesses(), containers=None, owner_uid=OWNER_UID, disk_fs=self.control
        )


def build_rig(
    *,
    home: Path,
    missing: Collection[str] = (),
    environ: Mapping[str, str] | None = None,
) -> FsRig:
    """The control with the cache table of ``home`` under ``environ`` (no variables by default).

    Every tool is on the fake PATH as ``/usr/bin/<name>`` except those in ``missing``.

    Create a redirected cache folder before calling this: the table reads the disk once.
    """
    runner, cwds = FakeRunner(), FakeCwds()
    (home / "work").mkdir(parents=True, exist_ok=True)
    control = DiskFsControl(
        home=home,
        caches=read_cache_table(environ=environ or {}, home=home, roots=(home / "work",)),
        roots=(home / "work",),
        min_age_days=MIN_AGE_DAYS,
        runner=runner,
        cwds=cwds,
        which=lambda name: None if name in missing else f"/usr/bin/{name}",
        mounts=lambda: frozenset(),
        clock=lambda: NOW,
    )
    return FsRig(home=home, runner=runner, cwds=cwds, control=control)


def age(*, path: Path, mtime: float) -> None:
    os.utime(path, (mtime, mtime), follow_symlinks=False)


def make_project(*, root: Path, name: str = "proj", folder: str = "node_modules") -> Path:
    """A project with an old `package.json` and `src/`, and a dependency folder of 3 files."""
    project = root / name
    (project / "src").mkdir(parents=True)
    (project / folder / "pkg" / "lib").mkdir(parents=True)
    for file in (project / "package.json", project / "src" / "app.js"):
        file.write_text("x", encoding="utf-8")
    for relative in ("index.js", "lib/util.js"):
        (project / folder / "pkg" / relative).write_text("y" * 8192, encoding="utf-8")
    (project / folder / "top.txt").write_text("z", encoding="utf-8")
    for path in (project, project / "src", project / "package.json", project / "src" / "app.js"):
        age(path=path, mtime=OLD)
    return project / folder


def fingerprint_of(*, path: Path) -> DirFingerprint:
    info = os.lstat(path)
    return DirFingerprint(realpath=str(path), st_ino=info.st_ino, st_dev=info.st_dev)


def dir_step(*, kind: ActionKind, fingerprint: DirFingerprint, order: int = 1) -> PlanStep:
    return PlanStep(
        order=order,
        kind=kind,
        target_label=fingerprint.realpath,
        fingerprint=fingerprint,
        risk=Risk.SAFE,
    )


def dir_plan(
    *, kind: ActionKind, path: Path | None = None, fingerprint: DirFingerprint | None = None
) -> Plan:
    fp = fingerprint if fingerprint is not None else fingerprint_of(path=path or Path("."))
    request_kind = kind if kind is ActionKind.TRASH_EMPTY else None
    return make_plan(steps=[dir_step(kind=kind, fingerprint=fp)], request_kind=request_kind)


def make_cache(*, home: Path, relative: str) -> Path:
    folder = home / relative
    (folder / "sub").mkdir(parents=True)
    (folder / "a.bin").write_bytes(b"a" * 4096)
    (folder / "sub" / "b.bin").write_bytes(b"b" * 4096)
    return folder


def make_trash(*, home: Path) -> Path:
    trash = home / ".local/share/Trash"
    (trash / "files" / "dir").mkdir(parents=True)
    (trash / "info").mkdir()
    (trash / "files" / "dir" / "x.txt").write_text("x" * 4096, encoding="utf-8")
    (trash / "files" / "y.txt").write_text("y", encoding="utf-8")
    (trash / "info" / "y.txt.trashinfo").write_text("[Trash Info]", encoding="utf-8")
    (trash / "directorysizes").write_text("1 2 3", encoding="utf-8")
    return trash
