"""Scanners through Windows Image Acquisition (WIA), one page at a time from the feeder (US4).

WIA is built into Windows and most document scanners ship a WIA driver. pytwain
was the first plan, but it is GPL-2.0, which the Apache-2.0 app can't ship.
Scanners without a WIA driver use the watched-folder source on the Scan page
with the scanner's own software saving into that folder.
"""

import sys
from collections.abc import Iterator

import cv2
import numpy as np

BMP = "{B96B3CAB-0728-11D3-9D7B-0000F81EF32E}"
SCANNER = 1  # WiaDeviceType
# Item and device property ids, from Microsoft's WIA documentation.
CURRENT_INTENT, X_RES, Y_RES = "6146", "6147", "6148"
GRAYSCALE = 2
HANDLING_SELECT, PAGES = "3088", "3096"
FEEDER, DUPLEX = 1, 4
RANGE, LIST = 1, 2  # WiaSubType of a property's allowed values
MIN_DPI = 150  # below this, bubbles are too few pixels to read
PAPER_EMPTY = 0x80210003
# What the operator should do for each WIA error that stops a run.
PROBLEMS = {
    0x80210002: "Paper jam",
    0x80210004: "Paper problem (a sheet fed badly)",
    0x80210020: "Two sheets fed together",
    0x80210016: "The scanner cover is open",
    0x80210005: "The scanner is off or unplugged",
    0x80210006: "The scanner is busy with another program",
    0x8021000A: "Lost the connection to the scanner",
}


class ScanStopped(Exception):
    """The scanner stopped the run before the feeder was empty; the message says why."""


class WiaScanner:
    def __init__(self, name: str, info):
        self.name = name
        self._info = info
        self.dpi = 0  # what the last run scanned at, which may not be what was asked for

    def pages(self, dpi: int, duplex: bool) -> Iterator[np.ndarray]:
        """Each page from the feeder as a BGR image, until the feeder is empty.

        Raises ScanStopped on a jam, double feed or other scanner problem; pages already
        yielded are the caller's to keep.
        """
        import pythoncom  # pywin32, Windows only
        import pywintypes

        pythoncom.CoInitialize()  # this runs on the scan thread
        try:
            try:
                device = self._info.Connect()
                device.Properties(HANDLING_SELECT).Value = FEEDER | (DUPLEX if duplex else 0)
                try:
                    device.Properties(PAGES).Value = 1
                except pywintypes.com_error:
                    pass  # drivers without it give one page per transfer anyway
                item = device.Items(1)
                try:
                    item.Properties(CURRENT_INTENT).Value = GRAYSCALE
                except pywintypes.com_error:
                    pass  # colour pages are converted for reading
            except pywintypes.com_error as e:
                raise ScanStopped(f"Couldn't set {self.name} to feed {'both sides ' if duplex else ''}from the "
                                  f"feeder: {_problem(e)}. Scan with the scanner's own program into a folder and "
                                  "read that folder instead") from e
            self.dpi = _resolution(item, dpi, pywintypes.com_error)
            if not self.dpi:
                raise ScanStopped(f"{self.name} won't scan at {MIN_DPI} DPI or more through Windows. Scan with the "
                                  "scanner's own program into a folder and read that folder instead")
            first = True
            while True:
                try:
                    image = item.Transfer(BMP)
                except pywintypes.com_error as e:
                    if _code(e) == PAPER_EMPTY:
                        if first:
                            raise ScanStopped("The feeder is empty. Put the sheets on the feeder and press Start scanning.") from e
                        return
                    raise ScanStopped(_problem(e)) from e
                first = False
                data = np.frombuffer(bytes(image.FileData.BinaryData), np.uint8)
                page = cv2.imdecode(data, cv2.IMREAD_COLOR)
                if page is None:
                    raise ScanStopped("The scanner sent a page that isn't an image")
                yield page
        finally:
            pythoncom.CoUninitialize()


def _allowed(prop) -> list[int]:
    """The resolutions a driver says it takes, nearest first to 200; [] when it doesn't say."""
    try:
        if prop.SubType == LIST:
            values = [int(prop.SubTypeValues.Item(i)) for i in range(1, prop.SubTypeValues.Count + 1)]
        elif prop.SubType == RANGE:
            lo, hi, step = int(prop.SubTypeMin), int(prop.SubTypeMax), max(1, int(prop.SubTypeStep))
            values = [v for v in (150, 200, 240, 300, 400, 600) if lo <= v <= hi and (v - lo) % step == 0]
        else:
            return []
    except Exception:  # noqa: BLE001 - a driver that can't say is asked for the usual ones instead
        return []
    return [v for v in values if v >= MIN_DPI]


def _resolution(item, dpi: int, com_error) -> int:
    """Set the scan resolution: `dpi` if the driver takes it, else the nearest it does (any from 150 DPI reads
    the same), else whatever it is set to already if that's enough. 0 when nothing will do."""
    x, y = item.Properties(X_RES), item.Properties(Y_RES)
    allowed = _allowed(x)
    tries = sorted(set(allowed) or {dpi, 200, 300, 150, 240, 400}, key=lambda v: (v != dpi, abs(v - dpi), -v))
    for v in tries:
        try:
            x.Value = v
            y.Value = v
            return v
        except com_error:
            continue
    try:
        current = int(x.Value)
    except (com_error, TypeError, ValueError):
        return 0
    return current if current >= MIN_DPI else 0


def scanners() -> list[WiaScanner]:
    """The WIA scanners Windows knows about; none off Windows or when WIA isn't available."""
    if sys.platform != "win32":
        return []
    try:
        import win32com.client
        import pywintypes
    except ImportError:
        return []
    try:
        infos = win32com.client.Dispatch("WIA.DeviceManager").DeviceInfos
        return [WiaScanner(i.Properties("Name").Value, i) for i in infos if i.Type == SCANNER]
    except pywintypes.com_error:
        return []


def _code(e) -> int:
    """The WIA error code inside a COM error, as an unsigned number."""
    excepinfo = e.excepinfo if len(e.args) > 2 else None
    code = excepinfo[5] if excepinfo and excepinfo[5] else e.hresult
    return code & 0xFFFFFFFF


def _problem(e) -> str:
    return PROBLEMS.get(_code(e), f"Scanner error {_code(e):#x}")
