from gi.repository import Gtk

from wimm.i18n import N_, _
from wimm.ui.views import BarSegment

from . import clear_children
from .help_button import help_button

PALETTE_SIZE = 8
SPECIAL_CLASSES = {
    "other_programs": "other",
    "kernel_cache": "cache",
    "unattributed": "unattributed",
    "free": "free",
}
BAR_LABEL = N_("Memoria per categoria")
LEGEND_COLUMNS = 6
BAR_SPACING = 6
LEGEND_COLUMN_SPACING = 12
LEGEND_ROW_SPACING = 2
SWATCH_SPACING = 6
# A segment rounded to 0% still gets one grid column, so every category stays visible.
MIN_SEGMENT_SPAN = 1


def segment_classes(*, segments: tuple[BarSegment, ...]) -> list[str]:
    """Assign a style class per segment: fixed ones for the remainders, a palette for the rest."""
    classes = []
    palette_index = 0
    for segment in segments:
        special = SPECIAL_CLASSES.get(segment.key)
        if special is None:
            special = str(palette_index % PALETTE_SIZE)
            palette_index += 1
        classes.append(f"wimm-seg-{special}")
    return classes


class MemoryBar(Gtk.Box):
    """Segmented RAM bar with an always-visible text legend (spec 10.4)."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=BAR_SPACING)
        self._segments: tuple[BarSegment, ...] = ()
        self._legend_labels: list[Gtk.Label] = []
        # 100 homogeneous columns: a segment spans as many columns as its percentage.
        self._grid = Gtk.Grid(column_homogeneous=True, hexpand=True, overflow=Gtk.Overflow.HIDDEN)
        self._grid.add_css_class("wimm-bar")
        self._legend = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            max_children_per_line=LEGEND_COLUMNS,
            column_spacing=LEGEND_COLUMN_SPACING,
            row_spacing=LEGEND_ROW_SPACING,
            homogeneous=False,
        )
        self.append(self._grid)
        self.append(self._legend)

    def update(self, *, segments: tuple[BarSegment, ...]) -> None:
        """Redraw the bar and the legend when the segments changed."""
        if segments == self._segments:
            return
        same_entries = _legend_identity(segments=segments) == _legend_identity(
            segments=self._segments
        )
        self._segments = segments
        clear_children(container=self._grid)
        column = 0
        classes = segment_classes(segments=segments)
        for segment, style in zip(segments, classes, strict=True):
            span = max(segment.percent, MIN_SEGMENT_SPAN)
            block = Gtk.Box(hexpand=True)
            block.add_css_class("wimm-bar-segment")
            block.add_css_class(style)
            block.update_property([Gtk.AccessibleProperty.LABEL], [segment.legend])
            self._grid.attach(block, column, 0, span, 1)
            column += span
        if same_entries:
            for label, segment in zip(self._legend_labels, segments, strict=True):
                label.set_label(segment.legend)
        else:
            self._rebuild_legend(segments=segments, classes=classes)
        text = "; ".join(segment.legend for segment in segments)
        self._grid.update_property(
            [Gtk.AccessibleProperty.LABEL, Gtk.AccessibleProperty.DESCRIPTION], [_(BAR_LABEL), text]
        )

    def _rebuild_legend(self, *, segments: tuple[BarSegment, ...], classes: list[str]) -> None:
        self._legend.remove_all()
        self._legend_labels = []
        for segment, style in zip(segments, classes, strict=True):
            entry, label = _legend_entry(segment=segment, style=style)
            self._legend.append(entry)
            self._legend_labels.append(label)


def _legend_identity(*, segments: tuple[BarSegment, ...]) -> tuple[tuple[str, str], ...]:
    """What the legend widgets depend on beyond the sizes: same identity, same widgets.

    Sizes change every sample; rebuilding the entries then would destroy the help buttons
    and close an open help popover while the user reads it.
    """
    return tuple((segment.key, segment.help_question) for segment in segments)


def _legend_entry(*, segment: BarSegment, style: str) -> tuple[Gtk.Box, Gtk.Label]:
    swatch = Gtk.Box(valign=Gtk.Align.CENTER)
    swatch.add_css_class("wimm-swatch")
    swatch.add_css_class(style)
    label = Gtk.Label(label=segment.legend, xalign=0, wrap=True)
    label.add_css_class("caption")
    entry = Gtk.Box(spacing=SWATCH_SPACING)
    entry.append(swatch)
    entry.append(label)
    if segment.help_question:
        entry.append(help_button(question=segment.help_question, answer=segment.help_answer))
    return entry, label
