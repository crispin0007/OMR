"""The WIA scanner loop, with fake COM objects standing in for Windows."""

import sys
import types

import cv2
import numpy as np
import pytest

pytest.importorskip("PySide6")

from omr_app import scanner  # noqa: E402


class ComError(Exception):
    def __init__(self, code):
        super().__init__(-2147352567, "Exception occurred.", (0, None, None, None, 0, code), None)
        self.hresult, self.excepinfo = -2147352567, self.args[2]


@pytest.fixture(autouse=True)
def fake_com(monkeypatch):
    monkeypatch.setitem(sys.modules, "pythoncom", types.SimpleNamespace(CoInitialize=lambda: None,
                                                                         CoUninitialize=lambda: None))
    monkeypatch.setitem(sys.modules, "pywintypes", types.SimpleNamespace(com_error=ComError))


class Props(dict):
    def __call__(self, key):
        if key not in self:
            raise ComError(0x80210001)
        return self[key]


class Refuses(types.SimpleNamespace):
    """A setting the driver fails on with a plain "failed" (0x80004005), as some WIA 2 drivers do."""

    @property
    def Value(self):  # noqa: N802 - COM's name
        return 0

    @Value.setter
    def Value(self, v):  # noqa: N802
        raise ComError(0x80004005)


class Device:
    def __init__(self, transfers, props=(scanner.HANDLING_SELECT, scanner.PAGES), items=None):
        self.Properties = Props({k: types.SimpleNamespace(Value=0) for k in props})
        self.items = items or [{}]
        for i in self.items:  # each item: its own properties, and pages from this device
            i.setdefault(scanner.X_RES, types.SimpleNamespace(Value=0))
            i.setdefault(scanner.Y_RES, types.SimpleNamespace(Value=0))
        self.items = [types.SimpleNamespace(Properties=Props(i), Transfer=self.next) for i in self.items]
        self.item = self.items[0]
        self.Items = Items(self.items)
        self.transfers = list(transfers)

    def next(self, fmt):
        assert fmt == scanner.BMP
        t = self.transfers.pop(0)
        if isinstance(t, int):
            raise ComError(t)
        data = cv2.imencode(".bmp", t)[1].tobytes()
        return types.SimpleNamespace(FileData=types.SimpleNamespace(BinaryData=data))


class Items:
    def __init__(self, items):
        self.items, self.Count = items, len(items)

    def __call__(self, n):
        return self.items[n - 1]


def wia(device):
    return scanner.WiaScanner("Test", types.SimpleNamespace(Connect=lambda: device))


def test_feeds_until_empty_and_sets_up_the_scanner():
    page = np.full((50, 40, 3), 200, np.uint8)
    d = Device([page, page, scanner.PAPER_EMPTY])
    assert len(list(wia(d).pages(200, True))) == 2
    assert d.Properties(scanner.HANDLING_SELECT).Value == scanner.FEEDER | scanner.DUPLEX
    assert d.item.Properties(scanner.X_RES).Value == 200  # no intent setting on this driver: still scans


@pytest.mark.parametrize("transfers, message", [
    ([scanner.PAPER_EMPTY], "The feeder is empty"),
    ([np.zeros((5, 5, 3), np.uint8), 0x80210002], "Paper jam"),
    ([0x80210020], "Two sheets fed together"),
    ([0x8021FFFF], "Scanner error 0x8021ffff"),
])
def test_problems_stop_the_run(transfers, message):
    got = []
    with pytest.raises(scanner.ScanStopped, match=message):
        for p in wia(Device(transfers)).pages(200, False):
            got.append(p)
    assert len(got) == sum(isinstance(t, np.ndarray) for t in transfers)


def test_a_scanner_without_items_says_to_use_a_folder(monkeypatch, tmp_path):
    monkeypatch.setattr("omr_app.paths.data_dir", lambda: tmp_path)
    d = Device([])
    d.Items = Items([])
    with pytest.raises(scanner.ScanStopped, match="Couldn.t set Test to feed from the feeder.*into a folder"):
        list(wia(d).pages(200, False))
    assert (tmp_path / "scanner-details.txt").read_text(encoding="utf-8").startswith("Test")


def test_a_driver_with_a_feeder_item_scans_from_it():
    page = np.full((50, 40, 3), 200, np.uint8)
    flatbed = {scanner.ITEM_NAME: types.SimpleNamespace(Value="Flatbed")}
    feeder = {scanner.ITEM_CATEGORY: types.SimpleNamespace(Value=scanner.FEEDER_CATEGORY.lower()),
              scanner.HANDLING_SELECT: types.SimpleNamespace(Value=scanner.FRONT_ONLY)}
    d = Device([page, page * 0, scanner.PAPER_EMPTY], props=(), items=[flatbed, feeder])
    d.Properties[scanner.HANDLING_SELECT] = Refuses()  # the device-wide setting fails, as on the reported driver
    d.items[0].Transfer = lambda fmt: pytest.fail("scanned the glass")
    s = wia(d)
    assert len(list(s.pages(200, True))) == 2 and not s.one_side
    assert d.items[1].Properties(scanner.HANDLING_SELECT).Value == scanner.DUPLEX


def test_a_feeder_only_on_one_side_still_scans():
    page = np.full((50, 40, 3), 200, np.uint8)
    d = Device([page, scanner.PAPER_EMPTY], props=())
    d.Properties[scanner.HANDLING_SELECT] = Select({scanner.FEEDER})
    s = wia(d)
    assert len(list(s.pages(200, True))) == 1 and s.one_side
    assert d.Properties(scanner.HANDLING_SELECT).Value == scanner.FEEDER


def test_a_driver_that_takes_no_source_scans_until_it_says_empty_or_repeats():
    a, b = np.full((50, 40, 3), 200, np.uint8), np.full((50, 40, 3), 90, np.uint8)
    d = Device([a, b, a], props=(scanner.HANDLING_STATUS,))
    d.Properties[scanner.HANDLING_SELECT] = Refuses()
    d.Properties[scanner.HANDLING_STATUS].Value = scanner.FEED_READY
    got = []
    for p in wia(d).pages(200, False):
        got.append(p)
        if len(got) == 2:
            d.Properties[scanner.HANDLING_STATUS].Value = 0  # the last sheet went through
    assert len(got) == 2
    glass = Device([a, a + 1, b], props=())  # says nothing about the feeder, and gives the glass again and again
    glass.Properties[scanner.HANDLING_SELECT] = Refuses()
    got = []
    with pytest.raises(scanner.ScanStopped, match="glass"):
        for p in wia(glass).pages(200, False):
            got.append(p)
    assert len(got) == 1


class Select(types.SimpleNamespace):
    def __init__(self, takes):
        super().__init__()
        object.__setattr__(self, "takes", takes)
        object.__setattr__(self, "_value", 0)

    @property
    def Value(self):  # noqa: N802
        return self._value

    @Value.setter
    def Value(self, v):  # noqa: N802
        if v not in self.takes:
            raise ComError(0x80004005)
        object.__setattr__(self, "_value", v)


class Resolution(types.SimpleNamespace):
    """A resolution property that takes only some values, as many drivers do."""

    def __init__(self, takes, **kw):
        super().__init__(**kw)
        object.__setattr__(self, "takes", takes)
        object.__setattr__(self, "_value", 100)

    @property
    def Value(self):  # noqa: N802 - COM's name
        return self._value

    @Value.setter
    def Value(self, v):  # noqa: N802
        if v not in self.takes:
            raise ComError(0x80070057)  # E_INVALIDARG
        object.__setattr__(self, "_value", v)


def driver(takes, **kw):
    d = Device([np.full((50, 40, 3), 200, np.uint8), scanner.PAPER_EMPTY])
    d.item.Properties[scanner.X_RES] = Resolution(takes, **kw)
    d.item.Properties[scanner.Y_RES] = Resolution(takes)
    return d


@pytest.mark.parametrize("takes, kw, used", [
    ({150, 300, 600}, {}, 150),  # says nothing: the nearest of the usual ones it takes
    ({300, 600}, dict(SubType=scanner.LIST, SubTypeValues=types.SimpleNamespace(
        Count=2, Item=lambda i: (300, 600)[i - 1])), 300),  # lists what it takes
    ({100, 200, 300}, dict(SubType=scanner.RANGE, SubTypeMin=100, SubTypeMax=300, SubTypeStep=100), 200),
])
def test_scans_at_a_resolution_the_scanner_takes(takes, kw, used):
    s = wia(driver(takes, **kw))
    assert len(list(s.pages(200, False))) == 1 and s.dpi == used


def test_a_scanner_that_takes_no_usable_resolution_says_to_use_a_folder():
    with pytest.raises(scanner.ScanStopped, match="into a folder"):
        list(wia(driver({75, 100})).pages(200, False))
