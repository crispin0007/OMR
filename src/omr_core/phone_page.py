"""The page a phone opens from the PC's QR code to photograph sheets (specs/006-phone-scanning). It is served by
the PC itself; nothing is loaded from the internet.

With a secure (https) address the camera runs live, with a target where each of the sheet's corner marks goes,
and takes each sheet by itself once all four marks are in their targets, sharp and still, then waits for the
next sheet to be put down. Without one, or when the camera can't be used, the phone's
own camera takes the photos through the upload button. Each photo is sent with an id of its own and resent until
the PC answers, so a photo is never lost to a dropped Wi-Fi nor saved twice."""

import json
from html import escape

from .template import Template

DETECT = r"""// Finding the sheet's four corner marks in a camera frame. These are plain functions of a grey frame (an array
// of 0 to 255, w x h), with no page or browser in them, so the tests run them as they are.
//
// A corner mark is told by how much darker a box its size is than the paper just around it, with paper and ink
// levels taken from the frame near each target: so a dim room, a shadow across the sheet, a glare spot or a
// thin printed ring that the phone's video softens still shows as a mark, while a straight edge, the table
// around the sheet or a bubble doesn't. The phone only needs to find the marks roughly where the targets are;
// the PC reads the photo, and asks for a retake when it can't, so here the tolerances are wide.
var DETECT_WIDTH = 640;  // frames are judged this wide
var MIN_MARK = 0.25;     // a box over a mark is at least this share darker than the paper around it
var MAX_SPREAD = 0.22;   // and the paper around it this even: its spread as a share of its brightness
var MIN_EDGE = 0.15;     // a mark's edge rises at least this share of paper-to-ink in one pixel: not badly blurred
var STILL = 0.012;       // the marks moved less than this share of the frame width since the last check
var MAX_SHAPE = 0.3;     // each side of the four marks' shape within this share of the others (the phone tipped)

// Where the sheet's corner marks should be in a frame `fw` x `fh` pixels: the page fitted in the picture with a
// margin, as the targets are drawn. (frame pixels per mm, mark size in pixels, mark centres)
function guide(fw, fh, sheet) {
  var k = Math.min(0.86 * fw / sheet.page[0], 0.86 * fh / sheet.page[1]);
  var ox = (fw - sheet.page[0] * k) / 2, oy = (fh - sheet.page[1] * k) / 2;
  return { k: k, size: sheet.size * k,
           marks: sheet.marks.map(function (p) { return [ox + p[0] * k, oy + p[1] * k]; }) };
}

function percentile(hist, n, share) {
  var want = n * share, seen = 0;
  for (var v = 0; v < 256; v++) { seen += hist[v]; if (seen >= want) return v; }
  return 255;
}

// The corner mark about `size` across nearest (cx, cy) within `reach` pixels: {x, y, score, edge, ok}, with
// `why` when it isn't one (ok false), for the debug readout. A box over the mark is darker than the paper around
// it by a share of the paper's own brightness, so a mark in shadow counts as one in full light; and the paper
// around it is even, which the table at the sheet's corner, half of it dark, is not.
function findMark(grey, w, h, cx, cy, size, reach) {
  var x0 = Math.max(0, Math.round(cx - reach)), x1 = Math.min(w, Math.round(cx + reach)),
      y0 = Math.max(0, Math.round(cy - reach)), y1 = Math.min(h, Math.round(cy + reach));
  var ww = x1 - x0, hh = y1 - y0, x, y;
  if (ww < size * 2 || hh < size * 2) return { ok: false, why: "target off the picture" };
  var hist = new Uint32Array(256);
  for (y = y0; y < y1; y++) for (x = x0; x < x1; x++) hist[Math.max(0, Math.min(255, grey[y * w + x] | 0))]++;
  var paper = percentile(hist, ww * hh, 0.9);
  if (paper < 35) return { ok: false, why: "too dark here", paper: paper };
  // brightness and its square summed, so any box's mean and spread are a few look-ups
  var W = ww + 1, sum = new Float64Array(W * (hh + 1)), sq = new Float64Array(W * (hh + 1));
  for (y = 0; y < hh; y++) {
    var row = 0, row2 = 0;
    for (x = 0; x < ww; x++) {
      var v = grey[(y + y0) * w + x + x0];
      row += v; row2 += v * v;
      sum[(y + 1) * W + x + 1] = sum[y * W + x + 1] + row;
      sq[(y + 1) * W + x + 1] = sq[y * W + x + 1] + row2;
    }
  }
  function box(t, ax, ay, bx, by) {  // [sum, pixels] of a box, clipped to the window
    ax = Math.max(0, ax); ay = Math.max(0, ay); bx = Math.min(ww, bx); by = Math.min(hh, by);
    if (bx <= ax || by <= ay) return [0, 0];
    return [t[by * W + bx] - t[ay * W + bx] - t[by * W + ax] + t[ay * W + ax], (bx - ax) * (by - ay)];
  }
  function judge(x, y, s) {  // a box `s` across centred at window pixel (x, y), against the paper around it
    var a = Math.floor(s / 2), inner = box(sum, x - a, y - a, x - a + s, y - a + s),
        outer = box(sum, x - s, y - s, x + s, y + s), n = outer[1] - inner[1];
    if (inner[1] < s * s || n < s * s) return null;
    var around = (outer[0] - inner[0]) / n;
    if (around < 20) return null;
    var spread = Math.sqrt(Math.max(0, (box(sq, x - s, y - s, x + s, y + s)[0] - box(sq, x - a, y - a, x - a + s, y - a + s)[0]) / n
                                       - around * around)) / around;
    var score = 1 - inner[0] / inner[1] / around, off = Math.hypot(x + x0 - cx, y + y0 - cy);
    return { x: x, y: y, s: s, score: score, around: around, spread: spread,
             valid: score >= MIN_MARK && spread <= MAX_SPREAD, rank: score * (1 - 0.3 * off / reach) };
  }
  var best = null, closest = null;
  function consider(j) {
    if (!j) return;
    if (!closest || j.score > closest.score) closest = j;
    if (j.valid && (!best || j.rank > best.rank)) best = j;
  }
  [0.75, 1, 1.3].forEach(function (f) {
    var s = Math.max(4, Math.round(size * f));
    for (y = s; y <= hh - s; y += 2) for (x = s; x <= ww - s; x += 2) consider(judge(x, y, s));
  });
  if (best) {  // the coarse search went in steps of two: settle on the pixel
    var b = best;
    for (y = b.y - 2; y <= b.y + 2; y++) for (x = b.x - 2; x <= b.x + 2; x++) consider(judge(x, y, b.s));
  }
  var f = best || closest;
  if (!f) return { ok: false, why: "nothing dark here", paper: paper };
  var out = { x: f.x + x0, y: f.y + y0, size: f.s, score: f.score, paper: f.around,
              edge: edge(grey, w, f.x + x0, f.y + y0, f.s, f.around), ok: !!best };
  if (!out.ok) out.why = f.score < MIN_MARK ? "too faint" : "uneven around it (the sheet's edge?)";
  return out;
}

// How sharp a mark's edges are: the steepest one-pixel rise from ink to paper across the mark, along its middle
// rows and, apart, its middle columns, as a share of paper less ink; the blurrier way of the two. Out of focus
// spreads the rise over several pixels every way, a shaken phone along the way it moved.
function edge(grey, w, cx, cy, s, paper) {
  var h = grey.length / w, r = Math.round(s * 0.9), q = Math.max(1, Math.round(s / 4)), across = [], down = [],
      ink = 255, i, j, v;
  for (j = -q; j <= q; j++) for (i = -q; i <= q; i++) {
    v = grey[Math.min(h - 1, Math.max(0, cy + j)) * w + Math.min(w - 1, Math.max(0, cx + i))];
    if (v < ink) ink = v;
  }
  for (j = -q; j <= q; j++) {
    var a = 0, d = 0;
    for (i = -r; i < r; i++) {
      var x = Math.min(w - 2, Math.max(0, cx + i)), y = Math.min(h - 1, Math.max(0, cy + j));
      a = Math.max(a, Math.abs(grey[y * w + x + 1] - grey[y * w + x]));
      x = Math.min(w - 1, Math.max(0, cx + j)); y = Math.min(h - 2, Math.max(0, cy + i));
      d = Math.max(d, Math.abs(grey[(y + 1) * w + x] - grey[y * w + x]));
    }
    across.push(a); down.push(d);
  }
  var middle = function (xs) { xs.sort(function (p, q) { return p - q; }); return xs[Math.floor(xs.length / 2)]; };
  return Math.min(middle(across), middle(down)) / Math.max(10, paper - ink);
}

function brightness(grey) {
  var sum = 0, n = 0;
  for (var i = 0; i < grey.length; i += 7) { sum += grey[i]; n++; }
  return sum / n;
}

// How far each side of the four marks' shape is from its share of the targets' (0 when the shape matches), or
// null when they're out of order, such as two found on the same mark.
function shapeOff(found, want) {
  var ratios = [], mean = 0;
  for (var i = 0; i < 4; i++) {
    var a = found[i], b = found[(i + 1) % 4], m = want[i], n = want[(i + 1) % 4], c = found[(i + 2) % 4];
    if ((b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x) <= 0) return null;  // turning the wrong way
    ratios.push(Math.hypot(b.x - a.x, b.y - a.y) / Math.hypot(n[0] - m[0], n[1] - m[1]));
    mean += ratios[i] / 4;
  }
  return Math.max.apply(null, ratios.map(function (r) { return Math.abs(r - mean) / mean; }));
}

// What to do to line the sheet up, from the marks found (null where one isn't) and where they should be.
function advice(found, want, tol, bright) {
  var have = [], should = [], dx = 0, dy = 0;
  found.forEach(function (f, i) {
    if (f) { have.push(f); should.push({ x: want[i][0], y: want[i][1] }); dx += f.x - want[i][0]; dy += f.y - want[i][1]; }
  });
  if (have.length < 2) return bright < 60 ? "Need more light" : "Line up the sheet's four corner marks with the targets";
  dx /= have.length; dy /= have.length;
  var spread = function (ps) {
    var d = 0; for (var i = 1; i < ps.length; i++) d += Math.hypot(ps[i].x - ps[0].x, ps[i].y - ps[0].y); return d;
  };
  var ratio = spread(have) / spread(should);
  if (ratio < 0.88) return "Move the phone closer";
  if (ratio > 1.12) return "Move the phone back a little";
  // the sheet shows to the right of its targets when the phone is too far left
  if (Math.abs(dx) > tol * 0.5) return dx > 0 ? "Move the phone right" : "Move the phone left";
  if (Math.abs(dy) > tol * 0.5) return dy > 0 ? "Move the phone down" : "Move the phone up";
  if (have.length === 4) return "Hold the phone flat over the sheet";
  return bright < 60 ? "Need more light" : "Line up the marks still out of their targets";
}

// One check of a frame: the marks found and whether the photo can be taken. `before` is the last check's.
function assess(grey, w, h, sheet, before) {
  var g = guide(w, h, sheet), reach = Math.max(g.size * 2.5, 0.16 * w), tol = Math.max(g.size * 2, 0.12 * w);
  var seen = g.marks.map(function (m) { return findMark(grey, w, h, m[0], m[1], g.size, reach); });
  var found = seen.map(function (f, i) {
    return f.ok ? { x: f.x, y: f.y, edge: f.edge,
                    inside: Math.hypot(f.x - g.marks[i][0], f.y - g.marks[i][1]) < tol } : null;
  });
  var bright = brightness(grey), inside = found.every(function (f) { return f && f.inside; });
  var shape = inside ? shapeOff(found, g.marks) : null, all = inside && shape !== null && shape <= MAX_SHAPE;
  var moved = null, sharpness = null;
  if (all) {
    sharpness = Math.min.apply(null, found.map(function (f) { return f.edge; }));
    if (before && before.all) moved = Math.max.apply(null, found.map(function (f, i) {
      return Math.hypot(f.x - before.found[i].x, f.y - before.found[i].y);
    }));
  }
  var still = moved !== null && moved < STILL * w, sharp = sharpness !== null && sharpness >= MIN_EDGE;
  var hint = !inside ? advice(found, g.marks, tol, bright) : !all ? "Hold the phone flat over the sheet" :
    !sharp ? "Hold steady to focus" : !still ? "Hold still…" : "Taking…";
  return { guide: g, seen: seen, found: found, tol: tol, bright: bright, shape: shape, all: all, moved: moved,
           sharpness: sharpness, ready: all && still && sharp, hint: hint };
}
"""

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: blob:; media-src blob: mediastream:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'">
<title>Scan sheets: __EXAM__</title>
<style>
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; background: #111; color: #fff; font: 16px/1.4 -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif; }
main { display: flex; flex-direction: column; height: 100%; }
header { display: flex; align-items: center; gap: 10px; padding: 10px 14px; background: #1d2330; }
header div { flex: 1; min-width: 0; }
header b { display: block; font-size: 17px; }
header span { color: #b8bfcc; font-size: 13px; }
#view { position: relative; flex: 1; overflow: hidden; background: #000; }
video { width: 100%; height: 100%; object-fit: contain; }
#overlay { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
#hint { position: absolute; left: 0; right: 0; bottom: 10px; text-align: center; font-size: 15px; text-shadow: 0 1px 3px #000; }
#result { padding: 12px 14px; font-size: 17px; font-weight: 600; min-height: 50px; background: #2a3040; }
#result.ok { background: #1f7a43; } #result.retake { background: #a33a3a; } #result.same { background: #7a5f1f; }
footer { display: flex; gap: 8px; padding: 10px 14px calc(10px + env(safe-area-inset-bottom)); background: #1d2330; align-items: center; }
button, label.button { flex: 1; padding: 13px 8px; font: inherit; font-weight: 600; border: 0; border-radius: 10px; background: #3b4458; color: #fff; text-align: center; }
button.main { background: #1565c0; }
#count { min-width: 74px; text-align: center; font-size: 13px; color: #b8bfcc; }
#count b { display: block; font-size: 22px; color: #fff; }
#upload { display: none; }
.note { padding: 16px; color: #d9dde5; }
#details { flex: none; padding: 7px 10px; font-size: 13px; }
#details.on { background: #1565c0; }
#debug { position: absolute; left: 6px; right: 6px; top: 50%; transform: translateY(-50%); margin: 0; padding: 6px 8px; background: rgba(0,0,0,.72); color: #e6e9ef; font: 11px/1.35 ui-monospace, Menlo, Consolas, monospace; white-space: pre-wrap; border-radius: 6px; pointer-events: none; }
#debug[hidden] { display: none; }
</style></head>
<body><main>
<header><div><b>__EXAM__</b><span>__WHO__</span></div><button id="details" title="What the camera sees">Details</button></header>
<div id="view">
  <video id="video" playsinline muted></video>
  <canvas id="overlay"></canvas>
  <pre id="debug" hidden></pre>
  <div id="hint">Starting the camera…</div>
</div>
<div id="result">Hold the phone over a sheet and line its four corner marks up with the targets.</div>
<footer>
  <button id="auto" class="main">Auto: on</button>
  <button id="shoot">Take now</button>
  <label class="button" for="upload">Photos…</label>
  <input id="upload" type="file" accept="image/*" capture="environment" multiple>
  <div id="count"><b>0</b>sent</div>
</footer>
</main>
<script>
"use strict";
__DETECT__
var EXAM = __EXAM_ID__, TOKEN = __TOKEN__, SHEET = __SHEET__;
var video = document.getElementById("video"), hint = document.getElementById("hint"),
    overlay = document.getElementById("overlay"), result = document.getElementById("result"),
    autoButton = document.getElementById("auto"), count = document.getElementById("count").firstChild;
var armed = true, steadyFor = 0, last = null, previous = null, sent = 0, queue = [], sending = false, live = false;

function say(text, kind) { result.textContent = text; result.className = kind || ""; }

function uid() {
  var a = new Uint8Array(12); crypto.getRandomValues(a);
  return "phone:" + Array.prototype.map.call(a, function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
}

// Photos go one at a time, each resent with its own id until the PC answers, so none is lost or doubled.
function send(image) { queue.push({ uid: uid(), image: image }); next(); }
function next() {
  if (sending || !queue.length) return;
  sending = true;
  var item = queue[0];
  fetch("/exams/" + EXAM + "/photo", {
    method: "POST", headers: { "Content-Type": "application/json", "X-Token": TOKEN },
    body: JSON.stringify({ uid: item.uid, image: item.image })
  }).then(function (r) {
    return r.json().then(function (body) { return { status: r.status, body: body }; });
  }).then(function (r) {
    sending = false;
    if (r.status === 401 || r.status === 403) {
      queue = []; say("This phone was taken out. Scan the QR code on the PC again.", "retake"); return;
    }
    queue.shift();
    var b = r.body;
    if (r.status !== 200) say("Retake: " + (b.error || "the PC couldn't use that photo"), "retake");
    else if (!b.ok) say("Retake: " + b.why, "retake");
    else if (!b.new) say("Already have this sheet (roll " + b.roll + "). Put down the next one.", "same");
    else {
      sent += 1; count.textContent = sent;
      say("✓ Read: roll " + b.roll + (b.to_check ? ", " + b.to_check + " to check on the PC" : ""), "ok");
      if (navigator.vibrate) navigator.vibrate(80);
    }
    next();
  }, function () {  // no Wi-Fi or the PC is off: keep the photo and try again
    sending = false;
    say("Can't reach the PC; " + queue.length + " photo(s) kept on this page and sent when it's back. Keep this page open.", "retake");
    setTimeout(next, 3000);
  });
}

function jpeg(source, w, h) {
  var c = document.createElement("canvas"), scale = Math.min(1, 3200 / Math.max(w, h));
  c.width = Math.round(w * scale); c.height = Math.round(h * scale);
  c.getContext("2d").drawImage(source, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.88).split(",")[1];
}

function shoot() {
  if (!live || !video.videoWidth) return;
  armed = false; steadyFor = 0;
  say("Reading…");
  send(jpeg(video, video.videoWidth, video.videoHeight));
}

// The targets and the marks found, over the picture: frame pixel (x, y) is drawn where the video shows it.
function draw(fw, fh, a) {
  var r = overlay.getBoundingClientRect(), ratio = window.devicePixelRatio || 1;
  overlay.width = r.width * ratio; overlay.height = r.height * ratio;
  var c = overlay.getContext("2d"), s = Math.min(overlay.width / fw, overlay.height / fh),
      ox = (overlay.width - fw * s) / 2, oy = (overlay.height - fh * s) / 2;
  c.clearRect(0, 0, overlay.width, overlay.height);
  c.lineWidth = 3 * ratio;
  if (!a) {  // no marks to look for: a box to hold the sheet in
    c.setLineDash([10 * ratio, 8 * ratio]);
    c.strokeStyle = steadyFor > 1 ? "#4cd27a" : "rgba(255,255,255,.6)";
    c.strokeRect(ox + fw * 0.08 * s, oy + fh * 0.06 * s, fw * 0.84 * s, fh * 0.88 * s);
    return;
  }
  var g = a.guide, found = a.found, blink = Math.floor(Date.now() / 400) % 2 === 0;
  g.marks.forEach(function (m, i) {
    var x = ox + m[0] * s, y = oy + m[1] * s, half = g.size * s * 0.75 + 4 * ratio;
    var inside = found[i] && found[i].inside;
    c.strokeStyle = inside ? "#4cd27a" : blink ? "#ffffff" : "rgba(255,255,255,.3)";
    c.beginPath();
    if (SHEET.shape === "ring") c.arc(x, y, half, 0, 2 * Math.PI); else c.rect(x - half, y - half, 2 * half, 2 * half);
    c.stroke();
    if (found[i]) {  // the sheet's own mark: green in its target, amber on its way
      c.fillStyle = inside ? "#4cd27a" : "#f5b942";
      c.beginPath(); c.arc(ox + found[i].x * s, oy + found[i].y * s, 6 * ratio, 0, 2 * Math.PI); c.fill();
    }
  });
  if (a.all) {
    c.strokeStyle = "#4cd27a";
    c.lineWidth = 2 * ratio; c.beginPath();
    found.forEach(function (f, i) { c[i ? "lineTo" : "moveTo"](ox + f.x * s, oy + f.y * s); });
    c.closePath(); c.stroke();
  }
}

// What the debug readout shows: each mark found or why not, and each check against what it needs.
var NAMES = ["top left", "top right", "bottom right", "bottom left"];
function details(a, fw, fh) {
  var lines = ["camera " + video.videoWidth + "×" + video.videoHeight + ", judged at " + fw + "×" + fh +
               ", " + rate.toFixed(1) + " checks/s", "light " + Math.round(a.bright)];
  if (!a.guide) {
    lines.push("change " + a.change.toFixed(1) + " (still under " + ANY_STILL + "), edges " + a.edges.toFixed(1) +
               " (sharp over " + ANY_SHARP + ")");
    return lines.join("\\n");
  }
  a.seen.forEach(function (f, i) {
    var line = NAMES[i] + ": ";
    if (!f.score && f.score !== 0) line += "✗ " + f.why;
    else {
      line += (a.found[i] ? (a.found[i].inside ? "✓ in" : "~ off") : "✗ " + f.why) + ", " +
        Math.round(Math.hypot(f.x - a.guide.marks[i][0], f.y - a.guide.marks[i][1])) + "px from target (in under " +
        Math.round(a.tol) + "), mark " + f.score.toFixed(2) + " (over " + MIN_MARK + "), edge " + f.edge.toFixed(2);
    }
    lines.push(line);
  });
  lines.push("shape " + (a.shape ? a.shape.toFixed(2) : "–") + " (under " + MAX_SHAPE + ")" +
             ", moved " + (a.moved === null ? "–" : a.moved.toFixed(1)) + "px (still under " +
             (STILL * fw).toFixed(1) + "), sharp " + (a.sharpness === null ? "–" : a.sharpness.toFixed(2)) +
             " (over " + MIN_EDGE + ")");
  lines.push("steady " + steadyFor + " of " + STEADY + (armed ? "" : ", waiting for the next sheet"));
  return lines.join("\\n");
}

// Each check works on a small grey copy of the frame. With the sheet's marks: the photo is taken once all four
// corner marks are in their targets, sharp and still for STEADY checks running; then the next sheet is waited
// for (the marks gone, or the picture changed). Without them: a picture that is bright, sharp and still.
var detect = document.createElement("canvas"), STEADY = 2, ANY_STILL = 6, ANY_SHARP = 4, rate = 0, lastAt = 0;
function watch() {
  if (!live || !video.videoWidth) return;
  var now = Date.now();
  if (lastAt) rate = rate * 0.8 + 0.2 * 1000 / Math.max(1, now - lastAt);
  lastAt = now;
  var w = Math.min(DETECT_WIDTH, video.videoWidth), h = Math.round(video.videoHeight * w / video.videoWidth);
  detect.width = w; detect.height = h;
  var gc = detect.getContext("2d", { willReadFrequently: true });
  gc.drawImage(video, 0, 0, w, h);
  var d = gc.getImageData(0, 0, w, h).data, grey = new Float32Array(w * h);
  for (var i = 0; i < grey.length; i++) grey[i] = (d[4 * i] + d[4 * i + 1] + d[4 * i + 2]) / 3;
  var change = 0, edges = 0, n = 0;
  for (i = 0; i < grey.length; i += 3) {
    if (last && last.length === grey.length) change += Math.abs(grey[i] - last[i]);
    if (i % w) edges += Math.abs(grey[i] - grey[i - 1]);
    n++;
  }
  change /= n; edges /= n;
  last = grey;
  if (mode === "marks") {
    var a = assess(grey, w, h, SHEET, previous);
    previous = a;
    if (!armed && (a.found.filter(Boolean).length < 2 || change > 14)) armed = true;  // sheet taken away or changed
    steadyFor = a.ready ? steadyFor + 1 : 0;
    draw(w, h, a);
    hint.textContent = !armed ? "Put down the next sheet" : a.hint;
    if (showing) debug.textContent = details(a, w, h);
    if (armed && steadyFor >= STEADY) shoot();
    return;
  }
  var bright = brightness(grey), paper = bright > 90, still = change < ANY_STILL, sharp = edges > ANY_SHARP;
  if (!armed && change > 14) armed = true;  // the picture changed: a new sheet
  steadyFor = still && sharp && paper ? steadyFor + 1 : 0;
  draw(w, h, null);
  hint.textContent = mode === "off" ? "Press Take now for each sheet" :
    !armed ? "Put down the next sheet" : !paper ? "Need more light, or a sheet in the box" :
    !sharp ? "Hold steady to focus" : !still ? "Hold still…" : "Taking…";
  if (showing) debug.textContent = details({ bright: bright, change: change, edges: edges }, w, h);
  if (mode === "any" && armed && steadyFor >= 4) shoot();
}

// The debug readout: what the camera sees and each check's numbers, to tell why a sheet isn't taken.
var debug = document.getElementById("debug"), showing = false;
try { showing = localStorage.getItem("omr-phone-details") === "1"; } catch (e) {}
function showDetails(on) {
  showing = on; debug.hidden = !on; document.getElementById("details").classList.toggle("on", on);
  try { localStorage.setItem("omr-phone-details", on ? "1" : "0"); } catch (e) {}
}
showDetails(showing);
document.getElementById("details").addEventListener("click", function () { showDetails(!showing); });

// Auto with the marks first; Auto (any) without them keeps working for a sheet whose marks can't be found.
var MODES = SHEET ? ["marks", "any", "off"] : ["any", "off"],
    LABELS = { marks: "Auto: marks", any: "Auto: any", off: "Auto: off" }, mode = MODES[0];
autoButton.textContent = LABELS[mode];
autoButton.addEventListener("click", function () {
  mode = MODES[(MODES.indexOf(mode) + 1) % MODES.length]; autoButton.textContent = LABELS[mode]; armed = true;
});
document.getElementById("shoot").addEventListener("click", function () { armed = true; shoot(); });
document.getElementById("upload").addEventListener("change", function (e) {
  Array.prototype.forEach.call(e.target.files, function (file) {
    var img = new Image(), url = URL.createObjectURL(file);
    img.onload = function () { send(jpeg(img, img.naturalWidth, img.naturalHeight)); URL.revokeObjectURL(url); };
    img.src = url;
  });
  say("Reading…");
  e.target.value = "";
});

if (window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
  navigator.mediaDevices.getUserMedia({ audio: false, video: {
    facingMode: { ideal: "environment" }, width: { ideal: 3840 }, height: { ideal: 2160 } } })
  .then(function (stream) {
    video.srcObject = stream; video.play(); live = true; setInterval(watch, 150);
  }, function () {
    hint.textContent = "The camera wasn't allowed. Allow it in the browser, or use Photos…";
  });
} else {
  hint.textContent = "Live camera needs the secure address in the QR code. Use Photos… to take each sheet.";
  autoButton.disabled = true; document.getElementById("shoot").disabled = true;
}
window.addEventListener("beforeunload", function (e) { if (queue.length) { e.preventDefault(); e.returnValue = ""; } });
</script>
</body></html>
"""


def phone_page(exam_id: int, exam_name: str, token: str, who: str, t: Template | None = None) -> str:
    """The page for one exam; with its sheet `t`, the camera shows targets where the sheet's corner marks go."""
    sheet = {"page": list(t.page), "shape": t.marker_shape, "size": t.marker_size,
             "marks": [list(m) for m in t.markers]} if t else None
    return (PAGE.replace("__EXAM_ID__", str(int(exam_id))).replace("__TOKEN__", json.dumps(token))
            .replace("__SHEET__", json.dumps(sheet)).replace("__DETECT__", DETECT)
            .replace("__EXAM__", escape(exam_name)).replace("__WHO__", escape(who)))
