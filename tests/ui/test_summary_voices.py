"""T063: the new memory voices and the video memory row of the summary."""

from dataclasses import replace

import pytest
from gi.repository import Gtk

from tests.ui.conftest import descendants
from wimm.model.enums import GpuVendor
from wimm.model.memory import GpuMemory
from wimm.model.snapshot import Snapshot
from wimm.ui.viewmodel import build_summary
from wimm.ui.widgets import icon_only_label
from wimm.ui.widgets.memory_bar import MemoryBar
from wimm.ui.widgets.summary import SummaryPanel

GB = 1_000_000_000
TMPFS = "Memoria condivisa e file temporanei (tmpfs)"
KERNEL = "Memoria del kernel non recuperabile"
ZRAM = "Swap compresso in RAM (zram)"
ZSWAP = "Swap compresso (zswap)"


def with_voices(
    snapshot: Snapshot,
    *,
    shared_tmpfs: int = 0,
    kernel_unreclaimable: int = 0,
    zram: int = 0,
    zswap: int = 0,
) -> Snapshot:
    breakdown = replace(
        snapshot.memory.breakdown,
        shared_tmpfs=shared_tmpfs,
        kernel_unreclaimable=kernel_unreclaimable,
        zram=zram,
        zswap=zswap,
    )
    return replace(snapshot, memory=replace(snapshot.memory, breakdown=breakdown))


def with_video(snapshot: Snapshot, *gpus: GpuMemory) -> Snapshot:
    return replace(snapshot, memory=replace(snapshot.memory, video=gpus))


def labels(snapshot: Snapshot) -> list[str]:
    return [segment.label for segment in build_summary(snapshot=snapshot).segments]


def test_voices_at_zero_are_not_listed(snapshot: Snapshot) -> None:
    shown = labels(with_voices(snapshot, shared_tmpfs=0, zram=0, zswap=0, kernel_unreclaimable=0))

    assert not {TMPFS, KERNEL, ZRAM, ZSWAP} & set(shown)


def test_voices_above_zero_are_listed_between_the_cache_and_unattributed(
    snapshot: Snapshot,
) -> None:
    shown = labels(
        with_voices(
            snapshot, shared_tmpfs=GB, kernel_unreclaimable=2 * GB, zram=3 * GB, zswap=4 * GB
        )
    )

    start = shown.index(TMPFS)
    assert shown[start : start + 5] == [TMPFS, KERNEL, ZRAM, ZSWAP, "Non attribuita"]


def test_only_the_nonzero_voice_appears_with_its_size(snapshot: Snapshot) -> None:
    view = build_summary(snapshot=with_voices(snapshot, zram=GB, zswap=0))

    (zram,) = [s for s in view.segments if s.key == "zram"]
    assert zram.legend == f"{ZRAM}: {zram.size_text}"
    assert zram.help_question == "Cos'è lo swap compresso (zram)?"
    assert "liberare chiudendo un programma" in zram.help_answer
    assert all(s.key != "zswap" for s in view.segments)


def test_ordinary_segments_carry_no_help(snapshot: Snapshot) -> None:
    view = build_summary(snapshot=with_voices(snapshot, zram=GB))

    voice_keys = {"shared_tmpfs", "kernel_unreclaimable", "zram", "zswap"}
    plain = [s for s in view.segments if s.key not in voice_keys]
    assert plain
    assert all(s.help_question == "" and s.help_answer == "" for s in plain)


def test_no_gpu_means_no_video_lines(snapshot: Snapshot) -> None:
    view = build_summary(snapshot=with_video(snapshot))

    assert view.video_lines == ()
    assert view.video_title == "Memoria video"


def test_video_lines_name_the_vendor_one_per_gpu_and_never_touch_the_ram_bar(
    snapshot: Snapshot,
) -> None:
    gpus = (
        GpuMemory(vendor=GpuVendor.NVIDIA, used_bytes=2 * GB, total_bytes=8 * GB),
        GpuMemory(vendor=GpuVendor.AMD, used_bytes=GB, total_bytes=4 * GB),
    )
    plain, with_gpu = (
        build_summary(snapshot=snapshot),
        build_summary(snapshot=with_video(snapshot, *gpus)),
    )

    assert with_gpu.video_lines == ("NVIDIA 2,0 GB di 8,0 GB", "AMD 1,0 GB di 4,0 GB")
    assert with_gpu.segments == plain.segments


@pytest.mark.ui
def test_new_voices_have_an_accessible_name_and_a_help_button(
    display: None, snapshot: Snapshot
) -> None:
    bar = MemoryBar()
    bar.update(segments=build_summary(snapshot=with_voices(snapshot, shared_tmpfs=GB)).segments)

    legend = [w.get_label() for w in descendants(bar) if isinstance(w, Gtk.Label)]
    assert any(text.startswith(TMPFS) for text in legend)
    helps = [w for w in descendants(bar) if isinstance(w, Gtk.MenuButton)]
    (help_,) = [h for h in helps if "tmpfs" in (icon_only_label(button=h) or "")]
    assert icon_only_label(button=help_) == "Cos'è la memoria condivisa (tmpfs)?"
    assert help_.get_tooltip_text() == "Cos'è la memoria condivisa (tmpfs)?"


@pytest.mark.ui
def test_video_row_is_visible_with_a_gpu_and_hidden_without(
    display: None, snapshot: Snapshot
) -> None:
    gpu = GpuMemory(vendor=GpuVendor.NVIDIA, used_bytes=2 * GB, total_bytes=8 * GB)
    panel = SummaryPanel()

    panel.update(view=build_summary(snapshot=with_video(snapshot, gpu)))
    shown = [w for w in descendants(panel) if w.get_name() == "video-memory"]
    texts = [w.get_label() for w in descendants(shown[0]) if isinstance(w, Gtk.Label)]
    assert shown[0].get_visible()
    assert texts == ["Memoria video", "NVIDIA 2,0 GB di 8,0 GB"]

    panel.update(view=build_summary(snapshot=with_video(snapshot)))
    assert not shown[0].get_visible()
