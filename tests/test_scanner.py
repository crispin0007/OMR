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


class Device:
    def __init__(self, transfers, props=(scanner.HANDLING_SELECT, scanner.PAGES)):
        self.Properties = Props({k: types.SimpleNamespace(Value=0) for k in props})
        self.item = types.SimpleNamespace(
            Properties=Props({k: types.SimpleNamespace(Value=0) for k in (scanner.X_RES, scanner.Y_RES)}),
            Transfer=lambda fmt: self.next(fmt))
        self.transfers = list(transfers)

    def Items(self, n):
        return self.item

    def next(self, fmt):
        assert fmt == scanner.BMP
        t = self.transfers.pop(0)
        if isinstance(t, int):
            raise ComError(t)
        data = cv2.imencode(".bmp", t)[1].tobytes()
        return types.SimpleNamespace(FileData=types.SimpleNamespace(BinaryData=data))


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


def test_a_scanner_without_a_feeder_says_so():
    with pytest.raises(scanner.ScanStopped, match="Couldn.t set Test to feed from the feeder"):
        list(wia(Device([], props=())).pages(200, False))


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
