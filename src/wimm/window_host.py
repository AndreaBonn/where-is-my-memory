"""The panel window, built only when first asked for, so GTK loads only then."""

import logging
from collections.abc import Callable
from typing import Protocol

LOGGER = logging.getLogger(__name__)


class PresentableWindow(Protocol):
    def show_group(self, group_id: str | None) -> None: ...

    def set_tray_missing(self, missing: bool) -> None: ...

    def get_visible(self) -> bool: ...

    def save_size(self) -> None: ...

    def destroy(self) -> None: ...


class WindowHost:
    """Owns the panel window, built on the first request so GTK loads only then."""

    def __init__(self, *, factory: Callable[[], PresentableWindow]) -> None:
        self._factory = factory
        self._window: PresentableWindow | None = None
        self._tray_missing = False

    def set_tray_missing(self, *, missing: bool) -> None:
        """Remember whether the icon has no host; a window not built yet is not created."""
        self._tray_missing = missing
        if self._window is not None:
            self._window.set_tray_missing(missing)

    def present(self, group_id: str | None) -> None:
        if group_id is not None:
            LOGGER.info("Window requested for group %s", group_id)
        if self._window is None:
            try:
                self._window = self._factory()
            except Exception:
                # No display (session gone, SSH, tests): monitoring and notifications go on.
                LOGGER.exception("Cannot open the window")
                return
            if self._tray_missing:
                self._window.set_tray_missing(True)
        self._window.show_group(group_id=group_id)

    def rebuild(self, *, then: Callable[[PresentableWindow], None] | None = None) -> None:
        """Build the window again, so every label is created in the active language.

        A hidden window is only dropped: the next request builds the new one. ``then``
        runs on the new window once it is shown, for example to reopen a dialog.
        """
        old = self._window
        if old is None:
            return
        visible = old.get_visible()
        old.save_size()
        old.destroy()
        self._window = None
        if not visible:
            return
        self.present(group_id=None)
        if self._window is not None and then is not None:
            then(self._window)
