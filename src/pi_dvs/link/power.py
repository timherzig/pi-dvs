"""Keep a macOS Link session awake without changing system power settings."""

import ctypes
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def prevent_idle_sleep() -> Iterator[None]:
    # Linux appliance power policy is managed by the host. On macOS, the audio
    # plays on the CDJs, so no local audio driver holds an assertion for us.
    if sys.platform != "darwin":
        yield
        return

    cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    iokit = ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
    cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    cf.CFRelease.restype = None
    iokit.IOPMAssertionCreateWithName.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    iokit.IOPMAssertionCreateWithName.restype = ctypes.c_int
    iokit.IOPMAssertionRelease.argtypes = [ctypes.c_uint32]
    iokit.IOPMAssertionRelease.restype = ctypes.c_int
    assertion = ctypes.c_uint32()
    kind = cf.CFStringCreateWithCString(None, b"PreventUserIdleSystemSleep", 0x08000100)
    name = cf.CFStringCreateWithCString(None, b"pi-dvs Pro DJ Link", 0x08000100)
    try:
        if not kind or not name:
            raise OSError("Cannot allocate the Link idle-sleep assertion")
        result = iokit.IOPMAssertionCreateWithName(kind, 255, name, ctypes.byref(assertion))
        if result != 0:
            raise OSError(f"Cannot prevent idle sleep for Pro DJ Link (IOKit {result:#x})")
    finally:
        if kind:
            cf.CFRelease(kind)
        if name:
            cf.CFRelease(name)
    try:
        yield
    finally:
        # The OS also releases assertions if the owning application exits.
        result = iokit.IOPMAssertionRelease(assertion)
        if result != 0:
            logger.warning("Cannot release Link idle-sleep assertion: IOKit %#x", result)
