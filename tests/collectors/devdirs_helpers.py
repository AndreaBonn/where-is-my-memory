import os
from pathlib import Path

from wimm.collectors.devdirs import DevDirScan, DevDirSettings, scan_devdirs
from wimm.core.devdir_rules import CACHEDIR_TAG, VENV_MARKER

NOW = 1_800_000_000.0
DAY = 86400


def _age(path: Path, days: float) -> None:
    stamp = NOW - days * DAY
    os.utime(path, (stamp, stamp), follow_symlinks=False)


def _scan(
    root: Path,
    tmp_path: Path,
    *,
    max_depth: int = 6,
    sleeps: list[float] | None = None,
    home: Path | None = None,
) -> DevDirScan:
    record = sleeps if sleeps is not None else []
    settings = DevDirSettings(
        roots=(root,), home=home if home is not None else tmp_path, max_depth=max_depth
    )
    return scan_devdirs(
        settings=settings, cache_dir=tmp_path / "sizes", now=NOW, sleep=record.append
    )


def _paths(result: DevDirScan) -> set[str]:
    return {item.path for item in result.devdirs}


def _project(root: Path, name: str, *, age: float = 100) -> Path:
    project = root / name
    project.mkdir(parents=True)
    (project / "node_modules").mkdir()
    (project / "node_modules" / "dep.js").write_bytes(b"x" * 5000)
    (project / "setup.py").write_text("x")
    _age(project / "setup.py", age)
    return project


def _venv(path: Path) -> Path:
    """A virtual environment as the scan recognises it: the folder holds ``pyvenv.cfg``."""
    (path / "lib").mkdir(parents=True)
    (path / VENV_MARKER).write_text("home = /usr/bin\n")
    return path


def _build(project: Path, *, marker: str, folder: str, signal: str | None = None) -> Path:
    """A project with a ``marker`` file, a ``folder`` of output and the second ``signal``."""
    project.mkdir(parents=True, exist_ok=True)
    (project / marker).write_text("x")
    output = project / folder
    (output / "debug").mkdir(parents=True)
    (output / "debug" / "artifact.bin").write_bytes(b"x" * 100)
    if signal == CACHEDIR_TAG:
        (output / CACHEDIR_TAG).write_text("Signature: 8a477f597d28d172789f06886806bc55\n")
    elif signal == "gitignore":
        (project / ".gitignore").write_text(f"*.log\n/{folder}/\n")
    _age(project / marker, 100)
    return output
