"""What a planner needs to know about tools on PATH: the lookup is injected, never called here."""

from collections.abc import Callable
from typing import Protocol

from wimm.i18n import N_
from wimm.model.actions import ActionRequest
from wimm.model.disk import DiskReport
from wimm.model.errors import InvalidRequest

from .planning_drafts import Draft

__all__ = ["CacheToolMissing", "ToolPlanner", "no_tool"]


def no_tool(_name: str) -> None:
    """The default lookup of a pure planner: no tool is on PATH, so command-only caches wait."""
    return None


class CacheToolMissing(InvalidRequest):
    """The cache can only be cleaned by a tool that is not installed, so no action is offered."""

    code = "CACHE_TOOL_MISSING"
    message = "The tool that cleans this cache is not on PATH"
    user_message = N_("Lo strumento che pulisce questa cache non è installato")


class ToolPlanner(Protocol):
    """A disk planner that also asks whether a tool is on PATH (`which`, injected)."""

    def __call__(
        self,
        *,
        request: ActionRequest,
        report: DiskReport | None,
        which: Callable[[str], str | None],
    ) -> list[Draft]: ...
