"""T063: the kernel-side memory voices and the video memory row of the summary."""

from dataclasses import dataclass

from wimm.i18n import N_, _
from wimm.model.enums import GpuVendor
from wimm.model.memory import MemoryBreakdown
from wimm.model.snapshot import Snapshot

from .format import format_size

VIDEO_TITLE = N_("Memoria video")
VIDEO_LINE = N_("{vendor} {used} di {total}")
VENDOR_NAMES = {GpuVendor.NVIDIA: "NVIDIA", GpuVendor.AMD: "AMD"}


@dataclass(frozen=True, slots=True)
class Voice:
    """A breakdown voice: where to read it, how to call it and how to explain it."""

    key: str
    label: str
    question: str
    answer: str


# Display order: files in memory first, then what the kernel keeps, then the compressed swap.
VOICES = (
    Voice(
        key="shared_tmpfs",
        label=N_("Memoria condivisa e file temporanei (tmpfs)"),
        question=N_("Cos'è la memoria condivisa (tmpfs)?"),
        answer=N_(
            "Sono file tenuti nella memoria invece che sul disco, per esempio quelli temporanei "
            "o condivisi tra programmi. Non si possono liberare chiudendo un programma: "
            "restano finché non vengono cancellati o il computer si spegne."
        ),
    ),
    Voice(
        key="kernel_unreclaimable",
        label=N_("Memoria del kernel non recuperabile"),
        question=N_("Cos'è la memoria del kernel non recuperabile?"),
        answer=N_(
            "Il kernel è il cuore del sistema e tiene da parte memoria per i propri compiti. "
            "Questa parte non si può liberare chiudendo un programma: il sistema la restituisce "
            "da solo quando non gli serve più."
        ),
    ),
    Voice(
        key="zram",
        label=N_("Swap compresso in RAM (zram)"),
        question=N_("Cos'è lo swap compresso (zram)?"),
        answer=N_(
            "È una parte della memoria che il sistema usa per comprimere i dati che non "
            "stanno più nella RAM, invece di scriverli sul disco. Non si può liberare chiudendo "
            "un programma: si svuota da sola quando quei dati tornano utili."
        ),
    ),
    Voice(
        key="zswap",
        label=N_("Swap compresso (zswap)"),
        question=N_("Cos'è lo swap compresso (zswap)?"),
        answer=N_(
            "È una piccola riserva di memoria in cui il sistema comprime i dati prima di "
            "spostarli sul disco. Non si può liberare chiudendo un programma: la gestisce il "
            "sistema da solo."
        ),
    ),
)


def voice_items(*, breakdown: MemoryBreakdown) -> list[tuple[str, str, int]]:
    """The voices above zero as (key, label, size); zram and zswap are missing on many systems."""
    sizes = [(voice, getattr(breakdown, voice.key)) for voice in VOICES]
    return [(voice.key, _(voice.label), size) for voice, size in sizes if size > 0]


def voice_help(*, key: str) -> tuple[str, str]:
    """(question, answer) for a voice key, or two empty strings for an ordinary segment."""
    for voice in VOICES:
        if voice.key == key:
            return _(voice.question), _(voice.answer)
    return "", ""


def video_lines(*, snapshot: Snapshot) -> tuple[str, ...]:
    """One line per GPU, never summed with the RAM breakdown."""
    return tuple(
        _(VIDEO_LINE).format(
            vendor=VENDOR_NAMES[gpu.vendor],
            used=format_size(size=gpu.used_bytes),
            total=format_size(size=gpu.total_bytes),
        )
        for gpu in snapshot.memory.video
    )
