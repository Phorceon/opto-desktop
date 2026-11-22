"""Kimi-written 3Blue1Brown-style Manim scenes, rendered and repaired locally.

Kimi K3.1 writes a real Manim Python script for a forged scene. The script is
rendered with Manim's OpenGL renderer, checked with ffprobe, and sent back to
Kimi for repair when rendering fails.

    uv run python -m opto.manim_forge out/forge/SCENE_ID out/forge/SCENE_ID/video.mp4
    uv run python -m opto.manim_forge FORGE_DIR OUT_MP4 -q h --force --repairs 2
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import llm, prompts_manim, visual_qa

ROOT = Path(__file__).resolve().parent.parent
MIN_DURATION = 8.0
QUALITIES = {"l": "low_quality", "m": "medium_quality", "h": "high_quality"}

# Executed in a fresh interpreter. OPTO_SCENE_DIR identifies the script; argv
# identifies the requested deliverable and render quality.
_RUNNER = r'''
import importlib.util
import os
import shutil
import sys
from pathlib import Path

from manim import ThreeDScene, tempconfig

scene_dir = Path(os.environ["OPTO_SCENE_DIR"])
script = scene_dir / "video_scene.py"
out_mp4 = Path(sys.argv[1]).resolve()
quality = sys.argv[2]

spec = importlib.util.spec_from_file_location("opto_forged_video_scene", script)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Could not load Manim scene script: {script}")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

scene_classes = [
    value for value in module.__dict__.values()
    if isinstance(value, type)
    and value is not ThreeDScene
    and issubclass(value, ThreeDScene)
    and value.__module__ == module.__name__
]
preferred = module.__dict__.get("OptoEpisode")
scene_class = preferred if preferred in scene_classes else (
    scene_classes[0] if scene_classes else None
)
if scene_class is None:
    raise RuntimeError(
        "video_scene.py defines no ThreeDScene subclass. Define OptoEpisode(ThreeDScene)."
    )

with tempconfig({
    "renderer": "opengl", "write_to_movie": True, "format": "mp4",
    "quality": {"l": "low_quality", "m": "medium_quality", "h": "high_quality"}[quality],
    "media_dir": str(out_mp4.parent / ".manim" / f"{out_mp4.stem}_{quality}"),
    "output_file": out_mp4.stem, "disable_caching": True,
    "verbosity": "WARNING", "progress_bar": "none", "preview": False,
    "background_color": "#000000",
}):
    sc = scene_class()
    sc.render()
    movie_file_path = sc.renderer.file_writer.movie_file_path

if not movie_file_path:
    raise RuntimeError("Manim completed without producing a movie file path.")
movie_file_path = Path(movie_file_path)
if not movie_file_path.exists():
    raise RuntimeError(f"Manim reported a movie path that does not exist: {movie_file_path}")
out_mp4.parent.mkdir(parents=True, exist_ok=True)
if movie_file_path.resolve() != out_mp4:
    shutil.move(str(movie_file_path), str(out_mp4))
print(out_mp4)
'''


def extract_code(text: str) -> str:
    """Return the largest fenced Python block, or the raw text if unfenced."""
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    if blocks:
        return max(blocks, key=len)
    return text.strip()


def _cap(text: str, limit: int = 2500) -> str:
    text = (text or "Manim failed without an error message.").strip()
    if len(text) <= limit:
        return text
    marker = "\n...[truncated]...\n"
    keep = limit - len(marker)
    left = keep // 2
    return text[:left] + marker + text[-(keep - left):]


def _compact_error(output: str) -> str:
    """Keep the last traceback, emphasizing frames from video_scene.py."""
    raw = (output or "").strip()
    if not raw:
        return "Manim failed without an error message."
    tail = raw[-20000:]
    marker = "Traceback (most recent call last):"
    start = tail.rfind(marker)
    if start < 0:
        return _cap(tail)

    traceback_text = tail[start:]
    lines = traceback_text.splitlines()
    focused: list[str] = []
    included: set[int] = set()
    for i, line in enumerate(lines):
        if "video_scene.py" in line:
            for j in (i, i + 1):
                if j < len(lines) and j not in included:
                    included.add(j)
                    focused.append(lines[j])

    if focused:
        exception = next((line.strip() for line in reversed(lines) if line.strip()), "")
        compact = "\n".join([marker, *focused])
        if exception and exception not in compact:
            compact += "\n" + exception
        return _cap(compact)
    return _cap(traceback_text)


_find_tool = visual_qa.find_tool


def _kill_process_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, check=False, timeout=15,
            )
        except OSError:
            pass
        try:
            proc.kill()
        except OSError:
            pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _probe_duration(mp4: Path) -> tuple[float | None, str]:
    try:
        proc = subprocess.run(
            [_find_tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(mp4)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
        )
    except subprocess.TimeoutExpired:
        return None, "ffprobe timed out while checking the rendered MP4."
    except OSError as exc:
        return None, f"Could not run ffprobe: {exc}"
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        return None, f"ffprobe could not read {mp4}: {detail or f'exit {proc.returncode}'}"
    try:
        duration = float(proc.stdout.strip().splitlines()[0])
        if not math.isfinite(duration):
            raise ValueError("non-finite duration")
    except (ValueError, IndexError) as exc:
        return None, f"ffprobe returned no valid duration for {mp4}: {exc}"
    if duration < MIN_DURATION:
        return None, (
            f"Rendered video is only {duration:.2f}s; it must be at least "
            f"{MIN_DURATION:.1f}s. Make the episode longer, not merely a static title card."
        )
    return duration, ""


def run_manim_script(
    code: str,
    forge_dir: Path,
    out_mp4: Path,
    quality: str = "l",
    timeout: int = 360,
) -> dict:
    """Write and render one scene, returning render stats or a compact error."""
    started = time.monotonic()
    forge_dir = Path(forge_dir).resolve()
    out_mp4 = Path(out_mp4).resolve()
    try:
        forge_dir.mkdir(parents=True, exist_ok=True)
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        (forge_dir / "video_scene.py").write_text(code, encoding="utf-8")
        if out_mp4.exists():
            out_mp4.unlink()
    except OSError as exc:
        return {"ok": False, "seconds": round(time.monotonic() - started, 2),
                "error": _cap(f"Could not prepare the Manim render: {exc}")}

    if quality not in QUALITIES:
        return {"ok": False, "seconds": round(time.monotonic() - started, 2),
                "error": f"Unknown Manim quality {quality!r}; expected l, m, or h."}

    cmd = [sys.executable, "-c", _RUNNER, str(out_mp4), quality]
    env = {**os.environ, "OPTO_SCENE_DIR": str(forge_dir.resolve()), "PYTHONIOENCODING": "utf-8"}
    ffmpeg_path = _find_tool("ffmpeg")
    if Path(ffmpeg_path).is_file():
        ffmpeg_dir = str(Path(ffmpeg_path).parent)
        cur_path = env.get("PATH", "")
        if ffmpeg_dir.lower() not in cur_path.lower():
            env["PATH"] = ffmpeg_dir + os.pathsep + cur_path

    popen_kwargs: dict = dict(
        cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
    except OSError as exc:
        return {"ok": False, "seconds": round(time.monotonic() - started, 2),
                "error": _cap(f"Could not start Manim: {exc}")}

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        stdout, stderr = proc.communicate()
        detail = _compact_error((stdout or "") + "\n" + (stderr or ""))
        message = f"Manim timed out after {timeout}s; the process group was killed."
        if detail and detail != "Manim failed without an error message.":
            message += "\n" + detail
        return {"ok": False, "seconds": round(time.monotonic() - started, 2),
                "error": _cap(message)}

    elapsed = round(time.monotonic() - started, 2)
    combined = (stdout or "") + "\n" + (stderr or "")
    if proc.returncode != 0:
        return {"ok": False, "seconds": elapsed, "error": _compact_error(combined)}
    if not out_mp4.exists():
        message = f"Manim exited successfully but did not produce {out_mp4}."
        if combined.strip():
            message += "\n" + _compact_error(combined)
        return {"ok": False, "seconds": elapsed, "error": _cap(message)}

    duration, problem = _probe_duration(out_mp4)
    if duration is None:
        return {"ok": False, "seconds": elapsed, "error": _cap(problem)}
    return {"ok": True, "seconds": elapsed, "duration": duration, "mp4": str(out_mp4)}


async def forge_video(
    forge_dir: str | Path,
    out_mp4: str | Path,
    quality: str = "m",
    repairs: int = 2,
    force: bool = False,
    visual_repairs: int = 2,
    visual_qa_existing: bool = False,
    on_event=None,
) -> dict:
    """Generate/reuse a Manim script, repair tracebacks, and let Kimi rewatch & fix visual defects."""
    forge_dir = Path(forge_dir).resolve()
    out_mp4 = Path(out_mp4).resolve()
    forge_dir.mkdir(parents=True, exist_ok=True)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    scene_data = json.loads((forge_dir / "scene.json").read_text(encoding="utf-8"))
    sid = forge_dir.name
    attempts: list[dict] = []
    qa_history: list[dict] = []

    def finish(res: dict | None, error: str = "") -> dict:
        ok = bool(res and res.get("ok"))
        rec = {
            "id": sid,
            "ok": ok,
            "mp4": str(res["mp4"]) if ok else str(out_mp4),
            "duration": res.get("duration") if ok and res else None,
            "attempts": attempts,
            "visual_qa_rounds": qa_history,
            "visual_qa": qa_history[-1] if qa_history else None,
            "backend": llm.BACKEND,
            "model": llm.KIMI,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if not ok:
            rec["error"] = error or "Manim video generation failed."
        (forge_dir / "video_record.json").write_text(
            json.dumps(rec, indent=1), encoding="utf-8"
        )
        return rec

    script_path = forge_dir / "video_scene.py"
    visual_fixes_left = max(0, visual_repairs)
    messages = prompts_manim.messages(scene_data, str(forge_dir))
    last_good_code: str | None = None

    if not force and script_path.exists():
        existing_code = script_path.read_text(encoding="utf-8")
        if on_event:
            await on_event({"phase": "manim", "attempt": 0, "existing": True,
                            "lines": existing_code.count("\n") + 1})
        verify_q = "l" if (visual_qa_existing and quality != "l") else quality
        verify_mp4 = (forge_dir / "video_visual_round0.mp4") if verify_q != quality else out_mp4
        res = await asyncio.to_thread(
            run_manim_script, existing_code, forge_dir, verify_mp4, verify_q
        )
        attempts.append({
            "stats": {}, "render_s": res["seconds"], "ok": res["ok"],
            "error": res.get("error", ""), "lines": existing_code.count("\n") + 1,
        })
        if res["ok"]:
            last_good_code = existing_code
            qa = await visual_qa.ainspect_video(verify_mp4, forge_dir / "video_qa_round0.png")
            qa_history.append(qa)
            print(f"[manim_forge] {sid} rewatch round 0: ok={qa['ok']} issues={qa['issues']}", flush=True)
            if not visual_qa_existing or qa["ok"] or visual_fixes_left == 0 or not qa.get("issues"):
                if verify_mp4 != out_mp4:
                    res = await asyncio.to_thread(
                        run_manim_script, existing_code, forge_dir, out_mp4, quality
                    )
                return finish(res)
            visual_fixes_left -= 1
            messages = messages + [
                {"role": "assistant", "content": f"```python\n{existing_code}\n```"},
                {"role": "user", "content": prompts_manim.visual_repair(
                    qa["issues"],
                    visual_qa.sheet_image_url(Path(qa["sheet"])),
                    visual_qa.sheet_image_url(Path(qa["zoom_sheet"])) if qa.get("zoom_sheet") else None,
                )},
            ]
        else:
            messages = messages + [
                {"role": "assistant", "content": f"```python\n{existing_code}\n```"},
                {"role": "user", "content": prompts_manim.repair(res["error"])},
            ]

    last_error = attempts[-1]["error"] if attempts else ""
    max_iters = max(0, repairs) + max(0, visual_repairs) + 1
    for attempt in range(max_iters):
        st = llm.Stats(llm.KIMI)
        if on_event:
            await on_event({"phase": "kimi", "attempt": attempt})
        chunks: list[str] = []
        async for chunk in llm.astream(messages, max_tokens=28000, stats=st):
            chunks.append(chunk)
            if on_event and len(chunks) % 40 == 0:
                await on_event({"phase": "writing", "chars": sum(map(len, chunks))})
        code = extract_code("".join(chunks))
        if not code.strip():
            last_error = st.error or "Kimi returned empty code."
            break
        (forge_dir / f"video_attempt{attempt}.py").write_text(code, encoding="utf-8")

        if on_event:
            await on_event({"phase": "manim", "attempt": attempt,
                            "lines": code.count("\n") + 1})

        render_s = 0.0
        verify_mp4 = (forge_dir / f"video_attempt{attempt}.mp4") if quality != "l" else out_mp4
        res = await asyncio.to_thread(
            run_manim_script, code, forge_dir, verify_mp4, "l" if quality != "l" else quality
        )
        render_s += res["seconds"]

        if res["ok"]:
            last_good_code = code
            r_idx = len(qa_history)
            if on_event:
                await on_event({"phase": "visual_qa", "attempt": attempt, "round": r_idx})
            qa = await visual_qa.ainspect_video(verify_mp4, forge_dir / f"video_qa_round{r_idx}.png")
            qa_history.append(qa)
            print(f"[manim_forge] {sid} rewatch round {r_idx}: ok={qa['ok']} issues={qa['issues']}", flush=True)
            if not qa["ok"] and visual_fixes_left > 0 and qa.get("issues"):
                visual_fixes_left -= 1
                attempts.append({
                    "stats": st.as_dict(), "render_s": round(render_s, 2), "ok": True,
                    "visual_ok": False, "visual_issues": qa["issues"],
                    "lines": code.count("\n") + 1,
                })
                messages = messages + [
                    {"role": "assistant", "content": f"```python\n{code}\n```"},
                    {"role": "user", "content": prompts_manim.visual_repair(
                        qa["issues"], visual_qa.sheet_image_url(Path(qa["sheet"]))
                    )},
                ]
                continue
            if quality != "l":
                res = await asyncio.to_thread(
                    run_manim_script, code, forge_dir, out_mp4, quality
                )
                render_s += res["seconds"]
                if res["ok"]:
                    qa_final = await visual_qa.ainspect_video(out_mp4, forge_dir / "video_qa.png")
                    qa_history.append(qa_final)

        attempts.append({
            "stats": st.as_dict(), "render_s": round(render_s, 2), "ok": res["ok"],
            "visual_ok": qa_history[-1]["ok"] if qa_history else None,
            "error": res.get("error", ""), "lines": code.count("\n") + 1,
        })
        if res["ok"]:
            return finish(res)

        last_error = res.get("error", "")
        messages = messages + [
            {"role": "assistant", "content": f"```python\n{code}\n```"},
            {"role": "user", "content": prompts_manim.repair(res["error"])},
        ]

    if last_good_code is not None:
        script_path.write_text(last_good_code, encoding="utf-8")
        res = await asyncio.to_thread(run_manim_script, last_good_code, forge_dir, out_mp4, quality)
        if res["ok"]:
            return finish(res)
    return finish(None, last_error)


def render_forge_video(
    forge_dir: str | Path,
    out_mp4: str | Path,
    quality: str = "m",
    force: bool = False,
    repairs: int = 2,
    visual_repairs: int = 2,
    visual_qa_existing: bool = False,
) -> Path:
    """Synchronous integration helper for opto.video and opto.server."""
    record = asyncio.run(forge_video(
        forge_dir, out_mp4, quality=quality, repairs=repairs,
        visual_repairs=visual_repairs, force=force,
        visual_qa_existing=visual_qa_existing,
    ))
    if not record.get("ok"):
        raise RuntimeError(
            f"Manim video generation failed for {forge_dir}: "
            f"{record.get('error', 'unknown error')}"
        )
    return Path(record["mp4"])


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Forge and render a Kimi-written Manim episode.")
    parser.add_argument("forge_dir", type=Path)
    parser.add_argument("out_mp4", type=Path)
    parser.add_argument("-q", "--quality", choices=("l", "m", "h"), default="m")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--repairs", type=int, default=2)
    parser.add_argument("--visual-repairs", type=int, default=2)
    parser.add_argument("--visual-qa", action="store_true",
                        help="also run Kimi visual rewatch + repair loop on existing video_scene.py")
    args = parser.parse_args()
    result = render_forge_video(
        args.forge_dir, args.out_mp4, quality=args.quality,
        force=args.force, repairs=args.repairs,
        visual_repairs=args.visual_repairs, visual_qa_existing=args.visual_qa,
    )
    print(result)
