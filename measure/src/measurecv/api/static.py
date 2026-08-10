"""The browser live-view page.

Served inline rather than from a static directory so the API stays a single
importable module with no file-path assumptions when packaged or containerised.

Why this page exists
--------------------
It is the same client for a laptop webcam and a phone camera. ``getUserMedia``
grabs frames in the browser, they go over the existing WebSocket to
``/v1/stream/ws``, and measurements come back as JSON which the page draws over
its own live video element. That means:

* the video stays at camera framerate regardless of how slow measurement is,
  because the page never waits for a reply to draw the next frame;
* a phone works with no app, no install and no platform-specific code;
* the server never needs access to the camera, so it can sit anywhere the
  browser can reach.

The one hard requirement is that ``getUserMedia`` needs a secure context.
``localhost`` counts as secure, so a laptop works over plain HTTP; a phone on
the LAN does **not**, and needs HTTPS or an SSH/ngrok tunnel. The page says so
itself rather than silently failing with a null camera.
"""

from __future__ import annotations

__all__ = ["LIVE_PAGE"]

LIVE_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>measurecv &mdash; live</title>
<style>
  :root {
    --bg: #0e1316; --panel: #161d21; --line: #2a343a;
    --ink: #e8edee; --ink-2: #a8b6bc; --ink-3: #79888f;
    --accent: #4fbecd; --pass: #4cb782; --warn: #d99a3a; --fail: #e0736a;
    --mono: ui-monospace, "SF Mono", "Cascadia Mono", Consolas, monospace;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font: 15px/1.5 "Segoe UI", -apple-system, system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  header {
    display: flex; align-items: center; gap: .75rem; flex-wrap: wrap;
    padding: .7rem 1rem; border-bottom: 1px solid var(--line); background: var(--panel);
    position: sticky; top: 0; z-index: 10;
  }
  h1 { font-size: .95rem; font-weight: 600; margin: 0; letter-spacing: -.01em; }
  h1 span { color: var(--accent); font-family: var(--mono); font-size: .8rem; }
  .spacer { flex: 1; }
  button {
    font: 600 .82rem var(--mono); letter-spacing: .04em; text-transform: uppercase;
    padding: .45rem .85rem; border-radius: 3px; cursor: pointer;
    background: var(--accent); color: #08262c; border: 0;
  }
  button.ghost { background: transparent; color: var(--ink-2); border: 1px solid var(--line); }
  button:disabled { opacity: .4; cursor: not-allowed; }
  button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  select {
    font: .8rem var(--mono); background: var(--bg); color: var(--ink);
    border: 1px solid var(--line); border-radius: 3px; padding: .4rem .5rem; max-width: 42vw;
  }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ink-3); flex: none; }
  .dot.on { background: var(--pass); box-shadow: 0 0 0 3px rgba(76,183,130,.18); }
  .dot.err { background: var(--fail); }

  main { display: grid; grid-template-columns: minmax(0,1fr) 340px; gap: 1rem; padding: 1rem; }
  @media (max-width: 900px) { main { grid-template-columns: 1fr; } }

  .stage { position: relative; background: #000; border: 1px solid var(--line);
           border-radius: 4px; overflow: hidden; aspect-ratio: 4/3; }
  video, canvas.overlay { position: absolute; inset: 0; width: 100%; height: 100%; }
  video { object-fit: contain; }
  canvas.overlay { pointer-events: none; }
  .hud {
    position: absolute; left: 0; top: 0; padding: .3rem .6rem; background: rgba(10,14,16,.82);
    font: .7rem var(--mono); color: var(--ink-2); letter-spacing: .04em;
    border-bottom-right-radius: 4px;
  }
  .banner {
    position: absolute; right: 0; top: 0; padding: .3rem .6rem;
    background: #8c2b24; color: #fff; font: 600 .7rem var(--mono); letter-spacing: .06em;
  }

  aside { display: flex; flex-direction: column; gap: .75rem; min-width: 0; }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 4px; padding: .85rem; }
  .card h2 { margin: 0 0 .6rem; font: 600 .68rem var(--mono); letter-spacing: .12em;
             text-transform: uppercase; color: var(--ink-3); }
  .stats { display: grid; grid-template-columns: 1fr 1fr; gap: .55rem .8rem; }
  .stats div { min-width: 0; }
  .stats dt { font: .64rem var(--mono); letter-spacing: .08em; text-transform: uppercase;
              color: var(--ink-3); }
  .stats dd { margin: .1rem 0 0; font: 600 1rem var(--mono); font-variant-numeric: tabular-nums; }
  .obj { border-top: 1px solid var(--line); padding: .55rem 0; }
  .obj:first-of-type { border-top: 0; }
  .obj-head { display: flex; align-items: baseline; gap: .5rem; }
  .obj-name { font-weight: 600; font-size: .88rem; }
  .chip { margin-left: auto; font: 600 .68rem var(--mono); padding: .1rem .4rem; border-radius: 2px; }
  .chip.hi { color: var(--pass); background: rgba(76,183,130,.15); }
  .chip.mid { color: var(--warn); background: rgba(217,154,58,.15); }
  .chip.lo { color: var(--fail); background: rgba(224,115,106,.15); }
  .dims { font: .8rem var(--mono); font-variant-numeric: tabular-nums; color: var(--ink-2);
          margin-top: .2rem; }
  .warn { font-size: .72rem; color: var(--warn); margin-top: .25rem; }
  .empty { color: var(--ink-3); font-size: .85rem; }
  .note { font-size: .75rem; color: var(--ink-3); line-height: 1.45; }
  .note code { font-family: var(--mono); color: var(--ink-2); }
  .error { color: var(--fail); font-size: .8rem; }
</style>
</head>
<body>
<header>
  <span class="dot" id="dot"></span>
  <h1>measurecv <span>live</span></h1>
  <select id="cameras" aria-label="Camera"></select>
  <div class="spacer"></div>
  <button id="start">Start</button>
  <button id="stop" class="ghost" disabled>Stop</button>
</header>

<main>
  <div class="stage">
    <video id="video" playsinline muted autoplay></video>
    <canvas id="overlay" class="overlay"></canvas>
    <div class="hud" id="hud">idle</div>
    <div class="banner" id="banner" hidden>UNCALIBRATED</div>
  </div>

  <aside>
    <div class="card">
      <h2>Session</h2>
      <dl class="stats">
        <div><dt>video</dt><dd id="s-video">&mdash;</dd></div>
        <div><dt>measure</dt><dd id="s-rate">&mdash;</dd></div>
        <div><dt>latency</dt><dd id="s-lat">&mdash;</dd></div>
        <div><dt>objects</dt><dd id="s-objs">&mdash;</dd></div>
      </dl>
    </div>
    <div class="card" id="results-card">
      <h2>Measurements</h2>
      <div id="results"><p class="empty">Press Start and allow camera access.</p></div>
    </div>
    <div class="card">
      <h2>Accuracy</h2>
      <p class="note" id="calibnote">
        Without calibration, absolute scale rests on an assumed field of view &mdash;
        roughly &plusmn;15%. Run <code>measurecv calibrate</code> once for this camera
        to reach 1&ndash;2%.
      </p>
    </div>
  </aside>
</main>

<script>
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const video = $("video"), overlay = $("overlay"), ctx = overlay.getContext("2d");
  const send = document.createElement("canvas"), sctx = send.getContext("2d");

  let ws = null, stream = null, running = false, inFlight = false;
  let measured = 0, lastAt = 0, lastScene = null, latency = 0, rate = 0;
  let frames = 0, fpsAt = performance.now(), vfps = 0;

  const SEND_W = 640;               // what the server measures
  const palette = (i) => `hsl(${(i * 137.5) % 360} 70% 62%)`;

  function setStatus(state, text) {
    $("dot").className = "dot" + (state ? " " + state : "");
    $("hud").textContent = text;
  }

  async function listCameras() {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const cams = devices.filter((d) => d.kind === "videoinput");
      $("cameras").innerHTML = cams
        .map((c, i) => `<option value="${c.deviceId}">${c.label || "Camera " + (i + 1)}</option>`)
        .join("");
    } catch (_) { /* labels need permission; refreshed after start */ }
  }

  async function start() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus("err", "camera unavailable");
      $("results").innerHTML =
        '<p class="error">This browser exposes no camera API. On a phone, the page must be ' +
        'served over HTTPS &mdash; getUserMedia is blocked on plain HTTP outside localhost.</p>';
      return;
    }
    try {
      const deviceId = $("cameras").value;
      stream = await navigator.mediaDevices.getUserMedia({
        video: deviceId
          ? { deviceId: { exact: deviceId }, width: { ideal: 1280 } }
          : { facingMode: { ideal: "environment" }, width: { ideal: 1280 } },
        audio: false,
      });
    } catch (err) {
      setStatus("err", "camera denied");
      $("results").innerHTML = `<p class="error">Camera error: ${err.name}. ` +
        `Grant permission, and make sure the page is on HTTPS or localhost.</p>`;
      return;
    }

    video.srcObject = stream;
    await video.play();
    await listCameras();

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/v1/stream/ws`);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => { running = true; setStatus("on", "connected"); pump(); };
    ws.onclose = () => { running = false; setStatus("", "disconnected"); };
    ws.onerror = () => setStatus("err", "socket error");
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (_) { return; }
      if (msg.type === "error") { setStatus("err", msg.message || "error"); inFlight = false; return; }
      if (msg.type !== "measurement") return;

      inFlight = false;
      measured += 1;
      const now = performance.now();
      latency = now - lastAt;
      rate = measured / ((now - fpsStart) / 1000);
      lastScene = msg;
      render(msg);
    };

    $("start").disabled = true; $("stop").disabled = false;
  }

  function stop() {
    running = false;
    if (ws) { ws.close(); ws = null; }
    if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    $("start").disabled = false; $("stop").disabled = true;
    setStatus("", "stopped");
  }

  let fpsStart = performance.now();

  function pump() {
    if (!running) return;
    frames += 1;
    const now = performance.now();
    if (now - fpsAt > 1000) { vfps = frames * 1000 / (now - fpsAt); frames = 0; fpsAt = now; }

    // Draw the last overlay every animation frame so video stays smooth
    // regardless of measurement latency.
    if (lastScene) drawOverlay(lastScene);
    updateStats();

    // One frame in flight at a time: queueing would only grow latency.
    if (!inFlight && ws && ws.readyState === WebSocket.OPEN && video.videoWidth) {
      inFlight = true;
      lastAt = now;
      const scale = SEND_W / video.videoWidth;
      send.width = SEND_W;
      send.height = Math.round(video.videoHeight * scale);
      sctx.drawImage(video, 0, 0, send.width, send.height);
      send.toBlob(
        (blob) => {
          if (!blob || !ws || ws.readyState !== WebSocket.OPEN) { inFlight = false; return; }
          blob.arrayBuffer().then((buf) => ws.send(buf));
        },
        "image/jpeg", 0.8
      );
    }
    requestAnimationFrame(pump);
  }

  function drawOverlay(scene) {
    const vw = video.videoWidth, vh = video.videoHeight;
    if (!vw) return;
    // Match the canvas to the letterboxed video box, not the element box.
    const box = video.getBoundingClientRect();
    const scale = Math.min(box.width / vw, box.height / vh);
    const dw = vw * scale, dh = vh * scale;
    const ox = (box.width - dw) / 2, oy = (box.height - dh) / 2;

    if (overlay.width !== Math.round(box.width) || overlay.height !== Math.round(box.height)) {
      overlay.width = Math.round(box.width); overlay.height = Math.round(box.height);
    }
    ctx.clearRect(0, 0, overlay.width, overlay.height);

    const sx = dw / scene.image_size.width, sy = dh / scene.image_size.height;
    ctx.font = "600 12px ui-monospace, Consolas, monospace";
    ctx.textBaseline = "top";

    scene.objects.forEach((o, i) => {
      const [x1, y1, x2, y2] = o.detection.bbox;
      const X = ox + x1 * sx, Y = oy + y1 * sy, W = (x2 - x1) * sx, H = (y2 - y1) * sy;
      const colour = palette(o.detection.track_id ?? i);

      ctx.lineWidth = o.confidence >= 0.5 ? 2 : 1;
      ctx.strokeStyle = colour;
      ctx.strokeRect(X, Y, W, H);

      const d = o.dimensions;
      const text = d
        ? `${o.detection.label} ${d.length.value.toFixed(2)}x${d.width.value.toFixed(2)}x${d.height.value.toFixed(2)}m`
        : `${o.detection.label} (not measurable)`;
      const tw = ctx.measureText(text).width + 10;
      ctx.fillStyle = "rgba(12,16,18,.85)";
      ctx.fillRect(X, Math.max(0, Y - 18), tw, 18);
      ctx.fillStyle = colour;
      ctx.fillText(text, X + 5, Math.max(0, Y - 18) + 3);
    });
  }

  function updateStats() {
    $("s-video").textContent = vfps ? vfps.toFixed(0) + " fps" : "\\u2014";
    $("s-rate").textContent = rate ? rate.toFixed(2) + " fps" : "\\u2014";
    $("s-lat").textContent = latency ? (latency / 1000).toFixed(1) + " s" : "\\u2014";
    $("s-objs").textContent = lastScene ? lastScene.objects.length : "\\u2014";
    if (running) {
      const age = lastAt ? ((performance.now() - lastAt) / 1000).toFixed(1) : "0.0";
      setStatus("on", `video ${vfps.toFixed(0)}fps | measure ${rate.toFixed(2)}fps | ${age}s`);
    }
  }

  function render(scene) {
    $("banner").hidden = scene.calibration_source !== "assumed_fov";
    const measurable = scene.objects.filter((o) => o.dimensions);
    if (!scene.objects.length) {
      $("results").innerHTML = '<p class="empty">No objects detected.</p>';
      return;
    }
    $("results").innerHTML = scene.objects.map((o) => {
      const c = o.confidence;
      const cls = c >= 0.7 ? "hi" : c >= 0.5 ? "mid" : "lo";
      const d = o.dimensions;
      const dims = d
        ? `${d.length.value.toFixed(3)} &times; ${d.width.value.toFixed(3)} &times; ${d.height.value.toFixed(3)} m`
        : "not measurable";
      const dist = o.distance ? ` &middot; ${o.distance.value.toFixed(2)} m away` : "";
      const warn = o.warnings.length
        ? `<div class="warn">${o.warnings[0].replace(/</g, "&lt;")}</div>` : "";
      return `<div class="obj"><div class="obj-head">
          <span class="obj-name">${o.detection.label.replace(/</g, "&lt;")}</span>
          <span class="chip ${cls}">${Math.round(c * 100)}%</span>
        </div><div class="dims">${dims}${dist}</div>${warn}</div>`;
    }).join("");
  }

  $("start").addEventListener("click", start);
  $("stop").addEventListener("click", stop);
  window.addEventListener("beforeunload", stop);
  listCameras();
  if (!window.isSecureContext) {
    $("calibnote").insertAdjacentHTML("afterend",
      '<p class="error" style="margin:.5rem 0 0">This page is not a secure context, so the ' +
      'browser will block camera access. Use localhost, HTTPS, or a tunnel.</p>');
  }
})();
</script>
</body>
</html>
"""
