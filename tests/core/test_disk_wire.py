import json
from typing import Any, cast

import pytest

from wimm.core.disk_rules import build_disk_report, parse_docker_df
from wimm.core.disk_wire import disk_report_from_json, disk_report_to_json
from wimm.model.disk import CacheKind, DiskReport
from wimm.wire_decoders import SnapshotFormatError

from .disk_helpers import FIXTURES, MB, SCANNED_AT, cache, load_df, report

SAMPLE = FIXTURES / "disk_report_sample.json"


@pytest.fixture
def document() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(SAMPLE.read_text(encoding="utf-8")))


def test_sample_decodes_to_the_model_and_reencodes_to_the_same_json(
    document: dict[str, Any],
) -> None:
    decoded = disk_report_from_json(text=SAMPLE.read_text(encoding="utf-8"))

    assert decoded.docker.images[1].dangling is True
    assert decoded.docker.images[1].unique_size == 120_000_000
    assert decoded.docker.build_cache_reclaimable == 70_000_000
    assert decoded.docker.volumes[1].size is None
    assert decoded.caches[1].kind is CacheKind.TRASH
    assert decoded.devdirs_truncated == 3
    assert json.loads(disk_report_to_json(report=decoded)) == document


def test_report_built_from_docker_df_survives_a_roundtrip() -> None:
    built = build_disk_report(
        scanned_at=SCANNED_AT, docker=parse_docker_df(df=load_df()), caches=(), devdirs=()
    )

    assert disk_report_from_json(text=disk_report_to_json(report=built)) == built


def _mutated(document: dict[str, Any], path: tuple[str | int, ...], value: object) -> str:
    node: Any = document
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return json.dumps(document)


@pytest.mark.parametrize(
    "path,value,message",
    [
        (("surprise",), 1, "surprise"),
        (("docker", "images", 0, "extra"), 1, "extra"),
        (("schema",), 4, "schema"),
        (("docker", "images", 0, "unique_size"), 450_000_001, "unique_size"),
        (("docker", "build_cache_reclaimable"), 100_000_001, "build_cache_reclaimable"),
        (("caches", 0, "kind"), "docs", "CacheKind"),
        (("devdirs", 0, "size"), -1, "size"),
        (("devdirs", 0, "age_days"), True, "age_days"),
        (("scanned_at",), "2026-10-16T10:12:00", "scanned_at"),
        (("docker", "volumes", 0, "ref_count"), "0", "ref_count"),
    ],
)
def test_invalid_documents_are_rejected(
    document: dict[str, Any], path: tuple[str | int, ...], value: object, message: str
) -> None:
    with pytest.raises(SnapshotFormatError, match=message):
        disk_report_from_json(text=_mutated(document, path, value))


def test_missing_field_is_rejected(document: dict[str, Any]) -> None:
    del document["devdirs_truncated"]

    with pytest.raises(SnapshotFormatError, match="devdirs_truncated"):
        disk_report_from_json(text=json.dumps(document))


def test_non_json_text_is_a_format_error() -> None:
    with pytest.raises(SnapshotFormatError):
        disk_report_from_json(text="{not json")


def test_report_saved_before_markers_decodes_with_an_empty_marker() -> None:
    decoded = disk_report_from_json(text=SAMPLE.read_text(encoding="utf-8"))

    assert [d.marker for d in decoded.devdirs] == [""]


def test_devdir_marker_survives_a_roundtrip(document: dict[str, Any]) -> None:
    document["devdirs"][0]["marker"] = "Cargo.toml"

    decoded = disk_report_from_json(text=json.dumps(document))

    assert decoded.devdirs[0].marker == "Cargo.toml"
    assert json.loads(disk_report_to_json(report=decoded)) == document


def test_devdir_marker_of_the_wrong_type_is_rejected(document: dict[str, Any]) -> None:
    document["devdirs"][0]["marker"] = 7

    with pytest.raises(SnapshotFormatError, match="marker"):
        disk_report_from_json(text=json.dumps(document))


def _report_with_kinds(*kinds: CacheKind) -> DiskReport:
    return report(caches=tuple(cache(kind=kind, size=MB) for kind in kinds))


def test_a_cache_of_a_new_type_survives_a_roundtrip() -> None:
    built = _report_with_kinds(CacheKind.CARGO_REGISTRY, CacheKind.JETBRAINS, CacheKind.GO_MOD)

    decoded = disk_report_from_json(text=disk_report_to_json(report=built))

    assert decoded == built
    assert [entry.kind.value for entry in decoded.caches] == [
        "cargo_registry",
        "jetbrains",
        "go_mod",
    ]


def test_a_report_saved_with_the_old_five_types_still_decodes() -> None:
    old = _report_with_kinds(
        CacheKind.UV, CacheKind.NPM, CacheKind.PIP, CacheKind.TRASH, CacheKind.THUMBNAILS
    )
    text = disk_report_to_json(report=old)

    assert disk_report_from_json(text=text) == old
    assert [entry["kind"] for entry in json.loads(text)["caches"]] == [
        "uv",
        "npm",
        "pip",
        "trash",
        "thumbnails",
    ]


def test_a_type_outside_the_catalog_is_still_rejected(document: dict[str, Any]) -> None:
    with pytest.raises(SnapshotFormatError, match="CacheKind"):
        disk_report_from_json(text=_mutated(document, ("caches", 0, "kind"), "cargo"))


def test_schema_version_written_is_three(document: dict[str, Any]) -> None:
    decoded = disk_report_from_json(text=json.dumps(document))

    assert json.loads(disk_report_to_json(report=decoded))["schema"] == 3


def test_schema_version_previous_report_is_rejected(document: dict[str, Any]) -> None:
    document["schema"] = 1

    with pytest.raises(SnapshotFormatError, match="schema"):
        disk_report_from_json(text=json.dumps(document))


def test_schema_version_future_report_is_rejected(document: dict[str, Any]) -> None:
    document["schema"] = 4

    with pytest.raises(SnapshotFormatError, match="schema"):
        disk_report_from_json(text=json.dumps(document))
