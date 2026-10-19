"""A HuggingFace hub cache in a tmpdir and the CACHE_ITEM_REMOVE plans aimed at it."""

import os
from dataclasses import dataclass
from pathlib import Path

from tests.service.executor_fakes import make_plan
from tests.service.fs_fakes import FsRig, build_rig
from wimm.model.actions import ItemFingerprint, Plan, PlanStep
from wimm.model.cache_items import ItemBlob
from wimm.model.enums import ActionKind, Risk

REMOVE = ActionKind.CACHE_ITEM_REMOVE
MODEL = "models--org--alpha"
OTHER = "models--org--beta"
EXCLUSIVE_BLOB = "blobs/ab/excl"
SHARED_BLOB = "blobs/ab/shared"
BLOB_BYTES = 4096


@dataclass(slots=True)
class HfCache:
    """Two models: `alpha` owns one store blob and shares another with `beta`."""

    rig: FsRig
    hub: Path

    @property
    def model(self) -> Path:
        return self.hub / MODEL

    def lock_file(self) -> Path:
        return self.hub / ".locks" / MODEL / "lock"


def _write(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def _link_model(*, hub: Path, name: str, blob: str) -> None:
    (hub / name / "refs").mkdir(parents=True)
    (hub / name / "refs" / "main").write_text("rev", encoding="utf-8")
    snapshot = hub / name / "snapshots" / "rev"
    snapshot.mkdir(parents=True)
    (snapshot / "weights").symlink_to(os.path.relpath(hub / blob, snapshot))


def build_hf_cache(*, home: Path) -> HfCache:
    hub = home / ".cache" / "huggingface" / "hub"
    (hub / ".locks" / MODEL).mkdir(parents=True)
    _write(hub / EXCLUSIVE_BLOB, BLOB_BYTES)
    _write(hub / SHARED_BLOB, BLOB_BYTES)
    _link_model(hub=hub, name=MODEL, blob=EXCLUSIVE_BLOB)
    (hub / MODEL / "snapshots" / "rev" / "shared").symlink_to(
        os.path.relpath(hub / SHARED_BLOB, hub / MODEL / "snapshots" / "rev")
    )
    _link_model(hub=hub, name=OTHER, blob=SHARED_BLOB)
    _write(hub / ".locks" / MODEL / "lock", 0)
    return HfCache(rig=build_rig(home=home), hub=hub)


def blob_of(*, hub: Path, relative: str) -> ItemBlob:
    info = os.lstat(hub / relative)
    return ItemBlob(
        path=relative, size=info.st_blocks * 512, st_ino=info.st_ino, st_dev=info.st_dev
    )


def item_fingerprint(
    *, folder: Path, blobs: tuple[ItemBlob, ...] = (), realpath: str | None = None
) -> ItemFingerprint:
    info = os.lstat(folder)
    return ItemFingerprint(
        realpath=realpath or str(folder), st_ino=info.st_ino, st_dev=info.st_dev, blobs=blobs
    )


def item_plan(*, fingerprint: ItemFingerprint) -> Plan:
    step = PlanStep(
        order=1,
        kind=REMOVE,
        target_label=fingerprint.realpath,
        fingerprint=fingerprint,
        risk=Risk.SAFE,
    )
    return make_plan(steps=[step])


def planned(*, cache: HfCache) -> Plan:
    """The plan the collector would have made: the folder and its one exclusive blob."""
    blob = blob_of(hub=cache.hub, relative=EXCLUSIVE_BLOB)
    return item_plan(fingerprint=item_fingerprint(folder=cache.model, blobs=(blob,)))
