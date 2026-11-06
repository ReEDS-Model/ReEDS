"""Item 15 - screenshots of the running ReEDS-Proxy dashboard (Predict tab).

Needs a running server (bokeh serve .../Stage2/code/reeds_proxy.py --port 5009)
and Google Chrome. Chrome is driven headless through the DevTools protocol
with tornado's websocket client (already installed with Bokeh), so no new
dependency is needed. The default design (all dials at Md / Ref, policy IRA)
is a training run, so the dashboard shows its k-fold out-of-fold prediction,
i.e. a held-out case.

Writes figs/_dashboard_full.png (whole page), figs/dashboard_predict.png/.pdf
and figs/dashboard_ci.png/.pdf (crops at least 1600 px wide).

    python 15_dashboard_screenshots.py              # capture + crop
    python 15_dashboard_screenshots.py --crop-only  # re-crop the saved page
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from PIL import Image
from tornado.ioloop import IOLoop
from tornado.websocket import websocket_connect

HERE = Path(__file__).resolve().parent
FIGS = HERE / "figs"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
URL = "http://localhost:5009/reeds_proxy"
PORT = 9333
W, H, SCALE = 1900, 1800, 3.0
# Crop boxes in CSS pixels, measured on the default layout (system layer,
# capacity): the top stacked-bar plot with legend, the bottom CI-coloured
# stack, and the CI colour scale that sits beside the error panel.
BOX_PREDICT = (20, 146, 609, 636)
BOX_CI = (20, 1183, 609, 1664)
BOX_CI_SCALE = (478, 862, 562, 1146)


async def capture(out: Path, wait_s: int):
    tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json").read())
    page = next(t for t in tabs if t.get("type") == "page")
    ws = await websocket_connect(page["webSocketDebuggerUrl"], max_message_size=1 << 30)
    msg_id = 0

    async def call(method, **params):
        nonlocal msg_id
        msg_id += 1
        await ws.write_message(json.dumps({"id": msg_id, "method": method, "params": params}))
        while True:
            m = json.loads(await ws.read_message())
            if m.get("id") == msg_id:
                return m.get("result", {})

    await call("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=SCALE, mobile=False)
    await call("Page.navigate", url=URL)
    # wait until the Bokeh document is up (session build loads the models)
    t0 = time.time()
    ready = False
    while time.time() - t0 < wait_s and not ready:
        r = await call("Runtime.evaluate", returnByValue=True, expression=(
            "!!(window.Bokeh && Bokeh.documents.length && Bokeh.documents[0].roots().length)"))
        ready = bool(r.get("result", {}).get("value"))
        time.sleep(2)
    time.sleep(15)
    # switch the Model selector to RF (the paper's model); the server redraws
    r = await call("Runtime.evaluate", returnByValue=True, expression=("""
        (() => { let n = 0; const d = Bokeh.documents[0];
          const all = d._all_models ? Array.from(d._all_models.values())
                    : (typeof d.all_models === 'function' ? Array.from(d.all_models()) : []);
          for (const m of all) {
            if (m.options && Array.isArray(m.options) && m.options.includes('rf') && m.value !== 'rf'
                && m.options.includes('knn')) { m.value = 'rf'; n += 1; } }
          return n; })()"""))
    val = f"ready={ready}, model selects switched={r.get('result', {}).get('value')} {r.get('exceptionDetails', {}).get('exception', {}).get('description', '')[:300]}"
    time.sleep(30)
    shot = await call("Page.captureScreenshot", format="png", captureBeyondViewport=False)
    out.write_bytes(base64.b64decode(shot["data"]))
    print(f"wrote {out} after {time.time() - t0:.0f} s ({val})")
    ws.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--crop-only", action="store_true", help="re-crop the saved full page")
    ap.add_argument("--wait", type=int, default=240)
    a = ap.parse_args()
    full = FIGS / "_dashboard_full.png"
    if not a.crop_only:
        prof = tempfile.mkdtemp(prefix="chrome_cdp_")
        proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                                 f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}",
                                 f"--window-size={W},{H}", "about:blank"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(30):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version")
                    break
                except Exception:
                    time.sleep(1)
            IOLoop.current().run_sync(lambda: capture(full, a.wait), timeout=a.wait + 120)
        finally:
            proc.terminate()
    img = Image.open(full)
    s = SCALE
    px = lambda b: tuple(int(round(v * s)) for v in b)
    pred = img.crop(px(BOX_PREDICT))
    ci = img.crop(px(BOX_CI))
    scale_img = img.crop(px(BOX_CI_SCALE))
    ci.paste(scale_img, (ci.width - scale_img.width - int(10 * s), int(20 * s)))
    for crop in (pred, ci):
        # blank the blue "active tool" underline of the Bokeh toolbar (top rows only)
        top = int(16 * s)
        px_ = crop.load()
        for yy in range(top):
            for xx in range(crop.width):
                r_, g_, b_ = px_[xx, yy][:3]
                if b_ > 180 and r_ < 120 and g_ > 120:
                    px_[xx, yy] = (255, 255, 255) + tuple(px_[xx, yy][3:])
    for name, crop in (("dashboard_predict", pred), ("dashboard_ci", ci)):
        if crop.width < 1600:
            r = 1600 / crop.width
            crop = crop.resize((1600, round(crop.height * r)), Image.LANCZOS)
        crop.save(FIGS / f"{name}.png", dpi=(300, 300))
        crop.convert("RGB").save(FIGS / f"{name}.pdf", resolution=300)
        print(f"wrote figs/{name}.png ({crop.width}x{crop.height}) and .pdf")


if __name__ == "__main__":
    sys.exit(main())
