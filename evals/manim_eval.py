"""Manim eval: Kimi writes 3Blue1Brown-style videos; render and score them mechanically.

    uv run python evals/manim_eval.py [--quality l|m] [--parallel 2] [--force] [--label "..."] [ids...]

Mechanical checks are necessary, not sufficient: judge visual quality separately from the
4x4 contact sheets written to out/qa/<id>_video.png.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from opto import llm, manim_forge  # noqa: E402

DEFAULT_IDS = ["f22_raptor", "v8_engine", "falcon9_rocket", "apache_helicopter", "human_eye", "mechanical_watch"]
PRIMITIVES = ("Axes", "NumberPlane", "ParametricFunction", "ValueTracker", "always_redraw", "Transform",
              "ReplacementTransform", "Brace", "SurroundingRectangle", "Arrow", "CurvedArrow", "Arc", "Angle",
              "Polygon", "DashedLine", "Circle", "Sector")


def _called(src: str, name: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\s*\(", src) is not None


def _duration(mp4: Path) -> float | None:
    if not mp4.exists():
        return None
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)],
                           capture_output=True, text=True, timeout=30, check=True)
        dur = float(p.stdout.strip())
        return dur if dur > 0 else None
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def _contact_sheet(mp4: Path, out: Path, dur: float) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(mp4), "-vf",
                    f"fps={16 / dur:.4f},scale=427:-1,tile=4x4", "-frames:v", "1", str(out)],
                   capture_output=True, text=True, timeout=180, check=True)


def _frame_stats(mp4: Path, dur: float | None) -> tuple[list[dict], str]:
    if not mp4.exists() or not dur:
        return [], "video or duration unavailable"
    try:
        with tempfile.TemporaryDirectory(prefix="manim-eval-") as td:
            pattern = str(Path(td) / "frame_%02d.png")
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(mp4), "-vf",
                            f"fps={8 / dur:.4f},scale=160:-1", "-frames:v", "8", pattern],
                           capture_output=True, text=True, timeout=180, check=True)
            paths = sorted(Path(td).glob("frame_*.png"))[:8]
            stats = []
            for path in paths:
                with Image.open(path) as im:
                    pixels = np.asarray(im.convert("L"), dtype=np.float64)
                stats.append({"mean": round(float(pixels.mean()), 2), "std": round(float(pixels.std()), 2)})
            if len(stats) != 8:
                return stats, f"extracted {len(stats)}/8 frames"
            return stats, ""
    except (subprocess.SubprocessError, OSError) as e:
        return [], f"frame extraction failed: {str(e)[-160:]}"


def score(sid: str, rec: dict, forge_dir: Path, mp4: Path) -> dict:
    checks: dict[str, tuple[bool, str]] = {}
    attempts = rec.get("attempts") or []
    script = forge_dir / "video_scene.py"
    src = script.read_text() if script.exists() else ""
    dur = _duration(mp4)
    size = mp4.stat().st_size if mp4.exists() else 0
    runs = rec.get("ok") is True and size > 100 * 1024
    last_error = attempts[-1].get("error") if attempts and not attempts[-1].get("ok") else rec.get("error")
    checks["runs"] = (runs, f"{len(attempts)} attempt(s); mp4={size / 1024:.1f} KB; "
                            f"last error: {(str(last_error)[-160:] if last_error else 'none')!r}")
    checks["duration"] = (dur is not None and 25.0 <= dur <= 140.0,
                          f"{dur:.2f}s (need 25.0–140.0s)" if dur is not None else "duration unavailable")

    loaded = _called(src, "load_forge_model")
    focused = _called(src, "play_cutaway") or _called(src, "focus_anims")
    checks["uses_3d_model"] = (loaded and focused,
                               f"load_forge_model={loaded}, play_cutaway/focus_anims={focused}")
    primitives = [name for name in PRIMITIVES if _called(src, name)]
    math_tex = _called(src, "math_tex")
    checks["uses_manim_math"] = (math_tex and len(primitives) >= 2,
                                 f"math_tex={math_tex}; {len(primitives)} primitives: {primitives}")
    write, create = _called(src, "Write"), _called(src, "Create")
    checks["uses_write_create"] = (write and create, f"Write={write}, Create={create}")
    forbidden = [name for name in ("MathTex", "Tex", "Arrow3D") if _called(src, name)]
    checks["no_forbidden_apis"] = (not forbidden, f"forbidden calls: {forbidden or 'none'}")

    frames, frame_error = _frame_stats(mp4, dur)
    good = sum(f["mean"] > 3.5 and f["std"] > 11.0 for f in frames)
    frame_ok = len(frames) == 8 and good >= 6
    detail = frame_error or f"{good}/8 non-blank; stats={frames}"
    checks["non_blank_frames"] = (frame_ok, detail)
    passed = sum(ok for ok, _ in checks.values())
    return {"id": sid, "score": round(passed / len(checks), 3), "pass": passed == len(checks),
            "duration": round(dur, 2) if dur is not None else None,
            "checks": {k: {"ok": ok, "detail": detail} for k, (ok, detail) in checks.items()}}


def _att_rows(rec: dict) -> list[dict]:
    rows = []
    for a in rec.get("attempts") or []:
        st = a.get("stats") or {}
        rows.append({k: a.get(k) for k in ("ok", "render_s", "lines")} |
                    {"ttft": st.get("ttft"), "tokens": st.get("completion_tokens"),
                     "err": a.get("error") or st.get("error")})
    return rows


async def one(sid: str, sem: asyncio.Semaphore, a: argparse.Namespace) -> dict:
    forge_dir = ROOT / "out" / "forge" / sid
    mp4 = ROOT / "out" / "videos" / f"{sid}.mp4"
    mp4.parent.mkdir(parents=True, exist_ok=True)
    async with sem:
        t0 = time.time()
        try:
            rec = await manim_forge.forge_video(forge_dir, mp4, quality=a.quality, force=a.force)
        except Exception as e:
            rec = {"ok": False, "attempts": [], "error": f"{type(e).__name__}: {e}"}
    wall = time.time() - t0
    dur = _duration(mp4)
    if rec.get("ok") and dur:
        try:
            await asyncio.to_thread(_contact_sheet, mp4, ROOT / "out" / "qa" / f"{sid}_video.png", dur)
        except (subprocess.SubprocessError, OSError) as e:
            print(f"{sid}: contact sheet failed: {e}", flush=True)
    r = score(sid, rec, forge_dir, mp4)
    r["wall"] = round(wall, 1)
    r["attempts"] = _att_rows(rec)
    fails = [k for k, v in r["checks"].items() if not v["ok"]]
    print(f"{sid:26s} score={r['score']:.2f} pass={r['pass']!s:5s} attempts={len(r['attempts'])} "
          f"duration={r['duration']}s wall={r['wall']}s fails={fails}", flush=True)
    return r


def summarize(run_dir: Path, results: list[dict], label: str, quality: str) -> None:
    results.sort(key=lambda r: r["id"])
    n = len(results)
    first_try = sum(1 for r in results if r["attempts"] and r["attempts"][0]["ok"])
    rep = {"run": run_dir.name, "label": label, "backend": llm.BACKEND, "model": llm.KIMI, "quality": quality,
           "n": n, "pass_rate": round(sum(r["pass"] for r in results) / max(1, n), 3),
           "mean_score": round(sum(r["score"] for r in results) / max(1, n), 3),
           "first_try_runs": first_try, "first_try_run_rate": round(first_try / max(1, n), 3), "results": results}
    (run_dir / "report.json").write_text(json.dumps(rep, indent=1))
    lines = [f"# Manim eval {run_dir.name} — {label}", "",
             f"backend `{llm.BACKEND}`, model `{llm.KIMI}`, quality `{quality}`; pass **{rep['pass_rate']:.0%}**, "
             f"mean score **{rep['mean_score']:.2f}**, scripts that ran first try: "
             f"**{first_try}/{n} ({rep['first_try_run_rate']:.0%})**", "",
             "| id | score | duration s | attempts | wall s | failed checks |",
             "|---|---|---|---|---|---|"]
    for r in results:
        bad = [f"{k}: {v['detail']}" for k, v in r["checks"].items() if not v["ok"]]
        dur = f"{r['duration']:.2f}" if r["duration"] is not None else "—"
        lines.append(f"| {r['id']} | {r['score']:.2f} | {dur} | {len(r['attempts'])} | {r['wall']} | "
                     f"{'<br>'.join(bad) or '—'} |")
    text = "\n".join(lines) + "\n"
    (run_dir / "summary.md").write_text(text)
    print(text, end="")


async def main_async(a: argparse.Namespace) -> None:
    ids = a.ids or DEFAULT_IDS
    run_dir = ROOT / "out" / "evals" / f"manim-{time.strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(a.parallel)
    results = await asyncio.gather(*[one(sid, sem, a) for sid in ids])
    summarize(run_dir, list(results), a.label, a.quality)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--quality", choices=["l", "m"], default="m")
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--label", default="")
    asyncio.run(main_async(ap.parse_args()))
