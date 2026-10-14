"""The TWAIN conversation, with a fake data source manager and fake Windows standing in."""

import cv2
import numpy as np
import pytest

pytest.importorskip("PySide6")

from omr_app import twain  # noqa: E402
from omr_app.scanner import ScanStopped  # noqa: E402
from omr_app.twain import ONEVALUE  # noqa: E402

XFER, OTHER = 111, 222  # window messages: the source's "page ready", and anything else


class FakeWin:
    def __init__(self):
        self.memory, self.next, self.queue, self.dispatched, self.closed = {}, 1, [], [], False

    def window(self):
        return 77

    def alloc(self, data):
        self.next += 1
        self.memory[self.next] = bytes(data)
        return self.next

    def read(self, handle, size=None):
        data = self.memory[handle]
        return data[:size] if size else data

    def free(self, handle):
        del self.memory[handle]

    def next_message(self):
        return self.queue.pop(0) if self.queue else None

    def dispatch(self, message):
        self.dispatched.append(message)

    def close(self):
        self.closed = True


class FakeDsm:
    """A source with a feeder: `pages` are images, or a TWAIN condition code that fails that transfer."""

    def __init__(self, win, pages, refuse=(), loaded=1):
        self.win, self.pages, self.refuse, self.loaded = win, list(pages), set(refuse), loaded
        self.caps, self.calls, self.condition = {}, [], 0

    def __call__(self, dest, group, dat, msg, data):
        self.calls.append((dat, msg))
        t = twain
        if dat == t.DAT_IDENTITY and msg in (t.MSG_GETFIRST, t.MSG_GETNEXT):
            names = [b"Pantum M7100", b"Other"]
            k = 0 if msg == t.MSG_GETFIRST else self.listed
            if k >= len(names):
                return t.TWRC_ENDOFLIST
            data.ProductName, self.listed = names[k], k + 1
            return t.TWRC_SUCCESS
        if dat == t.DAT_CAPABILITY and msg == t.MSG_SET:
            if data.Cap in self.refuse:
                return t.TWRC_FAILURE
            self.caps[data.Cap] = ONEVALUE.unpack(self.win.read(data.hContainer))[1]
            return t.TWRC_SUCCESS
        if dat == t.DAT_CAPABILITY and msg == t.MSG_GETCURRENT:
            if data.Cap != t.CAP_FEEDERLOADED:
                return t.TWRC_FAILURE
            data.ConType, data.hContainer = t.TWON_ONEVALUE, self.win.alloc(ONEVALUE.pack(t.TWTY_BOOL, self.loaded))
            return t.TWRC_SUCCESS
        if dat == t.DAT_USERINTERFACE and msg == t.MSG_ENABLEDS:
            assert not data.ShowUI and data.hParent == 77
            self.win.queue += [OTHER, XFER]
            return t.TWRC_SUCCESS
        if dat == t.DAT_EVENT:
            if data.pEvent != XFER:
                return t.TWRC_NOTDSEVENT
            data.TWMessage = t.MSG_XFERREADY
            return t.TWRC_DSEVENT
        if dat == t.DAT_IMAGENATIVEXFER:
            page = self.pages.pop(0)
            if isinstance(page, int):
                self.condition = page
                return t.TWRC_FAILURE
            data.value = self.win.alloc(cv2.imencode(".bmp", page)[1].tobytes()[14:])  # a DIB: a BMP's header off
            return t.TWRC_XFERDONE
        if dat == t.DAT_PENDINGXFERS:
            data.Count = len(self.pages) if msg == t.MSG_ENDXFER else 0
            return t.TWRC_SUCCESS
        if dat == t.DAT_STATUS:
            data.ConditionCode = self.condition
            return t.TWRC_SUCCESS
        return t.TWRC_SUCCESS


def scanner_with(pages, **kw):
    win = FakeWin()
    dsm = FakeDsm(win, pages, **kw)
    return twain.TwainScanner("Pantum M7100 (TWAIN)", b"Pantum M7100", lambda: dsm, lambda: win), dsm, win


def test_pages_come_from_the_feeder_until_it_is_empty():
    a, b = np.full((60, 40), 200, np.uint8), np.full((60, 40), 90, np.uint8)
    s, dsm, win = scanner_with([a, b])
    got = list(s.pages(200, True))
    assert [int(p[0, 0, 0]) for p in got] == [200, 90] and got[0].shape == (60, 40, 3)
    assert dsm.caps[twain.CAP_FEEDERENABLED] == 1 and dsm.caps[twain.CAP_DUPLEXENABLED] == 1
    assert twain.from_fix32(dsm.caps[twain.ICAP_XRESOLUTION]) == 200 and s.dpi == 200 and not s.one_side
    assert win.dispatched == [OTHER] and not win.memory and win.closed  # every handle freed
    assert (twain.DAT_IDENTITY, twain.MSG_CLOSEDS) in dsm.calls and dsm.calls[-1][1] == twain.MSG_CLOSEDSM


def test_a_source_that_refuses_both_sides_or_the_resolution():
    page = np.full((60, 40), 200, np.uint8)
    s, dsm, _ = scanner_with([page], refuse={twain.CAP_DUPLEXENABLED})
    assert len(list(s.pages(200, True))) == 1 and s.one_side
    s, *_ = scanner_with([page], refuse={twain.ICAP_XRESOLUTION})
    with pytest.raises(ScanStopped, match="won't scan at 150 DPI"):
        list(s.pages(200, False))


@pytest.mark.parametrize("pages, kw, message", [
    ([], {"loaded": 0}, "The feeder is empty"),
    ([np.full((60, 40), 200, np.uint8), twain.TWCC_PAPERJAM], {}, "Paper jam"),
    ([twain.TWCC_PAPERDOUBLEFEED], {}, "Two sheets fed together"),
])
def test_problems_stop_the_run(pages, kw, message):
    s, dsm, win = scanner_with(pages, **kw)
    with pytest.raises(ScanStopped, match=message):
        list(s.pages(200, False))
    assert win.closed and dsm.calls[-1][1] == twain.MSG_CLOSEDSM


def test_stopping_mid_batch_hands_the_source_back():
    page = np.full((60, 40), 200, np.uint8)
    s, dsm, win = scanner_with([page, page, page])
    run = s.pages(200, False)
    next(run)
    run.close()
    assert (twain.DAT_PENDINGXFERS, twain.MSG_RESET) in dsm.calls and win.closed


def test_sources_are_listed_and_numbers_converted():
    win = FakeWin()
    assert [i.ProductName for i in twain.Session(FakeDsm(win, []), win).sources()] == [b"Pantum M7100", b"Other"]
    assert twain.from_fix32(twain.fix32(300)) == 300 and twain.from_fix32(twain.fix32(-1.5)) == -1.5
    colour = np.dstack([np.full((7, 5), v, np.uint8) for v in (10, 20, 30)])
    assert (twain.dib_to_image(cv2.imencode(".bmp", colour)[1].tobytes()[14:]) == colour).all()
    assert twain.dib_to_image(b"junk") is None
