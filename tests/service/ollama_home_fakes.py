"""A home ollama store in a tmpdir and a fake client that removes its manifest (T-6.38c)."""

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from tests.collectors.ollama_models_helpers import CURRENT_UID, FakeProcess, FakeReader
from tests.service.executor_fakes import make_plan
from tests.service.fs_fakes import FsRig
from tests.service.ollama_item_fakes import FakeOllama, ollama_rig
from wimm.collectors.ollama_command import CommandOutput
from wimm.model.actions import ItemFingerprint, Plan, PlanStep
from wimm.model.enums import ActionKind, Risk

MANIFEST_RELATIVE = "manifests/registry.ollama.ai/library/gemma3/4b"
CONFIG_HEX = "a" * 64
LAYER_HEX = "b" * 64
BLOB_BYTES = 8192


def home_server() -> FakeReader:
    """S1: one server of the current user, `OLLAMA_MODELS` not set (the default store)."""
    return FakeReader(FakeProcess(uid=CURRENT_UID))


def write_manifest(*, store: Path, relative: str = MANIFEST_RELATIVE) -> Path:
    """A manifest naming a config blob and a layer blob that only it uses."""
    manifest = store / relative
    manifest.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "config": {"digest": f"sha256:{CONFIG_HEX}"},
        "layers": [{"digest": f"sha256:{LAYER_HEX}"}],
    }
    manifest.write_text(json.dumps(document), encoding="utf-8")
    (store / "blobs").mkdir(exist_ok=True)
    for digest in (CONFIG_HEX, LAYER_HEX):
        (store / "blobs" / f"sha256-{digest}").write_bytes(b"x" * BLOB_BYTES)
    return manifest


def blobs_disk_bytes(*, store: Path) -> int:
    """What the two blobs take on disk, measured as the listing does."""
    blobs = store / "blobs"
    return sum(os.lstat(blob).st_blocks * 512 for blob in blobs.iterdir())


@dataclass
class ManifestOllama(FakeOllama):
    """The server that answers `rm` by dropping the manifest file, or not."""

    manifest: Path | None = None

    def _rm(self, *, argv: Sequence[str]) -> CommandOutput:
        if self.manifest is not None and self.rm_removes and not self.rm_returncode:
            self.manifest.unlink()
        return super()._rm(argv=argv)


def item_step(*, manifest: Path, ino_shift: int = 0, dev_shift: int = 0) -> PlanStep:
    info = os.lstat(manifest)
    return PlanStep(
        order=1,
        kind=ActionKind.CACHE_ITEM_REMOVE,
        target_label="gemma3:4b",
        fingerprint=ItemFingerprint(
            realpath=str(manifest),
            st_ino=info.st_ino + ino_shift,
            st_dev=info.st_dev + dev_shift,
        ),
        risk=Risk.DANGER,
    )


def item_plan(*, manifest: Path) -> Plan:
    return make_plan(steps=[item_step(manifest=manifest)])


def home_rig(
    *, home: Path, ollama: FakeOllama, reader: FakeReader | None = None
) -> tuple[FsRig, Path]:
    """The rig over a home that holds one model; the table sees the store because it exists."""
    manifest = write_manifest(store=home / ".ollama/models")
    if isinstance(ollama, ManifestOllama):
        ollama.manifest = manifest
    rig = ollama_rig(home=home, ollama=ollama, reader=reader or home_server())
    return rig, manifest
