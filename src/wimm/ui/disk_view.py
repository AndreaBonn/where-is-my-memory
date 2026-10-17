"""Pure view model of the Disco page: a disk report in, sections with rows out."""

from dataclasses import replace
from datetime import datetime

from wimm.core.constants import DISK_SECTION_CAP
from wimm.core.risk import RiskTarget
from wimm.model.disk import CacheEntry, CacheKind, DevDir, DiskReport
from wimm.model.enums import ActionKind
from wimm.ui.disk_model import ActionSpec, DiskRowView, DiskSectionView, make_row, more_text
from wimm.ui.disk_texts import SECTION_DESCRIPTIONS
from wimm.ui.disk_view_docker import docker_sections

NO_SCAN_TEXT = "Nessun controllo ancora"
CACHE_TITLES = {
    CacheKind.UV: "uv",
    CacheKind.NPM: "npm",
    CacheKind.PIP: "pip",
    CacheKind.THUMBNAILS: "Miniature",
    CacheKind.TRASH: "Cestino",
}


def last_scan_text(*, report: DiskReport | None, now: datetime) -> str:
    """The header line: local time of the last scan, or the no-scan text."""
    if report is None:
        return NO_SCAN_TEXT
    local = report.scanned_at.astimezone()
    if local.date() == now.astimezone().date():
        return f"Ultimo controllo alle {local:%H:%M}"
    return f"Ultimo controllo il {local:%d/%m} alle {local:%H:%M}"


def _cache_row(*, entry: CacheEntry) -> DiskRowView:
    trash = entry.kind is CacheKind.TRASH
    action = ActionSpec(
        kind=ActionKind.TRASH_EMPTY if trash else ActionKind.CACHE_CLEAN,
        target=RiskTarget(kind="trash" if trash else "cache"),
        # trash_empty takes no target (the planner finds the trash); a cache is named by kind.
        target_id=None if trash else entry.kind.value,
    )
    return make_row(
        title=CACHE_TITLES[entry.kind], subtitle=entry.path, size=entry.size, action=action
    )


def _devdir_row(*, item: DevDir) -> DiskRowView:
    action = ActionSpec(ActionKind.DEVDIR_DELETE, RiskTarget(kind="devdir"), item.path)
    return make_row(
        title=item.path,
        subtitle=f"progetto fermo da {item.age_days} giorni",
        size=item.size,
        action=action,
    )


def _capped(*, rows: tuple[DiskRowView, ...], hidden: int) -> tuple[tuple[DiskRowView, ...], int]:
    shown = rows[:DISK_SECTION_CAP]
    return shown, hidden + len(rows) - len(shown)


def _listed(*, key: str, title: str, rows: tuple[DiskRowView, ...], empty: str) -> DiskSectionView:
    return DiskSectionView(key=key, title=title, rows=rows, message=None if rows else empty)


def _devdirs_section(*, report: DiskReport, min_age_days: int) -> DiskSectionView:
    largest_first = sorted(report.devdirs, key=lambda d: -d.size)
    dirs = tuple(_devdir_row(item=d) for d in largest_first)
    shown, hidden = _capped(rows=dirs, hidden=report.devdirs_truncated)
    empty = (
        f"Nessuna cartella di dipendenze più vecchia di {min_age_days} giorni "
        "nelle radici configurate"
    )
    return DiskSectionView(
        "devdirs",
        "Cartelle di dipendenze",
        shown,
        more_text(count=hidden),
        None if shown else empty,
    )


def _local_sections(*, report: DiskReport, min_age_days: int) -> tuple[DiskSectionView, ...]:
    caches = tuple(_cache_row(entry=e) for e in report.caches if e.kind is not CacheKind.TRASH)
    trash = tuple(_cache_row(entry=e) for e in report.caches if e.kind is CacheKind.TRASH)
    return (
        _listed(key="caches", title="Cache", rows=caches, empty="Nessuna cache trovata"),
        _devdirs_section(report=report, min_age_days=min_age_days),
        _listed(key="trash", title="Cestino", rows=trash, empty="Cestino non rilevato"),
    )


def build_disk_sections(
    *, report: DiskReport | None, min_age_days: int
) -> tuple[DiskSectionView, ...]:
    """All sections of the page; empty before the first scan."""
    if report is None:
        return ()
    sections = docker_sections(report=report) + _local_sections(
        report=report, min_age_days=min_age_days
    )
    return tuple(replace(s, description=SECTION_DESCRIPTIONS[s.key]) for s in sections)
