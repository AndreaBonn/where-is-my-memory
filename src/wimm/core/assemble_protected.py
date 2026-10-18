"""Ordering and protected-summary helpers of the snapshot assembly (pure)."""

from collections.abc import Mapping

from wimm.i18n import N_, _
from wimm.model.enums import Protection, protection_of
from wimm.model.snapshot import Group, ProtectedSummaryItem

from .grouping import GroupDraft
from .grouping_keys import (
    LABEL_AUDIO,
    LABEL_OTHER_USERS,
    LABEL_PODMAN,
    LABEL_SELF,
    LABEL_SESSION,
    LABEL_SYSTEM,
)

PROTECTED_REASONS: Mapping[str, str] = {
    LABEL_AUDIO[0]: N_("audio e media del desktop"),
    LABEL_SESSION[0]: N_("componente del desktop"),
    LABEL_OTHER_USERS[0]: N_("processi di altri utenti, non modificabili da qui"),
    LABEL_SYSTEM[0]: N_("servizio di sistema"),
    LABEL_SELF[0]: N_("questa applicazione"),
    LABEL_PODMAN[0]: N_("container Podman che il motore non mostra, non modificabili da qui"),
}


def protected_item(*, draft: GroupDraft, group: Group) -> ProtectedSummaryItem:
    return ProtectedSummaryItem(
        label=draft.name, memory=group.memory.used, reason=_(PROTECTED_REASONS[draft.key])
    )


def ranked(*, groups: list[Group]) -> tuple[Group, ...]:
    return tuple(sorted(groups, key=lambda item: (-item.memory.reclaimable, item.name, item.id)))


def actionable(*, built: list[tuple[GroupDraft, Group]]) -> list[Group]:
    return [
        group
        for draft, group in built
        if protection_of(category=draft.category) is Protection.ACTIONABLE
    ]


def protected_summary(*, built: list[tuple[GroupDraft, Group]]) -> tuple[ProtectedSummaryItem, ...]:
    items = [
        protected_item(draft=draft, group=group)
        for draft, group in built
        if protection_of(category=draft.category) is Protection.PROTECTED
    ]
    return tuple(sorted(items, key=lambda item: (-item.memory, item.label)))
