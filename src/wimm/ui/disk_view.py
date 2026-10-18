"""Pure view model of the Disco page: a disk report in, sections with rows out."""

from dataclasses import replace
from datetime import datetime
from pathlib import Path, PurePath

from wimm.core.cache_catalog import COMMAND_ONLY_KINDS
from wimm.core.cache_titles import CACHE_TITLES
from wimm.core.constants import DISK_SECTION_CAP
from wimm.core.risk import RiskTarget
from wimm.i18n import N_, _, ngettext
from wimm.model.disk import CacheEntry, CacheKind, DevDir, DiskReport
from wimm.model.enums import ActionKind
from wimm.ui.disk_model import (
    ROOTS_FINE,
    ActionSpec,
    DiskRowView,
    DiskSectionView,
    EmptyStateView,
    RootsState,
    make_row,
    more_text,
)
from wimm.ui.disk_texts import (
    CHOOSE_FOLDER_LABEL,
    MISSING_ROOT_TEXT,
    NO_ROOTS_TEXT,
    NO_ROOTS_TITLE,
    SECTION_DESCRIPTIONS,
    SECTION_TIERS,
)
from wimm.ui.disk_tiers import split_by_risk
from wimm.ui.disk_view_docker import docker_sections
from wimm.ui.format import home_relative, short_date

NO_SCAN_TEXT = N_("Nessun controllo ancora")
# Subfolders of a project whose name says nothing about which project it is.
GENERIC_PROJECT_FOLDERS = frozenset(
    {"frontend", "backend", "client", "server", "web", "app", "api", "functions", "ui", "src"}
)


def last_scan_text(*, report: DiskReport | None, now: datetime) -> str:
    """The header line: local time of the last scan, or the no-scan text."""
    if report is None:
        return _(NO_SCAN_TEXT)
    local = report.scanned_at.astimezone()
    if local.date() == now.astimezone().date():
        return _("Ultimo controllo alle {time}").format(time=f"{local:%H:%M}")
    return _("Ultimo controllo il {date} alle {time}").format(
        date=short_date(moment=local), time=f"{local:%H:%M}"
    )


def _cache_row(*, entry: CacheEntry, withheld: frozenset[CacheKind]) -> DiskRowView:
    action = None if entry.kind in withheld else _cache_action(entry=entry)
    return make_row(
        title=_(CACHE_TITLES[entry.kind]), subtitle=entry.path, size=entry.size, action=action
    )


def _cache_action(*, entry: CacheEntry) -> ActionSpec:
    trash = entry.kind is CacheKind.TRASH
    return ActionSpec(
        kind=ActionKind.TRASH_EMPTY if trash else ActionKind.CACHE_CLEAN,
        target=RiskTarget(kind="trash" if trash else "cache", cache_kind=entry.kind),
        # trash_empty takes no target (the planner finds the trash); a cache is named by kind.
        target_id=None if trash else entry.kind.value,
    )


def _devdir_title(*, path: PurePath) -> str:
    """F7: "progetto · cartella"; a generic project folder takes its parent along."""
    project = path.parent
    name = project.name
    if name.lower() in GENERIC_PROJECT_FOLDERS and project.parent.name:
        name = f"{project.parent.name}/{name}"
    return f"{name} · {path.name}"


def _devdir_row(*, item: DevDir) -> DiskRowView:
    action = ActionSpec(ActionKind.DEVDIR_DELETE, RiskTarget(kind="devdir"), item.path)
    age = ngettext(
        "progetto fermo da {days} giorno", "progetto fermo da {days} giorni", item.age_days
    ).format(days=item.age_days)
    where = home_relative(path=Path(item.path), home=Path.home())
    return make_row(
        title=_devdir_title(path=PurePath(item.path)),
        subtitle=f"{where} · {age}",
        size=item.size,
        action=action,
    )


def _capped(*, rows: tuple[DiskRowView, ...], hidden: int) -> tuple[tuple[DiskRowView, ...], int]:
    shown = rows[:DISK_SECTION_CAP]
    return shown, hidden + len(rows) - len(shown)


def _listed(*, key: str, title: str, rows: tuple[DiskRowView, ...], empty: str) -> DiskSectionView:
    return DiskSectionView(key=key, title=title, rows=rows, message=None if rows else empty)


def _roots_empty_state() -> EmptyStateView:
    return EmptyStateView(
        title=_(NO_ROOTS_TITLE), text=_(NO_ROOTS_TEXT), action_label=_(CHOOSE_FOLDER_LABEL)
    )


def _devdirs_section(
    *, report: DiskReport, min_age_days: int, roots: RootsState
) -> DiskSectionView:
    largest_first = sorted(report.devdirs, key=lambda d: -d.size)
    dirs = tuple(_devdir_row(item=d) for d in largest_first)
    shown, hidden = _capped(rows=dirs, hidden=report.devdirs_truncated)
    empty = ngettext(
        "Nessuna cartella di dipendenze più vecchia di {days} giorno nelle radici configurate",
        "Nessuna cartella di dipendenze più vecchia di {days} giorni nelle radici configurate",
        min_age_days,
    ).format(days=min_age_days)
    return DiskSectionView(
        "devdirs",
        _("Cartelle di dipendenze"),
        shown,
        more_text(count=hidden),
        None if shown or not roots.usable else empty,
        warnings=tuple(_(MISSING_ROOT_TEXT).format(path=path) for path in roots.missing),
        empty_state=None if roots.usable else _roots_empty_state(),
    )


def _local_sections(
    *, report: DiskReport, min_age_days: int, roots: RootsState, withheld: frozenset[CacheKind]
) -> tuple[DiskSectionView, ...]:
    def rows(*, trash: bool) -> tuple[DiskRowView, ...]:
        return tuple(
            _cache_row(entry=e, withheld=withheld)
            for e in report.caches
            if (e.kind is CacheKind.TRASH) is trash
        )

    caches, trash = rows(trash=False), rows(trash=True)
    return (
        _listed(key="caches", title=_("Cache"), rows=caches, empty=_("Nessuna cache trovata")),
        _devdirs_section(report=report, min_age_days=min_age_days, roots=roots),
        _listed(key="trash", title=_("Cestino"), rows=trash, empty=_("Cestino non rilevato")),
    )


def build_disk_sections(
    *,
    report: DiskReport | None,
    min_age_days: int,
    roots: RootsState = ROOTS_FINE,
    withheld: frozenset[CacheKind] = COMMAND_ONLY_KINDS,
) -> tuple[DiskSectionView, ...]:
    """All sections of the page; empty before the first scan.

    ``withheld`` are the caches left without an action because their tool is missing
    (`withheld_kinds`, computed by the caller)."""
    if report is None:
        return ()
    sections = split_by_risk(
        sections=docker_sections(report=report)
        + _local_sections(report=report, min_age_days=min_age_days, roots=roots, withheld=withheld)
    )
    # SECTION_TIERS lists the keys tier by tier: its order is the page order.
    order = list(SECTION_TIERS)
    described = (
        replace(s, description=_(SECTION_DESCRIPTIONS[s.key]), tier=SECTION_TIERS[s.key])
        for s in sections
    )
    return tuple(sorted(described, key=lambda s: order.index(s.key)))
