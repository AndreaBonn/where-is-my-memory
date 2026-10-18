"""Ask an X11 window to close the way a window manager does (WM_DELETE_WINDOW)."""

import ctypes

XLIB_NO_EVENT_MASK = 0
XLIB_CLIENT_MESSAGE = 33
XLIB_EVENT_LONGS = 24


class _ClientMessage(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", ctypes.c_long * 5),
    ]


class _XEvent(ctypes.Union):
    _fields_ = [("message", _ClientMessage), ("pad", ctypes.c_long * XLIB_EVENT_LONGS)]


def request_close(*, window: int) -> None:
    """Send WM_DELETE_WINDOW, what a window manager does on the close button."""
    xlib = ctypes.CDLL("libX11.so.6")
    xlib.XOpenDisplay.restype = ctypes.c_void_p
    xlib.XInternAtom.restype = ctypes.c_ulong
    display = xlib.XOpenDisplay(None)
    if not display:
        # A NULL display passed on to XInternAtom would crash the interpreter.
        raise RuntimeError("Cannot open the X display: is DISPLAY set?")
    protocols = xlib.XInternAtom(ctypes.c_void_p(display), b"WM_PROTOCOLS", False)
    delete = xlib.XInternAtom(ctypes.c_void_p(display), b"WM_DELETE_WINDOW", False)
    event = _XEvent()
    event.message = _ClientMessage(
        type=XLIB_CLIENT_MESSAGE,
        display=display,
        window=window,
        message_type=protocols,
        format=32,
        data=(ctypes.c_long * 5)(delete, 0, 0, 0, 0),
    )
    xlib.XSendEvent(
        ctypes.c_void_p(display),
        ctypes.c_ulong(window),
        False,
        ctypes.c_long(XLIB_NO_EVENT_MASK),
        ctypes.byref(event),
    )
    xlib.XFlush(ctypes.c_void_p(display))
    xlib.XCloseDisplay(ctypes.c_void_p(display))
