"""Visual QA: screenshot scenes in the web viewer (whole + cross-section) and tile them.

    uv run python evals/render.py jet_engine f22_raptor ...   (server must be running on :8765)
    uv run python evals/render.py --all                         every cached scene from evals/queries.json
    uv run python evals/render.py --video ID ...                also render low-quality Manim + contact sheet

Output: out/qa/<id>.png (whole | cut side by side) and out/qa/sheet.png.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QA = ROOT / "out" / "qa"
QA.mkdir(parents=True, exist_ok=True)
CHROME = shutil.which("chromium") or shutil.which("google-chrome-stable")
BASE = "http://127.0.0.1:8765"
MODE = "scene"   # or "forge" (Blender GLB scenes in out/forge/<id>)


def shot(sid: str, cut: bool) -> Path:
    out = QA / f"{sid}{'_cut' if cut else ''}.png"
    url = f"{BASE}/web/snap.html?{MODE}={sid}{'&cut=1' if cut else ''}"
    subprocess.run([CHROME, "--headless=new", "--disable-web-security", "--no-sandbox", "--hide-scrollbars", "--enable-unsafe-swiftshader",
                    "--use-angle=swiftshader", "--window-size=960,640", "--virtual-time-budget=9000",
                    f"--user-data-dir=/tmp/opto-chrome-{sid}{int(cut)}", f"--screenshot={out}", url],
                   capture_output=True, timeout=120)
    return out


def pair(sid: str) -> Path:
    a, b = shot(sid, False), shot(sid, True)
    out = QA / f"{sid}_pair.png"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(a), "-i", str(b), "-filter_complex",
                    "hstack=inputs=2", str(out)], check=True)
    return out


def video(sid: str) -> Path | None:
    if MODE == "forge":
        src = ROOT / "out" / "forge" / sid
        qual = "m"
    else:
        src = ROOT / "out" / "scenes" / f"{sid}.ndjson"
        qual = "l"
    mp4 = ROOT / "out" / "videos" / f"{sid}.mp4"
    r = subprocess.run([sys.executable, "-m", "opto.video", str(src), str(mp4), "-q", qual], cwd=ROOT,
                       capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        print(sid, "VIDEO FAILED", r.stderr[-800:])
        return None
    sheet = QA / f"{sid}_video.png"
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(mp4)], capture_output=True, text=True).stdout or 30)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(mp4), "-vf",
                    f"fps={12 / dur:.4f},scale=427:-1,tile=4x3", "-frames:v", "1", str(sheet)], check=True)
    return sheet


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--split")
    ap.add_argument("--video", action="store_true")
    ap.add_argument("--forge", action="store_true")
    a = ap.parse_args()
    global MODE
    if a.forge:
        MODE = "forge"
    ids = a.ids
    if a.all or a.split:
        qs = json.loads((ROOT / "evals" / "queries.json").read_text())
        base = ROOT / "out" / ("forge" if a.forge else "scenes")
        ids = [q["id"] for q in qs if (not a.split or q.get("split", "core") == a.split)
               and ((base / q["id"] / "scene.json").exists() if a.forge else (base / f"{q['id']}.json").exists())]
    with ThreadPoolExecutor(3) as ex:
        pairs = list(ex.map(pair, ids))
    for sid, p in zip(ids, pairs):
        print(sid, p)
    if a.video:
        for sid in ids:
            print(sid, video(sid))


if __name__ == "__main__":
    main()
