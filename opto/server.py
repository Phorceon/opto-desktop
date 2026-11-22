"""Opto web server.

    uv run python -m opto.server            # http://127.0.0.1:8765

GET  /                      the app
GET  /api/scene?q=&mode=&image_id=  SSE stream: status / item / draft_final / final
POST /api/upload            {"image":"data:image/...;base64,..."} -> {"image_id","url"}
POST /api/capture           capture current screen -> {"image_id","url"}
GET  /api/scenes            cached scenes
GET  /api/scene/{id}        one cached scene
POST /api/ask               {"scene_id","part_id","question"?} -> {"answer","stats"}
POST /api/video             {"scene_id","quality"} -> {"job","state"?,"url"?}
GET  /api/video/{job}       {"state","url"?,"error"?}
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import os
import re
import sys
import time
import uuid
from pathlib import Path

from PIL import Image
from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import forge as forge_mod
from . import generate as gen
from . import llm, prompts, research, visual_qa

ROOT = Path(__file__).resolve().parent.parent
VIDEOS = ROOT / "out" / "videos"
UPLOADS = ROOT / "out" / "uploads"
VIDEOS.mkdir(parents=True, exist_ok=True)
UPLOADS.mkdir(parents=True, exist_ok=True)
JOBS: dict[str, dict] = {}
ACTIVE_VIDEO_JOBS: dict[str, str] = {}


def sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data)}


def _save_image_bytes(raw_bytes: bytes) -> tuple[str, Path]:
    with Image.open(io.BytesIO(raw_bytes)) as src:
        im = src.convert("RGB")
        im.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
        image_id = uuid.uuid4().hex[:12]
        dst = UPLOADS / f"{image_id}.jpg"
        im.save(dst, format="JPEG", quality=88, optimize=True)
    return image_id, dst


def _image_data_url(image_id: str | None) -> str | None:
    if not image_id or not re.fullmatch(r"[a-f0-9]{8,24}", image_id):
        return None
    p = UPLOADS / f"{image_id}.jpg"
    if not p.is_file():
        return None
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


async def upload_image(request: Request):
    try:
        body = await request.json()
        data_url = str(body.get("image") or "")
        if "," in data_url:
            data_url = data_url.split(",", 1)[1]
        raw = base64.b64decode(data_url)
        if not raw or len(raw) > 25 * 1024 * 1024:
            return JSONResponse({"error": "invalid or oversized image"}, status_code=400)
        image_id, _ = await asyncio.to_thread(_save_image_bytes, raw)
        return JSONResponse({"image_id": image_id, "url": f"/out/uploads/{image_id}.jpg"})
    except Exception as exc:
        return JSONResponse({"error": f"upload failed: {exc}"}, status_code=400)


async def capture_screen(request: Request):
    def _grab() -> tuple[str, Path]:
        if sys.platform == "darwin":
            import subprocess
            import tempfile
            tmp = Path(tempfile.gettempdir()) / f"opto_cap_{uuid.uuid4().hex[:8]}.jpg"
            try:
                subprocess.run(["screencapture", "-x", "-t", "jpg", str(tmp)], check=True, timeout=15)
                return _save_image_bytes(tmp.read_bytes())
            finally:
                tmp.unlink(missing_ok=True)
        from PIL import ImageGrab
        shot = ImageGrab.grab(all_screens=False)
        buf = io.BytesIO()
        shot.convert("RGB").save(buf, format="JPEG", quality=90)
        return _save_image_bytes(buf.getvalue())

    try:
        image_id, _ = await asyncio.to_thread(_grab)
        return JSONResponse({"image_id": image_id, "url": f"/out/uploads/{image_id}.jpg"})
    except Exception as exc:
        return JSONResponse({"error": f"screen capture failed: {exc}"}, status_code=500)


async def scene_stream(request: Request):
    q = (request.query_params.get("q") or "").strip()[:400]
    image_id = (request.query_params.get("image_id") or "").strip() or None
    image_url = _image_data_url(image_id)
    if image_id and not image_url:
        return JSONResponse({"error": "unknown image_id"}, status_code=404)
    if not q and image_url:
        q = "Explain how the object shown in this image works"
    if not q:
        return JSONResponse({"error": "missing q"}, status_code=400)

    mode = request.query_params.get("mode", os.environ.get("OPTO_MODE", "kimi"))
    mode = "kimi"  # Kimi K3.1 only (multimodal + text)
    fresh = request.query_params.get("fresh") == "1"
    sid = gen.slug(q, image_id=image_id)

    async def events():
        t0 = time.time()
        hit = None if fresh else gen.cached(sid)
        if hit:
            yield sse("status", {"phase": "cache", "id": sid, "model": hit["stats"].get("model")})
            for item in schema_items(hit["scene"]):
                yield sse("item", item)
            yield sse("final", {"id": sid, "scene": hit["scene"], "stats": hit["stats"], "cached": True,
                                "errors": hit.get("errors", []), "wall": round(time.time() - t0, 3)})
            return

        active_model = llm.KIMI
        yield sse("status", {"phase": "queued", "id": sid, "model": active_model,
                             "mode": mode, "multimodal": bool(image_url)})
        queue: asyncio.Queue = asyncio.Queue()

        # web reference (Wikipedia facts + real photos) for named, real-world things;
        # skipped when the user attached their own image
        ref = None
        if not image_url:
            yield sse("status", {"phase": "research", "query": research.subject_of(q)})
            ref = await research.lookup(q)
            yield sse("status", {"phase": "research_done", "title": ref.title, "url": ref.url,
                                 "images": len(ref.images)})

        async def run(model: str, tag: str, img: str | None = None):
            llm.ON_RETRY.set(lambda info: queue.put_nowait((tag, {"t": "retry", **info})))
            try:
                async for item in gen.stream_scene(q, model=model, image_url=img, reference=ref):
                    await queue.put((tag, item))
            except Exception as e:
                await queue.put((tag, {"t": "error", "error": repr(e)}))
            await queue.put((tag, None))

        tasks: list[asyncio.Task] = [asyncio.create_task(run(llm.KIMI, "primary", image_url))]
        live: set[str] = {"primary"}

        primary_started = False
        try:
            while live:
                tag, item = await queue.get()
                if item is None:
                    live.discard(tag)
                    continue
                if await request.is_disconnected():
                    break
                if item["t"] == "error":
                    yield sse("status", {"phase": "error", "source": tag, "error": item["error"]})
                    continue
                if item["t"] == "retry":
                    yield sse("status", {"phase": "retry", "source": tag, **{k: v for k, v in item.items() if k != "t"}})
                    continue
                if tag == "draft":
                    if primary_started:
                        continue
                    if item["t"] == "final":
                        scene = gen.scene_from_final(item)
                        if scene.parts:
                            gen.save(sid, q, scene, item["raw"], item["stats"], story=item.get("story"))
                        yield sse("draft_final", {
                            "id": sid, "scene": item["scene"], "stats": item["stats"],
                            "errors": item["errors"], "wall": round(time.time() - t0, 3),
                        })
                        yield sse("status", {"phase": "draft_done", "stats": item["stats"]})
                    else:
                        yield sse("item", {**item, "draft": True})
                    continue
                if not primary_started:
                    primary_started = True
                    yield sse("status", {"phase": "streaming", "model": active_model,
                                         "since_request": round(time.time() - t0, 2)})
                    if mode == "hybrid" and not image_url:
                        yield sse("reset", {"reason": "kimi_refine"})
                if item["t"] == "final":
                    scene = gen.scene_from_final(item)
                    if scene.parts:
                        gen.save(sid, q, scene, item["raw"], item["stats"], story=item.get("story"))
                    yield sse("final", {"id": sid, "scene": item["scene"], "stats": item["stats"],
                                        "errors": item["errors"], "cached": False,
                                        "wall": round(time.time() - t0, 3)})
                else:
                    yield sse("item", item)
        finally:
            for t in tasks:
                t.cancel()

    return EventSourceResponse(events(), ping=10)


def forge_record(sid: str) -> dict | None:
    p = forge_mod.FORGE / sid / "record.json"
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if d.get("scene") else None
    return None


async def forge_stream(request: Request):
    """Kimi writes Blender code -> sandboxed Blender -> GLB. SSE: status / final / error."""
    q = (request.query_params.get("q") or "").strip()[:400]
    fresh = request.query_params.get("fresh") == "1"
    if not q:
        return JSONResponse({"error": "missing q"}, status_code=400)
    sid = forge_mod.slug(q)

    async def events():
        t0 = time.time()
        hit = None if fresh else forge_record(sid)
        if hit:
            yield sse("final", {"id": sid, "scene": hit["scene"], "glb": f"/out/forge/{sid}/model.glb",
                                "cached": True, "attempts": hit.get("attempts", []), "wall": round(time.time() - t0, 3)})
            return
        queue: asyncio.Queue = asyncio.Queue()

        async def on_event(ev):
            ev["elapsed"] = round(time.time() - t0, 1)
            await queue.put(("status", ev))

        async def run():
            try:
                rec = await forge_mod.forge(q, sid=sid, on_event=on_event)
                await queue.put(("done", rec))
            except Exception as e:
                await queue.put(("done", {"scene": None, "error": repr(e), "attempts": []}))

        task = asyncio.create_task(run())
        yield sse("status", {"phase": "queued", "id": sid, "model": llm.KIMI, "backend": llm.BACKEND})
        try:
            while True:
                kind, payload = await queue.get()
                if kind == "status":
                    yield sse("status", payload)
                    continue
                if payload.get("scene"):
                    yield sse("final", {"id": sid, "scene": payload["scene"], "glb": f"/out/forge/{sid}/model.glb?v={int(time.time())}",
                                        "cached": False, "attempts": payload["attempts"], "wall": round(time.time() - t0, 1)})
                else:
                    yield sse("error", {"id": sid, "error": payload.get("error", "unknown")[-1500:],
                                        "attempts": payload.get("attempts", [])})
                break
        finally:
            if not task.done():
                task.cancel()

    return EventSourceResponse(events(), ping=10)


def schema_items(scene: dict):
    yield {"t": "meta", "title": scene["title"], "subtitle": scene["subtitle"],
           "cut": scene["cut"], "camera": scene["camera"]}
    for k, t in (("parts", "part"), ("arrows", "arrow"), ("labels", "label"), ("beats", "beat")):
        for x in scene.get(k, []):
            yield {"t": t, **x}


async def list_scenes(request: Request):
    out = []
    for d in sorted(forge_mod.FORGE.glob("*/record.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            r = json.loads(d.read_text(encoding="utf-8"))
            if r.get("scene"):
                out.append({"id": r["id"], "query": r["query"], "title": r["scene"]["title"], "kind": "forge",
                            "parts": len(r["scene"]["parts"]), "created": r.get("created"),
                            "video": (VIDEOS / f"{r['id']}.mp4").exists()})
        except Exception:
            continue
    for p in sorted(gen.SCENES.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({"id": d["id"], "query": d["query"], "title": d["scene"]["title"],
                        "parts": len(d["scene"]["parts"]), "created": d.get("created"),
                        "video": (VIDEOS / f"{d['id']}.mp4").exists()})
        except Exception:
            continue
    return JSONResponse(out)


async def get_scene(request: Request):
    sid = request.path_params["sid"]
    d = forge_record(sid) or gen.cached(sid)
    return JSONResponse(d) if d else JSONResponse({"error": "not found"}, status_code=404)


def neighbours(scene: dict, part: dict, k: int = 6) -> list[str]:
    def c(p):
        if "pos" in p:
            return p["pos"]
        return [(a + b) / 2 for a, b in zip(p.get("bbox_min", [0, 0, 0]), p.get("bbox_max", [0, 0, 0]))]
    others = sorted((p for p in scene["parts"] if p["id"] != part["id"]),
                    key=lambda p: math.dist(c(p), c(part)))
    return [p["name"] for p in others[:k]]


async def ask(request: Request):
    body = await request.json()
    sid = body.get("scene_id", "")
    pid = body.get("part_id")
    candidates = [x for x in (forge_record(sid), gen.cached(sid)) if x]
    if not candidates:
        return JSONResponse({"error": "unknown scene"}, status_code=404)
    d, part = None, None
    for cand in candidates:
        hit = next((p for p in cand["scene"]["parts"] if p["id"] == pid), None)
        if hit:
            d, part = cand, hit
            break
    if not part:
        return JSONResponse({"error": "unknown part"}, status_code=404)
    st = llm.Stats(llm.KIMI)
    answer = await llm.acomplete(prompts.ask_messages(d["scene"]["title"], part, neighbours(d["scene"], part),
                                                      body.get("question")), model=llm.KIMI, max_tokens=1500, stats=st)
    return JSONResponse({"answer": answer.strip() or part.get("info", ""), "part": part, "stats": st.as_dict()})


async def video_start(request: Request):
    body = await request.json()
    sid = body.get("scene_id", "")
    quality = body.get("quality", "l") if body.get("quality") in ("l", "m", "h") else "l"
    force = bool(body.get("force", False))
    src = gen.SCENES / f"{sid}.ndjson"
    if forge_record(sid):
        src = forge_mod.FORGE / sid
    elif not src.exists():
        return JSONResponse({"error": "unknown scene"}, status_code=404)

    out = VIDEOS / f"{sid}.mp4"
    if out.exists() and not force:
        job = uuid.uuid4().hex[:10]
        url = f"/out/videos/{out.name}?v={int(out.stat().st_mtime)}"
        JOBS[job] = {"state": "done", "scene_id": sid, "url": url, "cached": True, "seconds": 0.0}
        return JSONResponse({"job": job, "state": "done", "url": url, "cached": True})

    existing_job = ACTIVE_VIDEO_JOBS.get(sid)
    if existing_job and JOBS.get(existing_job, {}).get("state") == "rendering":
        return JSONResponse({"job": existing_job, "state": "rendering"})

    job = uuid.uuid4().hex[:10]
    JOBS[job] = {"state": "rendering", "scene_id": sid, "started": time.time()}
    ACTIVE_VIDEO_JOBS[sid] = job

    async def run():
        mod = "opto.manim_forge" if src.is_dir() else "opto.video"
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        env.setdefault("OPTO_BACKEND", "openclaw")
        ffmpeg_path = visual_qa.find_tool("ffmpeg")
        if Path(ffmpeg_path).is_file():
            ffmpeg_dir = str(Path(ffmpeg_path).parent)
            cur_path = env.get("PATH", "")
            if ffmpeg_dir.lower() not in cur_path.lower():
                env["PATH"] = ffmpeg_dir + os.pathsep + cur_path
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", mod, str(src), str(out), "-q", quality,
                cwd=str(ROOT), env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, err = await proc.communicate()
            if proc.returncode == 0 and out.exists():
                JOBS[job].update(state="done", url=f"/out/videos/{out.name}?v={int(time.time())}",
                                 seconds=round(time.time() - JOBS[job]["started"], 1))
            else:
                JOBS[job].update(state="error", error=err.decode(errors="replace")[-1500:])
        finally:
            if ACTIVE_VIDEO_JOBS.get(sid) == job:
                ACTIVE_VIDEO_JOBS.pop(sid, None)

    asyncio.create_task(run())
    return JSONResponse({"job": job, "state": "rendering"})


async def video_status(request: Request):
    j = JOBS.get(request.path_params["job"])
    return JSONResponse(j or {"state": "unknown"})


async def index(request: Request):
    return FileResponse(ROOT / "web" / "index.html")


app = Starlette(routes=[
    Route("/", index),
    Route("/api/scene", scene_stream),
    Route("/api/upload", upload_image, methods=["POST"]),
    Route("/api/capture", capture_screen, methods=["POST"]),
    Route("/api/forge", forge_stream),
    Route("/api/scenes", list_scenes),
    Route("/api/scene/{sid}", get_scene),
    Route("/api/ask", ask, methods=["POST"]),
    Route("/api/video", video_start, methods=["POST"]),
    Route("/api/video/{job}", video_status),
    Mount("/web", StaticFiles(directory=ROOT / "web")),
    Mount("/out", StaticFiles(directory=ROOT / "out")),
])


def main() -> None:
    import uvicorn
    port = int(os.environ.get("OPTO_PORT", "8765"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
