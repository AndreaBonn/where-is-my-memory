import tomllib
from pathlib import Path

LOCKFILE = Path(__file__).resolve().parent.parent / "uv.lock"
# The venv is created with --system-site-packages (ADR-002): a locked copy of these would
# shadow the apt one. requests 2.34 from PyPI broke python3-docker 5.0.3 ("Not supported URL
# scheme http+docker"), so Docker looked unavailable in every development run.
# pygobject is locked but never installed: override-dependencies in pyproject.toml gives it
# an impossible marker.
APT_PROVIDED = frozenset({"docker", "psutil", "requests", "urllib3"})


def locked_package_names(*, text: str) -> frozenset[str]:
    return frozenset(item["name"] for item in tomllib.loads(text).get("package", []))


def test_locked_package_names_reads_the_lock_format() -> None:
    text = '[[package]]\nname = "ruff"\n\n[[package]]\nname = "requests"\n'
    assert locked_package_names(text=text) == {"ruff", "requests"}


def test_lockfile_does_not_shadow_apt_provided_libraries() -> None:
    locked = locked_package_names(text=LOCKFILE.read_text(encoding="utf-8"))
    assert locked
    assert locked & APT_PROVIDED == set()
