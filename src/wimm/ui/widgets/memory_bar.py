from gi.repository import Gtk

from wimm.ui.views import BarSegment

from . import clear_children

PALETTE_SIZE = 8
SPECIAL_CLASSES = {"kernel_cache": "cache", "unattributed": "unattributed", "free": "free"}
BAR_LABEL = "Memoria per categoria"
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
        self._segments = segments
        clear_children(container=self._grid)
        self._legend.remove_all()
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
            self._legend.append(_legend_entry(text=segment.legend, style=style))
        text = "; ".join(segment.legend for segment in segments)
        self._grid.update_property(
            [Gtk.AccessibleProperty.LABEL, Gtk.AccessibleProperty.DESCRIPTION], [BAR_LABEL, text]
        )


def _legend_entry(*, text: str, style: str) -> Gtk.Box:
    swatch = Gtk.Box(valign=Gtk.Align.CENTER)
    swatch.add_css_class("wimm-swatch")
    swatch.add_css_class(style)
    label = Gtk.Label(label=text, xalign=0, wrap=True)
    label.add_css_class("caption")
    entry = Gtk.Box(spacing=SWATCH_SPACING)
    entry.append(swatch)
    entry.append(label)
    return entry
