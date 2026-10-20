"""Pure view model of the Disco page: a disk report in, sections with rows out."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path, PurePath

from wimm.core.cache_catalog import COMMAND_ONLY_KINDS, withheld_kinds
from wimm.core.cache_titles import CACHE_TITLES
from wimm.core.constants import DISK_SECTION_CAP
from wimm.core.item_tools import ITEM_ONLY_KINDS, withheld_item_kinds
from wimm.core.risk import RiskTarget
from wimm.core.row_consequence import row_consequence
from wimm.i18n import N_, _, ngettext
from wimm.model.disk import CacheEntry, CacheKind, DevDir, DiskReport
from wimm.model.enums import ActionKind
from wimm.ui.disk_items import item_rows
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
from wimm.ui.disk_ollama import OLLAMA_SYSTEM_SUBTITLE, ollama_cache_row, parse_served
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


def withheld_for_report(
    *,
    report: DiskReport | None,
    which: Callable[[str], str | None],
    is_executable: Callable[[str], bool],
) -> frozenset[CacheKind]:
    """The kinds whose tool is missing; Android tools are looked for in the reported SDK."""
    caches = report.caches if report else ()
    roots = tuple(entry.path for entry in caches if entry.kind is CacheKind.ANDROID_SDK)
    items = withheld_item_kinds(sdk_roots=roots, is_executable=is_executable, which=which)
    return withheld_kinds(which=which) | items


def _cache_row(
    *, entry: CacheEntry, withheld: frozenset[CacheKind], served: str = ""
) -> DiskRowView:
    # A missing tool takes the action away from what it cleans: a command-only cache, or
    # the items of a cache removed one by one with their tool (Android).
    cache_withheld = entry.kind in withheld and entry.kind in COMMAND_ONLY_KINDS
    # An item-only cache (the system ollama store) has no whole-cache clean at all.
    no_clean = cache_withheld or entry.kind in ITEM_ONLY_KINDS
    action = None if no_clean else _cache_action(entry=entry)
    # The system store has no path to show (its "path" is the command): say what the size is.
    system = entry.kind is CacheKind.OLLAMA_SYSTEM
    row = make_row(
        title=_(CACHE_TITLES[entry.kind]),
        subtitle=_(OLLAMA_SYSTEM_SUBTITLE) if system else entry.path,
        size=entry.size,
        action=action,
    )
    row = ollama_cache_row(row=row, kind=entry.kind, served=parse_served(value=served))
    view = item_rows(
        entry=entry, removable=entry.kind not in withheld, served=parse_served(value=served)
    )
    return replace(row, items=view.rows, items_more=view.more_text) if view.rows else row


def _cache_action(*, entry: CacheEntry) -> ActionSpec:
    trash = entry.kind is CacheKind.TRASH
    kind = ActionKind.TRASH_EMPTY if trash else ActionKind.CACHE_CLEAN
    target = RiskTarget(kind="trash" if trash else "cache", cache_kind=entry.kind)
    return ActionSpec(
        kind=kind,
        target=target,
        # trash_empty takes no target (the planner finds the trash); a cache is named by kind.
        target_id=None if trash else entry.kind.value,
        consequence=row_consequence(action=kind, target=target),
    )


def _devdir_title(*, path: PurePath) -> str:
    """F7: "progetto · cartella"; a generic project folder takes its parent along."""
    project = path.parent
    name = project.name
    if name.lower() in GENERIC_PROJECT_FOLDERS and project.parent.name:
        name = f"{project.parent.name}/{name}"
    return f"{name} · {path.name}"


def _devdir_row(*, item: DevDir) -> DiskRowView:
    target = RiskTarget(kind="devdir")
    action = ActionSpec(
        ActionKind.DEVDIR_DELETE,
        target,
        item.path,
        consequence=row_consequence(
            action=ActionKind.DEVDIR_DELETE,
            target=target,
            folder_name=PurePath(item.path).name,
            marker=item.marker,
        ),
    )
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
            _cache_row(entry=e, withheld=withheld, served=report.ollama_served)
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

    ``withheld`` are the kinds whose tool is missing (`withheld_kinds` and
    `withheld_item_kinds`, computed by the caller): a command-only cache loses its action,
    an item kind the actions of its items."""
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
