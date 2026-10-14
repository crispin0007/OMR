"""The phone page in a real browser with a simulated camera: Chromium plays a video of a table, then a sheet held
too far away, then sheets lined up with the targets. Needs Playwright and Chromium, so it is skipped without them
(CI); it can't show a real phone's camera, focus or light."""

import json
import os
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from omr_core.lan import MainServer, make_cert
from omr_core.sheet import SheetSpec, layout, render
from omr_core.store import Store
from omr_core.template import parse
from sheets import draw, fill, random_marks

playwright = pytest.importorskip("playwright.sync_api")
CHROMIUM = os.environ.get("OMR_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
if not Path(CHROMIUM).exists():
    pytest.skip("no Chromium to play the simulated camera", allow_module_level=True)

W, H = 1080, 1440  # a phone held upright


def frame(sheet: np.ndarray | None, t, scale: float = 1.0) -> np.ndarray:
    """A camera frame of a dark table, with the sheet where the page's targets are (times `scale`)."""
    f = np.full((H, W, 3), (60, 70, 80), np.uint8)
    if sheet is not None:
        k = min(0.86 * W / t.page[0], 0.86 * H / t.page[1]) * scale  # as the page's guide() fits it
        s = cv2.resize(sheet, (round(t.page[0] * k), round(t.page[1] * k)), interpolation=cv2.INTER_AREA)
        y, x = (H - s.shape[0]) // 2, (W - s.shape[1]) // 2
        f[y:y + s.shape[0], x:x + s.shape[1]] = (s * 0.85).astype(np.uint8)  # a little dimmer than white
    return f


def run(tmp_path, template_json: str, sheets: list[np.ndarray], t) -> tuple[list[str], list[str], Store, int]:
    store = Store(tmp_path / "omr.db")
    exam = store.create_exam("Mock", template_json)
    token = store.add_station("Ravi", "Phone")
    frames = [frame(None, t)] * 10 + [frame(sheets[0], t, 0.85)] * 25  # too far away: never taken
    for s in sheets:
        frames += [frame(s, t)] * 30 + [frame(None, t)] * 10
    video = tmp_path / "camera.y4m"
    with open(video, "wb") as f:
        f.write(f"YUV4MPEG2 W{W} H{H} F10:1 Ip A1:1 C420jpeg\n".encode())
        for fr in frames:
            f.write(b"FRAME\n" + cv2.cvtColor(fr, cv2.COLOR_BGR2YUV_I420).tobytes())
    server = MainServer(tmp_path / "omr.db", port=0, cert=make_cert(tmp_path / "cert"))
    hints, results = [], [""]
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROMIUM, args=[
                "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                f"--use-file-for-fake-video-capture={video}"])
            page = browser.new_context(ignore_https_errors=True, viewport={"width": 390, "height": 760}).new_page()
            page.goto(f"https://127.0.0.1:{server.secure_port}/phone?exam={exam}&t={token}")
            end = time.time() + 30
            while time.time() < end and not (len(store.pages(exam)) == len(sheets) and results[-1].startswith("✓")
                                             and len([r for r in results if r.startswith("✓")]) == len(sheets)):
                for box, seen in (("#hint", hints), ("#result", results)):
                    text = page.inner_text(box)
                    if not seen or seen[-1] != text:
                        seen.append(text)
                time.sleep(0.1)
            page.screenshot(path=str(tmp_path / "phone.png"))
            browser.close()
    finally:
        server.stop()
    return hints, results, store, exam


def test_the_camera_takes_a_sheet_only_once_its_corner_marks_are_in_their_targets(tmp_path):
    template = (Path(__file__).parent.parent / "templates" / "test-100.json").read_text(encoding="utf-8")
    t = parse(json.loads(template))
    picks = [random_marks(t, seed) for seed in (5, 6)]
    hints, results, store, exam = run(tmp_path, template, [draw(t, m) for m, *_ in picks], t)
    assert "Move the phone closer" in hints  # the sheet held too far away wasn't taken
    assert [p.result.roll_number for p in store.pages(exam)] == [roll for _, _, roll, _ in picks]
    assert [r for r in results if r.startswith("✓")] == [f"✓ Read: roll {roll}" for _, _, roll, _ in picks]


def test_the_targets_follow_a_sheet_made_in_the_app(tmp_path):
    d = layout(SheetSpec("Weekly", 40, roll_digits=4, sets=0))  # ring corner marks
    t = parse(d)
    marks, answers, roll, _ = random_marks(t, 3)
    hints, results, store, exam = run(tmp_path, json.dumps(d), [fill(render(d), t, marks)], t)
    (got,) = store.pages(exam)
    assert got.result.roll_number == roll and got.result.answers == answers
