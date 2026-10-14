"""The phone page's corner-mark finder, run as it is in Node on camera frames as a real phone gives them: dim,
shadowed, with glare, tipped, softened, shaken, noisy and small. Each case is a few frames of a hand holding the
phone; the photo should be taken (or not) by the last one. Skipped without Node; it can't show a real phone's
camera, focus or light."""

import json
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from omr_core.phone_page import DETECT
from omr_core.sheet import SheetSpec, layout, render
from omr_core.template import parse
from sheets import camera, draw, fill, random_marks

NODE = shutil.which("node")
WIDTH = 640  # the page judges frames this wide (DETECT_WIDTH)
pytestmark = pytest.mark.skipif(not NODE, reason="no Node to run the phone page's code")

RUN = """
const fs = require("fs"), vm = require("vm");
const job = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
vm.runInThisContext(fs.readFileSync(process.argv[3], "utf8"));
const out = job.cases.map(c => {
  const bytes = fs.readFileSync(c.path), size = c.w * c.h;
  let before = null, a = null;
  for (let i = 0; i < c.n; i++) {
    a = assess(Float32Array.from(bytes.subarray(i * size, (i + 1) * size)), c.w, c.h, job.sheet, before);
    before = a;
  }
  return { ready: a.ready, hint: a.hint, found: a.found.map(f => !!f && f.inside),
           why: a.seen.map(f => f.ok ? "" : f.why) };
});
process.stdout.write(JSON.stringify(out));
"""

TAKE = {  # a hand holding the phone over the sheet roughly in place
    "clean": {},
    "dim room": {"light": 0.35},
    "very dim": {"light": 0.22, "noise": 6},
    "shadow across": {"shadow": 0.6},
    "glare": {"glare": 0.7},
    "tipped": {"keystone": 0.08, "turn": 4},
    "off a little": {"shift": (0.03, -0.02), "scale": 0.93},
    "too close a little": {"scale": 1.07},
    "soft focus": {"blur": 1.5},
    "noisy video": {"noise": 9, "quality": 35},
    "light table": {"table": (200, 205, 210)},
    "everything at once": {"light": 0.45, "shadow": 0.4, "keystone": 0.05, "turn": -3, "blur": 1.2, "noise": 6,
                           "shift": (-0.02, 0.02), "quality": 45},
}
SKIP = {  # not taken: what the PC couldn't read well, or no sheet in place
    "out of focus": {"blur": 7},
    "shaken": {"shake": 16},
    "a corner off the picture": {"shift": (0.14, 0.0)},
    "far away": {"scale": 0.8},
}
CAMERAS = {"1080 x 1440": (1080, 1440), "720 x 1280": (720, 1280), "480 x 640": (480, 640)}


def sheets():
    t = parse(json.loads((Path(__file__).parent.parent / "templates" / "test-100.json").read_text(encoding="utf-8")))
    d = layout(SheetSpec("Weekly", 40, roll_digits=4, sets=0))  # ring corner marks, as the app makes them
    r = parse(d)
    return {"square marks": (draw(t, random_marks(t, 5)[0]), t),
            "ring marks": (fill(render(d), r, random_marks(r, 3)[0]), r)}


def judge(tmp_path, t, cases: dict) -> dict:
    """Each case's last frame as the page judges it, the frames shrunk as the page shrinks them."""
    job = {"sheet": {"page": list(t.page), "shape": t.marker_shape, "size": t.marker_size,
                     "marks": [list(m) for m in t.markers]}, "cases": []}
    for i, frames in enumerate(cases.values()):
        h, w = frames[0].shape[:2]
        dw = min(WIDTH, w)
        dh = round(h * dw / w)
        grey = [cv2.resize(f, (dw, dh), interpolation=cv2.INTER_LINEAR).mean(-1).astype(np.uint8) for f in frames]
        path = tmp_path / f"case{i}.raw"
        path.write_bytes(b"".join(g.tobytes() for g in grey))
        job["cases"].append({"path": str(path), "w": dw, "h": dh, "n": len(grey)})
    (tmp_path / "job.json").write_text(json.dumps(job))
    (tmp_path / "detect.js").write_text(DETECT, encoding="utf-8")
    (tmp_path / "run.js").write_text(RUN)
    out = subprocess.run([NODE, tmp_path / "run.js", tmp_path / "job.json", tmp_path / "detect.js"],
                         capture_output=True, text=True, check=True).stdout
    return dict(zip(cases, json.loads(out)))


def held(page, t, size, args: dict, frames: int = 3) -> list[np.ndarray]:
    """A few frames of a hand holding the phone: it drifts a pixel or two between them."""
    out = []
    for i in range(frames):
        a = dict(args)
        sx, sy = a.pop("shift", (0, 0))
        out.append(camera(page, t, size, shift=(sx + 0.002 * i, sy - 0.0015 * i), seed=i, **a))
    return out


@pytest.mark.parametrize("camera_size", CAMERAS)
@pytest.mark.parametrize("marks", ["square marks", "ring marks"])
def test_a_sheet_held_roughly_in_place_is_taken_in_poor_conditions(tmp_path, marks, camera_size):
    page, t = sheets()[marks]
    got = judge(tmp_path, t, {name: held(page, t, CAMERAS[camera_size], a) for name, a in TAKE.items()})
    missed = {name: r for name, r in got.items() if not r["ready"]}
    assert missed == {}


@pytest.mark.parametrize("marks", ["square marks", "ring marks"])
def test_a_blurred_shaken_partial_or_distant_sheet_is_not_taken(tmp_path, marks):
    page, t = sheets()[marks]
    got = judge(tmp_path, t, {name: held(page, t, (1080, 1440), a) for name, a in SKIP.items()})
    taken = [name for name, r in got.items() if r["ready"]]
    assert taken == []
    assert got["far away"]["hint"] == "Move the phone closer"


def test_a_sheet_moving_under_the_phone_is_not_taken_until_it_stops(tmp_path):
    page, t = sheets()["square marks"]
    moving = [camera(page, t, shift=(0.02 * i, 0), seed=i) for i in range(3)]
    got = judge(tmp_path, t, {"moving": moving, "then still": moving + held(page, t, (1080, 1440), {"shift": (0.04, 0)})})
    assert not got["moving"]["ready"] and got["then still"]["ready"]


def test_the_table_alone_finds_no_marks(tmp_path):
    page, t = sheets()["square marks"]
    empty = np.full_like(page, 255)[:10, :10]
    table = [camera(empty, t, scale=0.01, seed=i) for i in range(3)]
    got = judge(tmp_path, t, {"table": table})["table"]
    assert not got["ready"] and not any(got["found"])


def test_the_page_script_parses(tmp_path):
    from omr_core.phone_page import phone_page
    page = phone_page(1, "Mock", "token", "Ravi", sheets()["ring marks"][1])
    (tmp_path / "page.js").write_text(page[page.index("<script>") + 8:page.index("</script>")], encoding="utf-8")
    subprocess.run([NODE, "--check", tmp_path / "page.js"], check=True)
