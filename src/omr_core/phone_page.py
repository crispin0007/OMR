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
header { padding: 10px 14px; background: #1d2330; }
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
</style></head>
<body><main>
<header><b>__EXAM__</b><span>__WHO__</span></header>
<div id="view">
  <video id="video" playsinline muted></video>
  <canvas id="overlay"></canvas>
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
var EXAM = __EXAM_ID__, TOKEN = __TOKEN__, SHEET = __SHEET__;
var video = document.getElementById("video"), hint = document.getElementById("hint"),
    overlay = document.getElementById("overlay"), result = document.getElementById("result"),
    autoButton = document.getElementById("auto"), count = document.getElementById("count").firstChild;
var armed = true, steadyFor = 0, last = null, sent = 0, queue = [], sending = false, live = false;

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

// Where the sheet's corner marks should be in a frame `fw` x `fh` pixels: the page fitted in the picture with a
// margin, as the targets are drawn. (frame pixels per mm, mark size in pixels, mark centres)
function guide(fw, fh) {
  var k = Math.min(0.86 * fw / SHEET.page[0], 0.86 * fh / SHEET.page[1]);
  var ox = (fw - SHEET.page[0] * k) / 2, oy = (fh - SHEET.page[1] * k) / 2;
  return { k: k, size: SHEET.size * k,
           marks: SHEET.marks.map(function (p) { return [ox + p[0] * k, oy + p[1] * k]; }) };
}

// The dark blob the size of a corner mark nearest (cx, cy), within `reach` pixels, or null. Dark is well under
// the brightness around it; a mark is about as wide as tall and about `size` across (a ring's box is the
// ring's). Filled bubbles are smaller and the orientation bar is long, so neither passes.
function findMark(grey, w, h, cx, cy, size, reach) {
  var x0 = Math.max(0, Math.round(cx - reach)), x1 = Math.min(w, Math.round(cx + reach)),
      y0 = Math.max(0, Math.round(cy - reach)), y1 = Math.min(h, Math.round(cy + reach));
  if (x1 - x0 < 4 || y1 - y0 < 4) return null;
  var ww = x1 - x0, sum = 0, x, y;
  for (y = y0; y < y1; y++) for (x = x0; x < x1; x++) sum += grey[y * w + x];
  var mean = sum / (ww * (y1 - y0)), dark = mean * 0.55, seen = new Uint8Array(ww * (y1 - y0)), best = null;
  if (mean < 50) return null;  // too dark to tell
  for (y = y0; y < y1; y++) for (x = x0; x < x1; x++) {
    if (seen[(y - y0) * ww + x - x0] || grey[y * w + x] > dark) continue;
    var stack = [x, y], bx0 = x, bx1 = x, by0 = y, by1 = y, count = 0;
    seen[(y - y0) * ww + x - x0] = 1;
    while (stack.length) {
      var py = stack.pop(), px = stack.pop();
      count++;
      if (px < bx0) bx0 = px; if (px > bx1) bx1 = px; if (py < by0) by0 = py; if (py > by1) by1 = py;
      for (var k = 0; k < 4; k++) {
        var qx = px + (k === 0 ? 1 : k === 1 ? -1 : 0), qy = py + (k === 2 ? 1 : k === 3 ? -1 : 0);
        if (qx < x0 || qx >= x1 || qy < y0 || qy >= y1) continue;
        var q = (qy - y0) * ww + qx - x0;
        if (!seen[q] && grey[qy * w + qx] <= dark) { seen[q] = 1; stack.push(qx, qy); }
      }
    }
    var bw = bx1 - bx0 + 1, bh = by1 - by0 + 1;
    if (bw < size * 0.5 || bw > size * 1.9 || bh < size * 0.5 || bh > size * 1.9 || bw > bh * 1.6
        || bh > bw * 1.6 || count < bw * bh * 0.25) continue;
    var mx = (bx0 + bx1) / 2, my = (by0 + by1) / 2, off = Math.hypot(mx - cx, my - cy);
    if (!best || off < best.off) best = { x: mx, y: my, off: off, edge: edge(grey, w, by0, by1, bx0, bx1, mean) };
  }
  return best;
}

// How sharp a mark's edge is: the steepest step across its left and right edges as a share of the step from
// the paper to the mark. A blurred or shaken picture spreads the step over several pixels.
function edge(grey, w, by0, by1, bx0, bx1, paper) {
  var y = Math.round((by0 + by1) / 2), ink = Math.min(grey[y * w + bx0 + 1], grey[y * w + bx1 - 1]), steep = 0;
  for (var x = Math.max(1, bx0 - 3); x <= bx0 + 2; x++) steep = Math.max(steep, grey[y * w + x - 1] - grey[y * w + x]);
  for (x = bx1 - 2; x <= Math.min(w - 2, bx1 + 3); x++) steep = Math.max(steep, grey[y * w + x + 1] - grey[y * w + x]);
  return steep / Math.max(1, paper - ink);
}

// What to do to line the sheet up, from the marks found (null where one isn't) and where they should be.
function advice(found, want, reach, bright) {
  var have = [], should = [], dx = 0, dy = 0;
  found.forEach(function (f, i) {
    if (f) { have.push(f); should.push({ x: want[i][0], y: want[i][1] }); dx += f.x - want[i][0]; dy += f.y - want[i][1]; }
  });
  if (bright < 70) return "Need more light";
  if (have.length < 2) return "Line up the sheet's four corner marks with the targets";
  dx /= have.length; dy /= have.length;
  var spread = function (ps) {
    var d = 0; for (var i = 1; i < ps.length; i++) d += Math.hypot(ps[i].x - ps[0].x, ps[i].y - ps[0].y); return d;
  };
  var ratio = spread(have) / spread(should);
  if (ratio < 0.92) return "Move the phone closer";
  if (ratio > 1.08) return "Move the phone back a little";
  // the sheet shows to the right of its targets when the phone is too far left
  if (Math.abs(dx) > reach * 0.3) return dx > 0 ? "Move the phone right" : "Move the phone left";
  if (Math.abs(dy) > reach * 0.3) return dy > 0 ? "Move the phone down" : "Move the phone up";
  if (have.length === 4) return "Hold the phone flat over the sheet";
  return "Line up the marks still out of their targets";
}

// The targets and the marks found, over the picture: frame pixel (x, y) is drawn where the video shows it.
function draw(fw, fh, g, found) {
  var r = overlay.getBoundingClientRect(), ratio = window.devicePixelRatio || 1;
  overlay.width = r.width * ratio; overlay.height = r.height * ratio;
  var c = overlay.getContext("2d"), s = Math.min(overlay.width / fw, overlay.height / fh),
      ox = (overlay.width - fw * s) / 2, oy = (overlay.height - fh * s) / 2;
  c.clearRect(0, 0, overlay.width, overlay.height);
  c.lineWidth = 3 * ratio;
  if (!g) {  // no marks to look for: a box to hold the sheet in
    c.setLineDash([10 * ratio, 8 * ratio]);
    c.strokeStyle = steadyFor > 1 ? "#4cd27a" : "rgba(255,255,255,.6)";
    c.strokeRect(ox + fw * 0.08 * s, oy + fh * 0.06 * s, fw * 0.84 * s, fh * 0.88 * s);
    return;
  }
  var blink = Math.floor(Date.now() / 400) % 2 === 0;
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
  if (found.every(function (f) { return f && f.inside; })) {
    c.strokeStyle = "#4cd27a";
    c.lineWidth = 2 * ratio; c.beginPath();
    found.forEach(function (f, i) { c[i ? "lineTo" : "moveTo"](ox + f.x * s, oy + f.y * s); });
    c.closePath(); c.stroke();
  }
}

// Auto with the sheet's marks: the photo is taken once all four corner marks sit in their targets, sharp and
// still; then the next sheet is waited for (the marks gone, or the picture changed). Auto without them: a
// picture that is bright, sharp and has stayed still. Both judge a small copy of the frame.
var detect = document.createElement("canvas");
function watch() {
  if (!live || !video.videoWidth) return;
  var w = 480, h = Math.round(video.videoHeight * w / video.videoWidth);
  detect.width = w; detect.height = h;
  var gc = detect.getContext("2d", { willReadFrequently: true });
  gc.drawImage(video, 0, 0, w, h);
  var d = gc.getImageData(0, 0, w, h).data, grey = new Float32Array(w * h);
  for (var i = 0; i < grey.length; i++) grey[i] = (d[4 * i] + d[4 * i + 1] + d[4 * i + 2]) / 3;
  var change = 0, edges = 0, bright = 0, n = 0;
  for (i = 0; i < grey.length; i += 3) {
    if (last) change += Math.abs(grey[i] - last[i]);
    if (i % w) edges += Math.abs(grey[i] - grey[i - 1]);
    bright += grey[i]; n++;
  }
  change /= n; edges /= n; bright /= n;
  last = grey;
  var still = change < 4, sharp = edges > 6;
  if (mode === "marks") {
    var g = guide(w, h), reach = Math.max(g.size * 1.6, 0.09 * w);
    var found = g.marks.map(function (m) { return findMark(grey, w, h, m[0], m[1], g.size, reach); });
    var tol = Math.max(g.size * 0.9, 0.04 * w);
    found.forEach(function (f, i) { if (f) f.inside = Math.hypot(f.x - g.marks[i][0], f.y - g.marks[i][1]) < tol; });
    var all = found.every(function (f) { return f && f.inside; });
    sharp = all && found.every(function (f) { return f.edge > 0.3; });
    if (!armed && (found.filter(Boolean).length < 2 || change > 14)) armed = true;  // sheet taken away or changed
    steadyFor = all && still && sharp ? steadyFor + 1 : 0;
    draw(w, h, g, found);
    hint.textContent = !armed ? "Put down the next sheet" : !all ? advice(found, g.marks, reach, bright) :
      !sharp ? "Hold steady to focus" : !still ? "Hold still…" : "Taking…";
    if (armed && steadyFor >= 3) shoot();
    return;
  }
  var paper = bright > 90;
  if (!armed && change > 14) armed = true;  // the picture changed: a new sheet
  steadyFor = still && sharp && paper ? steadyFor + 1 : 0;
  draw(w, h, null, null);
  hint.textContent = mode === "off" ? "Press Take now for each sheet" :
    !armed ? "Put down the next sheet" : !paper ? "Need more light, or a sheet in the box" :
    !sharp ? "Hold steady to focus" : !still ? "Hold still…" : "Taking…";
  if (mode === "any" && armed && steadyFor >= 4) shoot();
}

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
    video.srcObject = stream; video.play(); live = true; setInterval(watch, 200);
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
            .replace("__SHEET__", json.dumps(sheet))
            .replace("__EXAM__", escape(exam_name)).replace("__WHO__", escape(who)))
