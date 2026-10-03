#!/usr/bin/env python3
"""Render a demo video of the deployed Cordon site by slow-motion frame capture.

Why this exists
---------------
The only thing worth showing is the page's own adjudicated-run replay, which is JS-driven and
animates on load. Hand screen-recording it works fine; this reproduces it frame-accurately and can
be re-run whenever the site changes.

The three problems that shape the implementation
------------------------------------------------
1. Screenshots are slow. A full-page 1600x900 JPEG costs ~380 ms on this host, i.e. ~2.6 fps.
   Capturing at 15 fps and encoding at 15 fps would make the replay play ~6x too fast.

2. So the page's timers are slowed by SLOWMO before load, and the capture loop advances its own
   timeline by (wall_elapsed / SLOWMO). Everything -- the staged replay and the scrolling -- is then
   captured in slow motion.

3. ffmpeg is given `measured_capture_fps * SLOWMO`, which restores true 1x playback. The rate is
   measured during the run, not hardcoded, because it varies with load.

One subtlety that silently ruins the output: calling window.scrollTo() on every frame re-triggers
the replay (an in-view observer restarts it), so the animation appears frozen at COMMITTING for the
whole shot. Scrolls are therefore only issued when the target position actually changes.

This produces a SILENT walkthrough, not a narrated screen recording.

Usage:
    python scripts/make_demo_video.py --check
    python scripts/make_demo_video.py --probe
    python scripts/make_demo_video.py --out demo/cordon-demo.mp4
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WIDTH, HEIGHT = 1600, 900
SLOWMO = 6.0          # page timers are stretched by this factor; ffmpeg fps compensates by it
TOTAL_S = 40.0        # video seconds
JPEG_QUALITY = 92
CASE_PATH = "/case/live-drain-run2"

# Scroll offsets measured from the production layout. Rerun --probe after a restyle.
SHOT_PROBLEM = 300
SHOT_FIG1 = 728
SHOT_CASE = 1224
SHOT_LIMITS = 2428
SHOT_CONSOLE = 2931

# (video_seconds, scroll_y). Interpolated between keys.
TIMELINE = [
    (0.0, 0),
    (2.5, 0),
    (5.0, SHOT_PROBLEM),
    (6.2, SHOT_FIG1),
    (19.0, SHOT_FIG1),   # long hold: the replay is ~6 s of real time, 36 s slowed
    (23.0, SHOT_CASE),
    (27.5, SHOT_CASE),
    (30.0, SHOT_LIMITS),
    (33.0, SHOT_LIMITS),
    (35.0, SHOT_CONSOLE),
    (38.0, SHOT_CONSOLE),
    (40.0, SHOT_CONSOLE),
]
RELOAD_AT = 6.25       # reload while already at FIG. 1 so the replay starts on camera
CASE_AT = 34.0         # cut to the live shareable case for the closing shot


def find_chromium() -> str | None:
    """Prefer a chromium already on disk over triggering a ~150 MB download."""
    root = Path(os.path.expanduser("~")) / ".cache" / "ms-playwright"
    if not root.is_dir():
        return None
    for pat in (
        "chromium-*/chrome-linux64/chrome",
        "chromium-*/chrome-linux/chrome",
        "chromium_headless_shell-*/chrome-linux*/headless_shell",
    ):
        for m in sorted(root.glob(pat), reverse=True):
            if os.access(m, os.X_OK):
                return str(m)
    return None


def timer_slowmo_script(slowmo: float) -> str:
    """Stretch setTimeout/setInterval delays before any page script runs."""
    return f"""
    (() => {{
      const S = {slowmo};
      const _t = window.setTimeout, _i = window.setInterval;
      window.setTimeout  = function (fn, d, ...a) {{ return _t.call(window, fn, d == null ? d : d * S, ...a); }};
      window.setInterval = function (fn, d, ...a) {{ return _i.call(window, fn, d == null ? d : d * S, ...a); }};
    }})();
    """


def scroll_for(vt: float) -> int:
    if vt <= TIMELINE[0][0]:
        return TIMELINE[0][1]
    for (t0, y0), (t1, y1) in zip(TIMELINE, TIMELINE[1:]):
        if t0 <= vt <= t1:
            if t1 == t0:
                return y1
            return int(round(y0 + (y1 - y0) * (vt - t0) / (t1 - t0)))
    return TIMELINE[-1][1]


def capture(url: str, out_dir: Path, slowmo: float) -> int:
    from playwright.sync_api import sync_playwright

    exe = find_chromium()
    if exe is None:
        sys.exit("no chromium under ~/.cache/ms-playwright -- python -m playwright install chromium")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=exe, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        page.add_init_script(timer_slowmo_script(slowmo))
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)

        def shot(i: int) -> None:
            page.screenshot(
                path=str(out_dir / f"f{i:05d}.jpg"), type="jpeg", quality=JPEG_QUALITY
            )

        i = 0
        vt = 0.0
        last_y: int | None = None
        reloaded = False
        on_case = False
        t_wall = time.time()

        while vt < TOTAL_S:
            if not on_case and vt >= CASE_AT:
                page.goto(
                    url.rstrip("/") + CASE_PATH, wait_until="domcontentloaded", timeout=90_000
                )
                on_case = True
                last_y = None
                shot(i)
                i += 1
                vt += (time.time() - t_wall) / slowmo
                t_wall = time.time()
                continue

            if not reloaded and vt >= RELOAD_AT:
                page.evaluate("window.scrollTo(0, %d)" % SHOT_FIG1)
                page.reload(wait_until="domcontentloaded", timeout=90_000)
                last_y = None
                reloaded = True

            y = 0 if on_case else scroll_for(vt)
            if y != last_y:            # only on change -- see module docstring
                page.evaluate("(y) => window.scrollTo(0, y)", y)
                last_y = y

            shot(i)
            i += 1
            vt += (time.time() - t_wall) / slowmo
            t_wall = time.time()

        browser.close()

    return i


def encode(out_dir: Path, out: Path, n: int, fps: float) -> None:
    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg not found on PATH")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-framerate", f"{fps:.3f}",
        "-i", str(out_dir / "f%05d.jpg"),
        "-c:v", "libx264", "-preset", "medium", "-crf", "21",
        "-pix_fmt", "yuv420p",
        "-vf", "tpad=stop_mode=clone:stop_duration=1.2",
        "-movflags", "+faststart",
        str(out),
    ]
    subprocess.run(cmd, check=True)


def probe(url: str) -> None:
    from playwright.sync_api import sync_playwright

    exe = find_chromium()
    if exe is None:
        sys.exit("no chromium found -- python -m playwright install chromium")
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=["--no-sandbox", "--disable-dev-shm-usage"])
        pg = b.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        pg.goto(url, wait_until="domcontentloaded", timeout=90_000)
        print("page height:", pg.evaluate("document.body.scrollHeight"))
        rows = pg.evaluate(
            """() => {
              const out = [];
              document.querySelectorAll('section, [id]').forEach(el => {
                const r = el.getBoundingClientRect();
                const t = (el.innerText||'').trim().slice(0,48).replace(/\\s+/g,' ');
                if (t) out.push({id: el.id || el.tagName, top: Math.round(r.top+window.scrollY), t});
              });
              return out;
            }"""
        )
        for r in rows:
            print(f"  {r['id']:<16} top={r['top']:<6} {r['t']}")
        b.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://cordon-oxunify.vercel.app")
    ap.add_argument("--out", default="demo/cordon-demo.mp4")
    ap.add_argument("--slowmo", type=float, default=SLOWMO)
    ap.add_argument("--keep-frames", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if args.check:
        print("chromium  :", find_chromium() or "NOT FOUND")
        print("ffmpeg    :", shutil.which("ffmpeg") or "NOT FOUND")
        try:
            import playwright  # noqa: F401
            print("playwright: installed")
        except ImportError:
            print("playwright: NOT INSTALLED (pip install playwright)")
        print(f"plan      : {WIDTH}x{HEIGHT}, slowmo={args.slowmo}, {TOTAL_S}s target")
        return 0

    if args.probe:
        probe(args.url)
        return 0

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="cordon-frames-"))

    try:
        n = capture(args.url, tmp, args.slowmo)
        if n < 2:
            sys.exit("captured fewer than 2 frames")
        # ffmpeg fps = capture rate * slowmo  ->  restores 1x playback of the slowed page
        fps = n / TOTAL_S
        print(f"captured {n} frames; encoding at {fps:.2f} fps")
        encode(tmp, out, n, fps)
        dur = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
            capture_output=True, text=True,
        ).stdout.strip()
        print(f"wrote {out}  ({out.stat().st_size/1_048_576:.2f} MB, {dur}s)")
    finally:
        if args.keep_frames:
            print(f"frames kept in {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())