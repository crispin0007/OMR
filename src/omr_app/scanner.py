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
HANDLING_STATUS, HANDLING_SELECT, PAGES = "3087", "3088", "3096"
FEEDER, DUPLEX, FRONT_ONLY = 1, 4, 0x20
FEED_READY = 1
ITEM_NAME, ITEM_CATEGORY = "4098", "4125"
FEEDER_CATEGORY = "{FE131934-F84C-42AD-8DA4-6129CDDD7288}"  # a WIA 2.0 driver's feeder item
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
        self.one_side = False  # the last run asked for both sides and the driver wouldn't
        self.sure = True  # the driver took the feeder as the source

    def pages(self, dpi: int, duplex: bool) -> Iterator[np.ndarray]:
        """Each page from the feeder as a BGR image, until the feeder is empty.

        Raises ScanStopped on a jam, double feed or other scanner problem; pages already
        yielded are the caller's to keep.
        """
        import pythoncom  # pywin32, Windows only
        import pywintypes

        pythoncom.CoInitialize()  # this runs on the scan thread
        try:
            com_error = pywintypes.com_error
            try:
                device = self._info.Connect()
            except com_error as e:
                raise ScanStopped(f"Couldn't connect to {self.name}: {_problem(e)}") from e
            item, self.sure, self.one_side = _feeder(device, duplex, com_error)
            if item is None:
                raise ScanStopped(f"Couldn't set {self.name} to feed from the feeder. Scan with the scanner's own "
                                  f"program into a folder and read that folder instead{_reported(device, self.name)}")
            for target in (device, item):
                try:
                    target.Properties(PAGES).Value = 1
                except com_error:
                    pass  # drivers without it give one page per transfer anyway
            try:
                item.Properties(CURRENT_INTENT).Value = GRAYSCALE
            except com_error:
                pass  # colour pages are converted for reading
            self.dpi = _resolution(item, dpi, com_error)
            if not self.dpi:
                raise ScanStopped(f"{self.name} won't scan at {MIN_DPI} DPI or more through Windows. Scan with the "
                                  "scanner's own program into a folder and read that folder instead")
            first, last = True, None
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
                if not self.sure and last is not None and _same(page, last):
                    # The driver didn't say the feeder was picked and the same page came twice: it is scanning
                    # the glass, which never runs out.
                    raise ScanStopped(f"{self.name} scanned the same page twice, so it seems to be scanning the "
                                      "glass, not the feeder. Scan with the scanner's own program into a folder and "
                                      "read that folder instead")
                last = page
                yield page
                if not self.sure and _status(device, com_error) == 0:
                    return  # the driver says the feeder is empty
        finally:
            pythoncom.CoUninitialize()


def _feeder(device, duplex: bool, com_error):
    """(the item to scan from, whether the feeder is surely the source, whether only one side will come) set up
    for the feeder, or (None, ...) when nothing would take.

    Drivers differ: older (WIA 1) ones pick the feeder with a property on the device; newer (WIA 2) ones have a
    separate item for the feeder, and some refuse the device property with a plain "failed" (0x80004005). Each
    way is tried in turn."""
    items = []
    try:
        items = [device.Items(i) for i in range(1, device.Items.Count + 1)]
    except (com_error, AttributeError, TypeError):
        try:
            items = [device.Items(1)]
        except com_error:
            return None, False, False
    feeder = next((i for i in items if _is_feeder(i)), None)
    if feeder is not None:
        # The feeder item is the feeder; on it the setting only says which sides.
        if not duplex:
            return feeder, True, False
        for target, value in ((feeder, DUPLEX), (device, FEEDER | DUPLEX)):
            try:
                target.Properties(HANDLING_SELECT).Value = value
                return feeder, True, False
            except com_error:
                continue
        return feeder, True, True
    item = items[0] if items else None
    if item is None:
        return None, False, False
    for value, one_side in (((FEEDER | DUPLEX, False), (FEEDER, True)) if duplex else ((FEEDER, False),)):
        for target in (device, item):
            try:
                target.Properties(HANDLING_SELECT).Value = value
                return item, True, one_side
            except com_error:
                continue
    # Nothing took: scan from the source the driver is set to, and watch for it being the glass.
    return item, False, duplex


def _is_feeder(item) -> bool:
    for key, test in ((ITEM_CATEGORY, lambda v: str(v).upper() == FEEDER_CATEGORY),
                      (ITEM_NAME, lambda v: any(w in str(v).lower() for w in ("feeder", "adf")))):
        try:
            if test(item.Properties(key).Value):
                return True
        except Exception:  # noqa: BLE001 - a driver without the property
            continue
    return False


def _status(device, com_error) -> int | None:
    """FEED_READY when the driver says the feeder has paper, 0 when it says it's empty, None when it doesn't say."""
    try:
        return int(device.Properties(HANDLING_STATUS).Value) & FEED_READY
    except (com_error, TypeError, ValueError):
        return None


def _same(a: np.ndarray, b: np.ndarray) -> bool:
    return a.shape == b.shape and float(cv2.absdiff(a, b).mean()) < 2


def report(device) -> str:
    """What a driver offers, item by item, as text a person can send when a scanner won't feed."""
    lines = []
    for label, target in [("Device", device)] + [(f"Item {i}", device.Items(i))
                                                  for i in range(1, _count(device) + 1)]:
        lines.append(label)
        try:
            props = list(target.Properties)
        except Exception:  # noqa: BLE001
            lines.append("  (can't list its settings)")
            continue
        for p in props:
            try:
                allowed = ""
                if p.SubType == LIST:
                    allowed = f" one of {[p.SubTypeValues.Item(i) for i in range(1, p.SubTypeValues.Count + 1)]}"
                elif p.SubType == RANGE:
                    allowed = f" from {p.SubTypeMin} to {p.SubTypeMax}"
                lines.append(f"  {p.PropertyID} {p.Name} = {p.Value}{allowed}{' (read only)' if p.IsReadOnly else ''}")
            except Exception:  # noqa: BLE001
                continue
    return "\n".join(lines)


def _count(device) -> int:
    try:
        return int(device.Items.Count)
    except Exception:  # noqa: BLE001
        return 0


def _reported(device, name: str) -> str:
    """Save what the driver offers to a file, and say where; "" when it can't be saved."""
    from .paths import data_dir

    try:
        path = data_dir() / "scanner-details.txt"
        path.write_text(f"{name}\n\n{report(device)}\n", encoding="utf-8")
    except Exception:  # noqa: BLE001 - the report is a help, never a reason to fail differently
        return ""
    return f". What the scanner offers is saved in {path}"


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
