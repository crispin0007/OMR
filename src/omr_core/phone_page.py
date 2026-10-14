"""The page a phone opens from the PC's QR code to photograph sheets (specs/006-phone-scanning). It is served by
the PC itself; nothing is loaded from the internet.

With a secure (https) address the camera runs live and takes each sheet by itself once the picture is sharp and
still, then waits for the next sheet to be put down. Without one, or when the camera can't be used, the phone's
own camera takes the photos through the upload button. Each photo is sent with an id of its own and resent until
the PC answers, so a photo is never lost to a dropped Wi-Fi nor saved twice."""

import json
from html import escape

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
#frame { position: absolute; inset: 6% 8%; border: 3px dashed rgba(255,255,255,.55); border-radius: 10px; pointer-events: none; }
#frame.steady { border-color: #4cd27a; border-style: solid; }
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
  <div id="frame"></div>
  <div id="hint">Starting the camera…</div>
</div>
<div id="result">Hold the phone over a sheet, with all four corner marks inside the box.</div>
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
var EXAM = __EXAM_ID__, TOKEN = __TOKEN__;
var video = document.getElementById("video"), hint = document.getElementById("hint"),
    frame = document.getElementById("frame"), result = document.getElementById("result"),
    autoButton = document.getElementById("auto"), count = document.getElementById("count").firstChild;
var auto = true, armed = true, steadyFor = 0, last = null, sent = 0, queue = [], sending = false, live = false;
var small = document.createElement("canvas"); small.width = 96; small.height = 128;

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

// Auto: a picture that is sharp and has stayed still is taken; then the next is waited for, which is a
// change in the picture (a new sheet put down) followed by stillness again.
function watch() {
  if (!live || !video.videoWidth) return;
  var g = small.getContext("2d", { willReadFrequently: true });
  g.drawImage(video, 0, 0, small.width, small.height);
  var d = g.getImageData(0, 0, small.width, small.height).data, grey = new Float32Array(small.width * small.height);
  for (var i = 0; i < grey.length; i++) grey[i] = (d[4 * i] + d[4 * i + 1] + d[4 * i + 2]) / 3;
  var change = 0, edges = 0, bright = 0;
  for (i = 0; i < grey.length; i++) {
    if (last) change += Math.abs(grey[i] - last[i]);
    if (i % small.width) edges += Math.abs(grey[i] - grey[i - 1]);
    bright += grey[i];
  }
  change /= grey.length; edges /= grey.length; bright /= grey.length;
  last = grey;
  var still = change < 4, sharp = edges > 6, paper = bright > 90;
  if (!armed && change > 14) armed = true;  // the picture changed: a new sheet
  steadyFor = still && sharp && paper ? steadyFor + 1 : 0;
  frame.className = steadyFor > 1 ? "steady" : "";
  hint.textContent = !auto ? "Press Take now for each sheet" :
    !armed ? "Put down the next sheet" : !paper ? "Need more light, or a sheet in the box" :
    !sharp ? "Hold steady to focus" : !still ? "Hold still…" : "Taking…";
  if (auto && armed && steadyFor >= 4) shoot();
}

autoButton.addEventListener("click", function () {
  auto = !auto; autoButton.textContent = "Auto: " + (auto ? "on" : "off"); armed = true;
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


def phone_page(exam_id: int, exam_name: str, token: str, who: str) -> str:
    return (PAGE.replace("__EXAM_ID__", str(int(exam_id))).replace("__TOKEN__", json.dumps(token))
            .replace("__EXAM__", escape(exam_name)).replace("__WHO__", escape(who)))
