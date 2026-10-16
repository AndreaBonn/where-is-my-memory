import os
from pathlib import Path

import docker
import psutil
import pytest

EXPECTED_PSUTIL_VERSION = "5.9.8"
EXPECTED_DOCKER_VERSION = "5.0.3"
SYSTEM_PACKAGES = Path("/usr/lib/python3/dist-packages")
pytestmark = pytest.mark.skipif(
    "WIMM_SKIP_RUNTIME_PIN" in os.environ,
    reason="Runtime pins explicitly disabled by WIMM_SKIP_RUNTIME_PIN",
)


def test_runtime_psutil_matches_system_package() -> None:
    assert psutil.__version__ == EXPECTED_PSUTIL_VERSION
    assert Path(psutil.__file__).resolve().is_relative_to(SYSTEM_PACKAGES)


def test_runtime_docker_matches_system_version() -> None:
    assert docker.__version__ == EXPECTED_DOCKER_VERSION
