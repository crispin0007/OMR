"""Scanners through TWAIN, for scanners whose driver has no WIA side or whose WIA side won't feed.

Written here from the public TWAIN specification (the TWAIN Working Group's), talking to the TWAIN data
source manager (TWAINDSM.dll) with ctypes; pytwain is GPL and can't ship in the Apache-2.0 app. Windows only,
and only 64-bit TWAIN drivers can be used from the 64-bit app.

A TWAIN source talks to the program through window messages, so the scan thread makes a hidden window, pumps
its messages and hands each to the source until it says a page is ready; the page comes back as a device-
independent bitmap (a native transfer), which every source supports.
"""

import ctypes
import struct
import sys
import time
from collections.abc import Iterator

import cv2
import numpy as np

from .scanner import FEEDER_EMPTY_TEXT, MIN_DPI, ScanStopped

# From the TWAIN specification: groups, data types, messages, return and condition codes, capabilities.
DG_CONTROL, DG_IMAGE = 0x0001, 0x0002
DAT_CAPABILITY, DAT_EVENT, DAT_IDENTITY, DAT_PARENT, DAT_PENDINGXFERS = 0x0001, 0x0002, 0x0003, 0x0004, 0x0005
DAT_STATUS, DAT_USERINTERFACE, DAT_IMAGENATIVEXFER = 0x0008, 0x0009, 0x0104
MSG_GET, MSG_GETCURRENT, MSG_GETFIRST, MSG_GETNEXT, MSG_SET = 0x0001, 0x0002, 0x0004, 0x0005, 0x0006
MSG_XFERREADY, MSG_CLOSEDSREQ, MSG_CLOSEDSOK = 0x0101, 0x0102, 0x0103
MSG_OPENDSM, MSG_CLOSEDSM, MSG_OPENDS, MSG_CLOSEDS = 0x0301, 0x0302, 0x0401, 0x0402
MSG_DISABLEDS, MSG_ENABLEDS, MSG_PROCESSEVENT, MSG_ENDXFER, MSG_RESET = 0x0501, 0x0502, 0x0601, 0x0701, 0x0007
TWRC_SUCCESS, TWRC_FAILURE, TWRC_CHECKSTATUS, TWRC_CANCEL, TWRC_DSEVENT = 0, 1, 2, 3, 4
TWRC_NOTDSEVENT, TWRC_XFERDONE, TWRC_ENDOFLIST = 5, 6, 7
TWCC_PAPERJAM, TWCC_PAPERDOUBLEFEED, TWCC_CHECKDEVICEONLINE, TWCC_NODS, TWCC_DENIED = 20, 21, 23, 3, 16
CAP_XFERCOUNT, ICAP_PIXELTYPE, ICAP_XRESOLUTION, ICAP_YRESOLUTION = 0x0001, 0x0101, 0x1118, 0x1119
CAP_FEEDERENABLED, CAP_FEEDERLOADED, CAP_AUTOFEED, CAP_INDICATORS, CAP_DUPLEXENABLED = (0x1002, 0x1003, 0x1007,
                                                                                       0x100B, 0x1013)
TWTY_INT16, TWTY_UINT16, TWTY_BOOL, TWTY_FIX32 = 0x0001, 0x0004, 0x0006, 0x0007
TWON_ONEVALUE, TWON_DONTCARE16 = 0x0005, 0xFFFF
TWPT_GRAY = 1
SOURCE_TIMEOUT = 60  # seconds to wait for the source to send the first page before giving up

PROBLEMS = {TWCC_PAPERJAM: "Paper jam", TWCC_PAPERDOUBLEFEED: "Two sheets fed together",
            TWCC_CHECKDEVICEONLINE: "The scanner is off or unplugged",
            TWCC_DENIED: "The scanner is busy with another program"}


class TW_VERSION(ctypes.Structure):
    _pack_ = 2
    _fields_ = [("MajorNum", ctypes.c_uint16), ("MinorNum", ctypes.c_uint16), ("Language", ctypes.c_uint16),
                ("Country", ctypes.c_uint16), ("Info", ctypes.c_char * 34)]


class TW_IDENTITY(ctypes.Structure):
    _pack_ = 2
    _fields_ = [("Id", ctypes.c_uint32), ("Version", TW_VERSION), ("ProtocolMajor", ctypes.c_uint16),
                ("ProtocolMinor", ctypes.c_uint16), ("SupportedGroups", ctypes.c_uint32),
                ("Manufacturer", ctypes.c_char * 34), ("ProductFamily", ctypes.c_char * 34),
                ("ProductName", ctypes.c_char * 34)]


class TW_USERINTERFACE(ctypes.Structure):
    _pack_ = 2
    _fields_ = [("ShowUI", ctypes.c_uint16), ("ModalUI", ctypes.c_uint16), ("hParent", ctypes.c_void_p)]


class TW_PENDINGXFERS(ctypes.Structure):
    _pack_ = 2
    _fields_ = [("Count", ctypes.c_uint16), ("EOJ", ctypes.c_uint32)]


class TW_EVENT(ctypes.Structure):
    _pack_ = 2
    _fields_ = [("pEvent", ctypes.c_void_p), ("TWMessage", ctypes.c_uint16)]


class TW_CAPABILITY(ctypes.Structure):
    _pack_ = 2
    _fields_ = [("Cap", ctypes.c_uint16), ("ConType", ctypes.c_uint16), ("hContainer", ctypes.c_void_p)]


class TW_STATUS(ctypes.Structure):
    _pack_ = 2
    _fields_ = [("ConditionCode", ctypes.c_uint16), ("Reserved", ctypes.c_uint16)]


ONEVALUE = struct.Struct("<HI")  # TW_ONEVALUE: ItemType, Item; packed to 2 bytes as TWAIN is


def app_identity() -> TW_IDENTITY:
    me = TW_IDENTITY()
    me.Version.MajorNum, me.Version.MinorNum = 1, 0
    me.Version.Language, me.Version.Country = 2, 1  # English, USA: the language the source's messages use
    me.Version.Info = b"OMR Checker"
    me.ProtocolMajor, me.ProtocolMinor = 1, 9
    me.SupportedGroups = DG_CONTROL | DG_IMAGE
    me.Manufacturer, me.ProductFamily, me.ProductName = b"OMR Checker", b"OMR Checker", b"OMR Checker"
    return me


def fix32(value: float) -> int:
    """A number as TWAIN's fixed point (whole part, then 1/65536ths), as the 32 bits of a TW_ONEVALUE item."""
    v = int(round(value * 65536))  # 16.16 two's complement: -1.5 is whole -2 and half
    return ((v & 0xFFFF) << 16) | ((v >> 16) & 0xFFFF)


def from_fix32(item: int) -> float:
    whole = item & 0xFFFF
    return (whole - 0x10000 if whole & 0x8000 else whole) + (item >> 16) / 65536


def dib_to_image(dib: bytes) -> np.ndarray | None:
    """A device-independent bitmap (what a native transfer gives) as a BGR image; None when it isn't one."""
    if len(dib) < 40:
        return None
    (header,), (bits,) = struct.unpack_from("<I", dib, 0), struct.unpack_from("<H", dib, 14)
    (compression,), (colours,) = struct.unpack_from("<I", dib, 16), struct.unpack_from("<I", dib, 32)
    palette = (colours or (1 << bits if bits <= 8 else 0)) * 4 + (12 if compression == 3 and header == 40 else 0)
    offset = 14 + header + palette
    bmp = b"BM" + struct.pack("<IHHI", 14 + len(dib), 0, 0, offset) + dib
    return cv2.imdecode(np.frombuffer(bmp, np.uint8), cv2.IMREAD_COLOR)


class Session:
    """One conversation with the data source manager and, once opened, one source. `call` is DSM_Entry with the
    app's identity filled in; `win` does the Windows side (window, messages, global memory)."""

    def __init__(self, call, win):
        self.call, self.win = call, win
        self.source: TW_IDENTITY | None = None

    def status(self) -> int:
        s = TW_STATUS()
        self.call(self.source, DG_CONTROL, DAT_STATUS, MSG_GET, s)
        return s.ConditionCode

    def problem(self, what: str) -> str:
        code = self.status()
        return PROBLEMS.get(code, f"{what} (TWAIN condition {code})")

    def sources(self) -> list[TW_IDENTITY]:
        found, msg = [], MSG_GETFIRST
        while True:
            ident = TW_IDENTITY()
            if self.call(None, DG_CONTROL, DAT_IDENTITY, msg, ident) != TWRC_SUCCESS:
                return found
            found.append(ident)
            msg = MSG_GETNEXT

    def set_cap(self, cap: int, kind: int, item: int) -> bool:
        handle = self.win.alloc(ONEVALUE.pack(kind, item & 0xFFFFFFFF))
        try:
            c = TW_CAPABILITY(cap, TWON_ONEVALUE, handle)
            return self.call(self.source, DG_CONTROL, DAT_CAPABILITY, MSG_SET, c) == TWRC_SUCCESS
        finally:
            self.win.free(handle)

    def get_cap(self, cap: int) -> int | None:
        """A capability's current value when the source gives it as one value; None when it doesn't."""
        c = TW_CAPABILITY(cap, TWON_DONTCARE16, None)
        if self.call(self.source, DG_CONTROL, DAT_CAPABILITY, MSG_GETCURRENT, c) != TWRC_SUCCESS:
            return None
        try:
            if c.ConType != TWON_ONEVALUE or not c.hContainer:
                return None
            return ONEVALUE.unpack_from(self.win.read(c.hContainer, ONEVALUE.size))[1]
        finally:
            if c.hContainer:
                self.win.free(c.hContainer)


def resolution(session: Session, dpi: int) -> int:
    """Set the resolution: `dpi` if the source takes it, else the nearest usual one from MIN_DPI; else what it is
    set to already if that's enough. 0 when nothing will do."""
    for v in sorted({dpi, 200, 300, 150, 240, 400}, key=lambda v: (v != dpi, abs(v - dpi), -v)):
        if session.set_cap(ICAP_XRESOLUTION, TWTY_FIX32, fix32(v)) and \
                session.set_cap(ICAP_YRESOLUTION, TWTY_FIX32, fix32(v)):
            return v
    current = session.get_cap(ICAP_XRESOLUTION)
    current = round(from_fix32(current)) if current is not None else 0
    return current if current >= MIN_DPI else 0


class TwainScanner:
    def __init__(self, name: str, product: bytes, call_factory=None, win_factory=None):
        self.name = name
        self.product = product  # the source's ProductName: what opens it again
        self.dpi = 0
        self.one_side = False
        self.sure = True
        self._call = call_factory or _dsm_call
        self._win = win_factory or _Windows

    def pages(self, dpi: int, duplex: bool) -> Iterator[np.ndarray]:
        """Each page from the feeder as a BGR image, until the feeder is empty; raises ScanStopped as the WIA
        scanner does."""
        call = self._call()
        if call is None:
            raise ScanStopped("TWAIN isn't installed on this PC (TWAINDSM.dll). Use the scanner's WIA entry, or "
                              "scan with its own program into a folder")
        win = self._win()
        s = Session(call, win)
        parent = ctypes.c_void_p(win.window())
        if call(None, DG_CONTROL, DAT_PARENT, MSG_OPENDSM, parent) != TWRC_SUCCESS:
            win.close()
            raise ScanStopped("Couldn't start TWAIN on this PC")
        try:
            source = TW_IDENTITY()
            source.ProductName = self.product
            if call(None, DG_CONTROL, DAT_IDENTITY, MSG_OPENDS, source) != TWRC_SUCCESS:
                raise ScanStopped(f"Couldn't open {self.name}: {s.problem('it refused')}. Close the scanner's own "
                                  "program, then press Start scanning again")
            s.source = source
            try:
                yield from self._run(s, parent, dpi, duplex)
            finally:
                call(source, DG_CONTROL, DAT_IDENTITY, MSG_CLOSEDS, source)
        finally:
            call(None, DG_CONTROL, DAT_PARENT, MSG_CLOSEDSM, parent)
            win.close()

    def _run(self, s: Session, parent, dpi: int, duplex: bool) -> Iterator[np.ndarray]:
        s.set_cap(CAP_XFERCOUNT, TWTY_INT16, -1)  # every page in the feeder
        s.set_cap(ICAP_PIXELTYPE, TWTY_UINT16, TWPT_GRAY)  # colour pages are converted for reading anyway
        s.set_cap(CAP_INDICATORS, TWTY_BOOL, 0)  # no progress window of the source's own
        self.sure = s.set_cap(CAP_FEEDERENABLED, TWTY_BOOL, 1)
        s.set_cap(CAP_AUTOFEED, TWTY_BOOL, 1)
        self.one_side = duplex and not s.set_cap(CAP_DUPLEXENABLED, TWTY_BOOL, 1)
        if not duplex:
            s.set_cap(CAP_DUPLEXENABLED, TWTY_BOOL, 0)
        self.dpi = resolution(s, dpi)
        if not self.dpi:
            raise ScanStopped(f"{self.name} won't scan at {MIN_DPI} DPI or more through TWAIN. Scan with the "
                              "scanner's own program into a folder and read that folder instead")
        if s.get_cap(CAP_FEEDERLOADED) == 0:
            raise ScanStopped(FEEDER_EMPTY_TEXT)
        ui = TW_USERINTERFACE(0, 0, parent.value)
        if s.call(s.source, DG_CONTROL, DAT_USERINTERFACE, MSG_ENABLEDS, ui) not in (TWRC_SUCCESS,
                                                                                    TWRC_CHECKSTATUS):
            raise ScanStopped(f"{self.name} wouldn't start: {s.problem('it refused')}")
        try:
            yield from self._transfers(s)
        finally:
            # Stopped mid-batch: drop the pages the source still holds, so it can be closed.
            s.call(s.source, DG_CONTROL, DAT_PENDINGXFERS, MSG_RESET, TW_PENDINGXFERS())
            s.call(s.source, DG_CONTROL, DAT_USERINTERFACE, MSG_DISABLEDS, ui)

    def _transfers(self, s: Session) -> Iterator[np.ndarray]:
        """Wait for the source to say pages are ready, then take them one by one until none are pending."""
        waited = time.monotonic()
        while True:
            message = s.win.next_message()
            if message is None:
                if time.monotonic() - waited > SOURCE_TIMEOUT:
                    raise ScanStopped(f"{self.name} didn't start scanning. Check the paper is in the feeder, then "
                                      "press Start scanning again")
                continue
            event = TW_EVENT(message, 0)
            if s.call(s.source, DG_CONTROL, DAT_EVENT, MSG_PROCESSEVENT, event) != TWRC_DSEVENT:
                s.win.dispatch(message)
                continue
            if event.TWMessage in (MSG_CLOSEDSREQ, MSG_CLOSEDSOK):
                return  # the source's own Cancel, or it is done
            if event.TWMessage != MSG_XFERREADY:
                continue
            while True:
                handle = ctypes.c_void_p()
                rc = s.call(s.source, DG_IMAGE, DAT_IMAGENATIVEXFER, MSG_GET, handle)
                if rc == TWRC_CANCEL:
                    return
                if rc != TWRC_XFERDONE:
                    raise ScanStopped(s.problem("the page didn't come through"))
                try:
                    page = dib_to_image(s.win.read(handle.value))
                finally:
                    s.win.free(handle.value)
                pending = TW_PENDINGXFERS()
                s.call(s.source, DG_CONTROL, DAT_PENDINGXFERS, MSG_ENDXFER, pending)
                if page is None:
                    raise ScanStopped("The scanner sent a page that isn't an image")
                yield page
                if pending.Count == 0:
                    return  # the feeder is empty


def scanners() -> list[TwainScanner]:
    """The TWAIN sources on this PC; none off Windows or without a 64-bit TWAIN data source manager."""
    if sys.platform != "win32":
        return []
    call = _dsm_call()
    if call is None:
        return []
    win = _Windows()
    parent = ctypes.c_void_p(win.window())
    try:
        if call(None, DG_CONTROL, DAT_PARENT, MSG_OPENDSM, parent) != TWRC_SUCCESS:
            return []
        try:
            found = Session(call, win).sources()
        finally:
            call(None, DG_CONTROL, DAT_PARENT, MSG_CLOSEDSM, parent)
    except OSError:
        return []
    finally:
        win.close()
    return [TwainScanner(f"{i.ProductName.decode('mbcs', 'replace')} (TWAIN)", bytes(i.ProductName)) for i in found]


def _dsm_call():
    """DSM_Entry with this app's identity, as call(dest, group, data type, message, data) -> return code; None
    when there is no TWAIN data source manager."""
    try:
        entry = ctypes.WinDLL("TWAINDSM.dll").DSM_Entry
    except (OSError, AttributeError):
        return None
    entry.restype = ctypes.c_uint16
    entry.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint16, ctypes.c_uint16,
                      ctypes.c_void_p]
    me = app_identity()

    def call(dest, group, dat, msg, data):
        return entry(ctypes.byref(me), ctypes.byref(dest) if dest is not None else None, group, dat, msg,
                     ctypes.byref(data) if data is not None else None)
    return call


class _Windows:
    """The Windows side of TWAIN: a hidden window for the source to post to, its messages, and global memory."""

    def __init__(self):
        from ctypes import wintypes
        self.user32, self.kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        self.user32.CreateWindowExW.restype = wintypes.HWND
        self.user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                                wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        self.user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT,
                                             wintypes.UINT, wintypes.UINT]
        for f in ("TranslateMessage", "DispatchMessageW"):
            getattr(self.user32, f).argtypes = [ctypes.POINTER(wintypes.MSG)]
        self.kernel32.GlobalAlloc.restype = ctypes.c_void_p
        self.kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        for f in ("GlobalLock", "GlobalFree", "GlobalUnlock", "GlobalSize"):
            getattr(self.kernel32, f).argtypes = [ctypes.c_void_p]
        self.kernel32.GlobalLock.restype = ctypes.c_void_p
        self.kernel32.GlobalSize.restype = ctypes.c_size_t
        self.msg = wintypes.MSG()
        self.hwnd = self.user32.CreateWindowExW(0, "STATIC", "OMR Checker TWAIN", 0, 0, 0, 0, 0, None, None, None,
                                                None)

    def window(self) -> int:
        return self.hwnd or 0

    def next_message(self):
        """A pointer to the next window message of this thread, or None (after a short wait) when there is none."""
        if self.user32.PeekMessageW(ctypes.byref(self.msg), None, 0, 0, 1):  # PM_REMOVE
            return ctypes.addressof(self.msg)
        time.sleep(0.01)
        return None

    def dispatch(self, _message):
        self.user32.TranslateMessage(ctypes.byref(self.msg))
        self.user32.DispatchMessageW(ctypes.byref(self.msg))

    def alloc(self, data: bytes) -> int:
        handle = self.kernel32.GlobalAlloc(0x0042, len(data))  # GHND: movable, zeroed
        if not handle:
            raise MemoryError("no memory for a TWAIN setting")
        ctypes.memmove(self.kernel32.GlobalLock(handle), data, len(data))
        self.kernel32.GlobalUnlock(handle)
        return handle

    def read(self, handle: int, size: int | None = None) -> bytes:
        size = size or self.kernel32.GlobalSize(handle)
        try:
            return ctypes.string_at(self.kernel32.GlobalLock(handle), size)
        finally:
            self.kernel32.GlobalUnlock(handle)

    def free(self, handle: int):
        self.kernel32.GlobalFree(handle)

    def close(self):
        if self.hwnd:
            self.user32.DestroyWindow(self.hwnd)
            self.hwnd = None
