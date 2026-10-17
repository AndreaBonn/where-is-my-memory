"""A1: whether the welcome was already shown. Plain files, no GTK: the app checks it at start."""

import logging
from pathlib import Path

LOGGER = logging.getLogger(__name__)
# An empty marker in the state directory; its presence is all that matters.
WELCOMED_FILE = "welcomed"


def is_first_run(*, state_dir: Path) -> bool:
    """True until the welcome has been closed once.

    A directory that cannot be read counts as seen: otherwise a broken state directory
    would open the window at every login.
    """
    try:
        return not (state_dir / WELCOMED_FILE).exists()
    except OSError:
        LOGGER.warning("Cannot read the welcome marker in %s", state_dir, exc_info=True)
        return False


def mark_welcomed(*, state_dir: Path) -> None:
    """Remember that the welcome was seen; creates the directory if needed, never raises."""
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / WELCOMED_FILE).touch()
    except OSError:
        LOGGER.warning("Cannot remember the welcome in %s", state_dir, exc_info=True)


def opens_window(*, background: bool, state_dir: Path) -> bool:
    """The window opens unless started in the background, except on the first run."""
    return not background or is_first_run(state_dir=state_dir)
