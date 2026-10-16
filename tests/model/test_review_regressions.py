import json
from dataclasses import replace
from pathlib import Path

import pytest

from tests.helpers import invalid_model_value
from wimm import model as m
from wimm.serialize import SnapshotFormatError, snapshot_from_json, snapshot_to_json

PROCESS = m.ProcessFingerprint(pid=1, create_time=1.0, uid=1000, cmdline_hash="hash")
CONTAINER = m.ContainerFingerprint(id="c", status="running")
COMPOSE = m.ComposeFingerprint(project="demo", container_ids=frozenset({"c"}))
IMAGE = m.ImageFingerprint(id="i")
VOLUME = m.VolumeFingerprint(name="v")
DIRECTORY = m.DirFingerprint(realpath="/cache", st_ino=1, st_dev=1)
STEP_FINGERPRINTS = [
    (m.ActionKind.PROCESS_TERMINATE, PROCESS),
    (m.ActionKind.PROCESS_KILL, PROCESS),
    (m.ActionKind.APP_CLOSE, PROCESS),
    (m.ActionKind.CONTAINER_STOP, CONTAINER),
    (m.ActionKind.CONTAINER_REMOVE, CONTAINER),
    (m.ActionKind.COMPOSE_DOWN, COMPOSE),
    (m.ActionKind.COMPOSE_DOWN_VOLUMES, COMPOSE),
    (m.ActionKind.IMAGE_REMOVE, IMAGE),
    (m.ActionKind.VOLUME_REMOVE, VOLUME),
    (m.ActionKind.DEVDIR_DELETE, DIRECTORY),
    (m.ActionKind.CACHE_CLEAN, DIRECTORY),
    (m.ActionKind.TRASH_EMPTY, DIRECTORY),
    (m.ActionKind.IMAGES_PRUNE_DANGLING, None),
    (m.ActionKind.IMAGES_PRUNE_UNUSED, None),
    (m.ActionKind.BUILDER_PRUNE, None),
    (m.ActionKind.CONTAINERS_PRUNE_STOPPED, None),
]
FIXTURE = Path(__file__).parents[1] / "fixtures" / "snapshot_whitebox.json"


@pytest.mark.parametrize("kind,fingerprint", STEP_FINGERPRINTS)
def test_step_requires_action_specific_fingerprint(
    kind: m.ActionKind, fingerprint: m.Fingerprint | None
) -> None:
    step = m.PlanStep(
        order=1,
        kind=kind,
        target_label="target",
        fingerprint=fingerprint,
        risk=m.Risk.SAFE,
    )
    assert step.fingerprint == fingerprint
    mismatch = IMAGE if fingerprint != IMAGE else PROCESS
    with pytest.raises(ValueError, match="fingerprint"):
        replace(step, fingerprint=mismatch)


@pytest.mark.parametrize("kind", [m.ActionKind.GROUP_STOP, m.ActionKind.STOP_ALL_IDLE_SAFE])
@pytest.mark.parametrize("fingerprint", [PROCESS, CONTAINER, COMPOSE, None])
def test_aggregate_requests_require_member_steps(
    kind: m.ActionKind, fingerprint: m.Fingerprint | None
) -> None:
    request = m.ActionRequest(
        kind=kind, group_id=m.GroupId("g") if kind is m.ActionKind.GROUP_STOP else None
    )
    assert request.kind is kind
    assert (
        m.PlanStep(
            order=1,
            kind=m.ActionKind.CONTAINER_STOP,
            target_label="c",
            fingerprint=CONTAINER,
            risk=m.Risk.SAFE,
        ).fingerprint
        == CONTAINER
    )
    with pytest.raises(ValueError, match="fingerprint"):
        m.PlanStep(
            order=1,
            kind=kind,
            target_label="g",
            fingerprint=fingerprint,
            risk=m.Risk.SAFE,
        )


@pytest.mark.parametrize("value", [-1, 1.5, True])
def test_process_fingerprint_rejects_invalid_pid(value: object) -> None:
    assert replace(PROCESS, pid=0).pid == 0
    with pytest.raises(ValueError, match="pid"):
        replace(PROCESS, pid=invalid_model_value(value))


@pytest.mark.parametrize("value", [-1, 65536, True, 1.5])
@pytest.mark.parametrize("field", ["ports", "listen_ports"])
def test_snapshot_models_and_decoder_validate_ports(field: str, value: object) -> None:
    snapshot = snapshot_from_json(text=FIXTURE.read_text())
    group = snapshot.groups[0]
    process = group.members[1]
    assert isinstance(process, m.ProcessMember)
    instance = group if field == "ports" else process
    assert getattr(replace(instance, **invalid_model_value({field: (0, 65535)})), field) == (
        0,
        65535,
    )
    with pytest.raises(ValueError, match=field):
        replace(instance, **invalid_model_value({field: (value,)}))
    data = json.loads(snapshot_to_json(snapshot=snapshot))
    target = data["groups"][0] if field == "ports" else data["groups"][0]["members"][1]
    target[field] = [value]
    with pytest.raises(SnapshotFormatError, match=field):
        snapshot_from_json(text=json.dumps(data))


@pytest.mark.parametrize("value", [-1, True, 1.5])
def test_snapshot_process_pid_validation(value: object) -> None:
    data = json.loads(FIXTURE.read_text())
    process = data["groups"][0]["members"][1]
    process["pid"] = 0
    decoded = snapshot_from_json(text=json.dumps(data)).groups[0].members[1]
    assert isinstance(decoded, m.ProcessMember)
    assert decoded.pid == 0
    process["pid"] = value
    with pytest.raises(SnapshotFormatError, match="pid"):
        snapshot_from_json(text=json.dumps(data))


def test_project_memory_is_attributed_to_member_categories() -> None:
    breakdown = m.MemoryBreakdown(
        categories=((m.Category.CONTAINER, 10),), kernel_cache=0, unattributed=0
    )
    assert breakdown.categories == ((m.Category.CONTAINER, 10),)
    with pytest.raises(ValueError, match="PROJECT"):
        replace(breakdown, categories=((m.Category.PROJECT, 10),))
    data = json.loads(FIXTURE.read_text())
    data["memory"]["breakdown"]["PROJECT"] = 10
    with pytest.raises(SnapshotFormatError, match="PROJECT"):
        snapshot_from_json(text=json.dumps(data))


@pytest.mark.parametrize("value", [None, 1, b"{}", {}, [], True, "[" * 10000 + "]" * 10000])
def test_decoder_normalizes_invalid_input_and_excessive_nesting(value: object) -> None:
    assert snapshot_from_json(text=FIXTURE.read_text()).groups[0].name == "whitebox"
    with pytest.raises(SnapshotFormatError):
        snapshot_from_json(text=invalid_model_value(value))
