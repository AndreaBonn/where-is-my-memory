"""Whether a registry holds an image, from `GET /images/{id}/json` (Engine API 1.53+).

With the containerd image store every image gets `RepoDigests`, a local build too, so a
digest does not prove the image can be pulled again. The `Identity` field does: `Pull`
names the repository it came from, `Build` marks an image built on this machine.
"""

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from wimm.model.disk import DockerDisk

# The Engine API version whose image inspect carries `Identity`.
IDENTITY_API = (1, 53)


def identity_expected(*, api_version: str) -> bool:
    """True when the engine's API reports `Identity`; an unreadable version counts as yes."""
    try:
        major, minor = (int(part) for part in api_version.split(".")[:2])
    except ValueError:
        return True
    return (major, minor) >= IDENTITY_API


def is_pull_proven(*, inspected: Any, identity_expected: bool) -> bool:
    """True when the inspect answer shows a registry origin.

    Only on an engine older than API 1.53 does a missing `Identity` keep the digest rule,
    because there a local build has no digests. A failed or malformed inspection, or an
    `Identity` without a pull, proves nothing.
    """
    if not isinstance(inspected, Mapping):
        return False
    if "Identity" not in inspected:
        return not identity_expected
    identity = inspected["Identity"]
    return isinstance(identity, Mapping) and bool(identity.get("Pull"))


def with_provenance(
    *, docker: DockerDisk, inspected: Mapping[str, Any], identity: bool
) -> DockerDisk:
    """Mark as a local build every image whose pull `inspected` does not prove.

    ``inspected`` maps an image id to its inspect answer, or to None when it failed; an
    image missing from it counts as unproven. ``identity`` says whether the engine reports
    `Identity`. A local build never becomes pullable here.
    """
    images = tuple(
        image
        if image.local_build
        or is_pull_proven(inspected=inspected.get(image.id), identity_expected=identity)
        else replace(image, local_build=True)
        for image in docker.images
    )
    return replace(docker, images=images)
