"""F1: only an image a registry is known to hold is offered as safe to remove."""

from typing import Any

import pytest

from wimm.core.disk_rules import safe_reclaimable_bytes
from wimm.core.image_provenance import identity_expected, is_pull_proven, with_provenance

from .disk_helpers import MB, docker_disk, image, report, sha

PULLED = {"Identity": {"Pull": [{"Repository": "docker.io/library/alpine"}]}}
BUILT = {"Identity": {"Build": [{"Ref": "lhyljjokscn8", "CreatedAt": "2026-10-13T21:58:45Z"}]}}


@pytest.mark.parametrize(
    ("inspected", "expected"),
    [
        (PULLED, True),
        (BUILT, False),
        ({"Identity": {"Pull": [], "Build": []}}, False),
        ({"Identity": {}}, False),
        ({"Identity": None}, False),
        (None, False),
        (["not", "a", "mapping"], False),
        ({"Id": sha("a")}, True),
    ],
    ids=[
        "pulled",
        "built-here",
        "empty-lists",
        "empty-identity",
        "null-identity",
        "inspect-failed",
        "malformed",
        "engine-without-identity-keeps-digest-rule",
    ],
)
def test_is_pull_proven_on_an_old_engine_trusts_only_a_pull_or_no_identity(
    inspected: Any, expected: bool
) -> None:
    assert is_pull_proven(inspected=inspected, identity_expected=False) is expected


def test_is_pull_proven_on_an_engine_with_identity_needs_the_pull() -> None:
    assert is_pull_proven(inspected={"Id": sha("a")}, identity_expected=True) is False
    assert is_pull_proven(inspected=PULLED, identity_expected=True) is True


def test_an_image_pulled_and_also_built_here_counts_as_pulled() -> None:
    both = {"Identity": {**PULLED["Identity"], **BUILT["Identity"]}}

    assert is_pull_proven(inspected=both, identity_expected=True) is True


@pytest.mark.parametrize(
    ("version", "expected"),
    [("1.53", True), ("1.56", True), ("2.0", True), ("1.52", False), ("1.41", False), ("", True)],
)
def test_identity_expected_from_api_1_53_and_when_the_version_is_unreadable(
    version: str, expected: bool
) -> None:
    assert identity_expected(api_version=version) is expected


def test_with_provenance_marks_a_digest_carrying_local_build_as_local() -> None:
    docker = docker_disk(images=(image(char="a"), image(char="b")))

    marked = with_provenance(
        docker=docker, identity=True, inspected={sha("a"): PULLED, sha("b"): BUILT}
    )

    assert {i.id: i.local_build for i in marked.images} == {sha("a"): False, sha("b"): True}


def test_with_provenance_treats_an_image_left_uninspected_as_local() -> None:
    docker = docker_disk(images=(image(char="a"),))

    assert with_provenance(docker=docker, identity=True, inspected={}).images[0].local_build is True


def test_with_provenance_never_turns_a_local_build_into_a_pullable_one() -> None:
    docker = docker_disk(images=(image(char="a", local_build=True),))

    marked = with_provenance(docker=docker, identity=True, inspected={sha("a"): PULLED})

    assert marked.images[0].local_build is True


def test_safe_total_counts_the_pulled_image_and_not_the_one_built_here() -> None:
    images = (image(char="a", size=100 * MB), image(char="b", size=7 * MB))
    docker = with_provenance(
        docker=docker_disk(images=images),
        identity=True,
        inspected={sha("a"): BUILT, sha("b"): PULLED},
    )

    assert safe_reclaimable_bytes(report=report(docker=docker)) == 7 * MB
