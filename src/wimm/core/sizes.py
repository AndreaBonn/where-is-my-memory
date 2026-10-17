"""Byte counts as Italian text, shared by the UI, the tray and the notifications."""

import math

SI_UNITS = ("B", "kB", "MB", "GB", "TB")
SI_BASE = 1000
FIRST_DECIMAL_UNIT = 3


def _scaled(*, size: int, index: int) -> tuple[int, int]:
    """Return ``size`` in unit ``index`` rounded half up, as an integer, with its decimal scale."""
    scale = 10 if index >= FIRST_DECIMAL_UNIT else 1
    divisor = SI_BASE**index
    return (2 * size * scale + divisor) // (2 * divisor), scale


def format_size(*, size: int) -> str:
    """Format a byte count in SI units with the Italian decimal comma.

    Below 1 GB no decimals are shown, from 1 GB on one decimal. Integer
    arithmetic keeps the result independent of locale and float rounding.

    Parameters
    ----------
    size : int
        Non-negative number of bytes.

    Returns
    -------
    str
        For example ``"980 MB"`` or ``"1,1 GB"``.
    """
    if not math.isfinite(size) or size < 0:
        raise ValueError(f"size must be a finite non-negative byte count, got {size!r}")
    last = len(SI_UNITS) - 1
    index = 0
    scaled, scale = _scaled(size=size, index=index)
    while scaled >= SI_BASE * scale and index < last:
        index += 1
        scaled, scale = _scaled(size=size, index=index)
    whole, fraction = divmod(scaled, scale)
    unit = SI_UNITS[index]
    return f"{whole},{fraction} {unit}" if scale > 1 else f"{whole} {unit}"
