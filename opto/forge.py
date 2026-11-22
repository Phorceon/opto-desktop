"""Opto Forge: Kimi writes Blender bpy code → sandboxed headless Blender → GLB + scene.json + mesh.npz.

    uv run python -m opto.forge "how does a jet engine work?"
    uv run python -m opto.forge --file path/to/scene_script.py desk_fan_forge

Kimi's script is untrusted code. It runs under bubblewrap: no network, read-only system, the home
directory hidden (only the Blender venv and runtime are mounted read-only), a private /tmp, and only
the output directory writable; plus a wall-clock timeout. On failure the traceback goes back to Kimi
for up to two repair rounds.

Speed: a small pool of warm workers (POOL_SIZE sandboxed Blender processes that imported bpy once) runs
jobs over a JSON-lines pipe; each job resets Blender to an empty factory scene. Workers mount the whole
out/forge root writable (one-shot runs mount only their own outdir). A job that times out or crashes
kills its worker, which is respawned in the background; when no worker is free (or workers can't
start) the job falls back to the one-shot sandboxed subprocess.
"""

from __future__ import annotations

import asyncio
import atexit
import collections
import hashlib
import json
import os
import re
import shutil
import signal
import sys
import time
from pathlib import Path

from . import llm, prompts_forge

ROOT = Path(__file__).resolve().parent.parent
FORGE = ROOT / "out" / "forge"
FORGE.mkdir(parents=True, exist_ok=True)
BLENDER_PY = ROOT / ".venv-blender" / "bin" / "python"
RUNTIME = ROOT / "opto" / "forge_runtime.py"
TIMEOUT = 90
POOL_SIZE = int(os.environ.get("OPTO_FORGE_WORKERS", "2"))  # 0 disables the warm pool
MAX_JOBS_PER_WORKER = 40  # recycle workers now and then so nothing can accumulate


def slug(query: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_")[:48] or "scene"
    return f"{base}_{hashlib.sha1(query.strip().lower().encode()).hexdigest()[:6]}"


def extract_code(text: str) -> str:
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    if blocks:
        return max(blocks, key=len)
    return text.strip()


def _sandbox_base(binds: list[str]) -> list[str]:
    venv = ROOT / ".venv-blender"
    real_venv_py = Path(BLENDER_PY).resolve()
    cmd = ["bwrap", "--ro-bind", "/usr", "/usr", "--ro-bind", "/etc", "/etc",
           "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64", "--symlink", "usr/bin", "/bin",
           "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--tmpfs", str(Path.home()),
           "--ro-bind", str(venv), str(venv), "--ro-bind", str(RUNTIME), str(RUNTIME), *binds,
           "--unshare-all", "--die-with-parent", "--new-session",
           "--setenv", "HOME", "/tmp", "--setenv", "TMPDIR", "/tmp"]
    # the venv's python symlinks (twice) into uv's managed-interpreter store: mount that store read-only
    store = Path.home() / ".local" / "share" / "uv" / "python"
    if store.exists():
        cmd += ["--ro-bind", str(store), str(store)]
    elif not str(real_venv_py).startswith(str(venv)):
        cmd += ["--ro-bind", str(real_venv_py.parents[1]), str(real_venv_py.parents[1])]
    return cmd  # no session bus, no display: Blender runs fully headless


def sandbox_cmd(script: Path, outdir: Path) -> list[str]:
    """One-shot: only this script (read-only) and its outdir (writable) are visible."""
    binds = ["--ro-bind", str(script), str(script), "--bind", str(outdir), str(outdir)]
    return _sandbox_base(binds) + [str(BLENDER_PY), str(RUNTIME), str(script), str(outdir)]


def worker_cmd() -> list[str]:
    """Warm worker: the out/forge root is writable (scripts live in their outdir under it)."""
    return _sandbox_base(["--bind", str(FORGE), str(FORGE)]) + [str(BLENDER_PY), str(RUNTIME), "--worker"]


# ---------------------------------------------------------------- warm worker pool

class _Worker:
    def __init__(self, pool: "_Pool"):
        self.pool = pool
        self.proc: asyncio.subprocess.Process | None = None
        self.state = "starting"  # starting | idle | busy | dead
        self.claimed = False
        self.jobs = 0
        self.stderr: collections.deque[str] = collections.deque(maxlen=300)
        self.runtime_mtime = RUNTIME.stat().st_mtime
        self.started = asyncio.ensure_future(self._start())

    async def _start(self) -> bool:
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *worker_cmd(), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, start_new_session=True, limit=1 << 22)
            asyncio.ensure_future(self._drain())
            deadline = time.time() + 60
            while True:  # skip anything that isn't our JSON hello
                line = await asyncio.wait_for(self.proc.stdout.readline(), max(1, deadline - time.time()))
                if not line:
                    await asyncio.sleep(0.05)
                    raise RuntimeError(f"worker exited ({self.proc.returncode}): " + "".join(self.stderr)[-800:])
                try:
                    if json.loads(line).get("ready"):
                        break
                except (ValueError, AttributeError):
                    pass
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, asyncio.TimeoutError):
                exc = RuntimeError("no ready message within 60 s")
            self.pool.failed(exc)
            self.kill()
            return False
        if self.state == "starting":
            self.state = "idle"
        return True

    async def _drain(self):
        # keep the stderr pipe empty (Blender + the script print a lot); keep a tail for crash reports
        while self.proc and self.proc.stderr:
            line = await self.proc.stderr.readline()
            if not line:
                break
            self.stderr.append(line.decode(errors="replace"))

    def stale(self) -> bool:
        try:
            return RUNTIME.stat().st_mtime != self.runtime_mtime
        except OSError:
            return True

    def kill(self):
        self.state = "dead"
        if self.proc and self.proc.returncode is None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    async def run(self, script: Path, outdir: Path, timeout: float) -> dict:
        """→ {"ok", "error"?, "timings"?}; kills itself on timeout / crash / protocol garbage."""
        self.stderr.clear()
        self.jobs += 1
        try:
            self.proc.stdin.write((json.dumps({"script": str(script), "outdir": str(outdir)}) + "\n").encode())
            await self.proc.stdin.drain()
            line = await asyncio.wait_for(self.proc.stdout.readline(), timeout)
        except asyncio.TimeoutError:
            self.kill()
            return {"ok": False, "timeout": True,
                    "error": f"Timed out after {timeout:g}s (script too slow)."}
        except (BrokenPipeError, ConnectionResetError, OSError) as exc:
            self.kill()
            return {"ok": False, "error": f"Blender worker died: {exc}\n" + "".join(self.stderr)[-2500:]}
        try:
            res = json.loads(line) if line else None
        except ValueError:
            res = None
        if not isinstance(res, dict) or "ok" not in res:
            await asyncio.sleep(0.05)  # let the stderr drain catch the crash message
            self.kill()
            code = self.proc.returncode
            return {"ok": False, "error": f"Blender crashed while running the script (exit {code}).\n"
                                          + "".join(self.stderr)[-2500:]}
        left = (res.get("timings") or {}).get("leftover") or {}
        if any(left.get(k) for k in ("objects", "meshes", "materials", "curves", "parts")):
            self.kill()  # state leaked between jobs: never reuse this process
        return res


class _Pool:
    def __init__(self, loop, size: int):
        self.loop, self.size = loop, size
        self.workers: list[_Worker] = []
        self.disabled_until = 0.0

    def failed(self, exc):
        print(f"[forge] warm worker failed to start ({exc}); using one-shot runs for 60 s", file=sys.stderr)
        self.disabled_until = time.time() + 60

    def ensure(self):
        """Top the pool up to `size` live workers (spawning happens in the background)."""
        self.workers = [w for w in self.workers if w.state != "dead"]
        if time.time() < self.disabled_until:
            return
        while len(self.workers) < self.size:
            self.workers.append(_Worker(self))

    async def acquire(self) -> _Worker | None:
        self.ensure()
        for w in self.workers:
            if w.state == "idle" and w.stale():
                w.kill()
        self.ensure()
        for w in self.workers:
            if w.state == "idle":
                w.state = "busy"
                return w
        for w in self.workers:  # a worker that is still booting is ready sooner than a cold one-shot
            if w.state == "starting" and not w.claimed:
                w.claimed = True
                ok = await w.started
                w.claimed = False
                if ok and w.state == "idle":
                    w.state = "busy"
                    return w
        return None

    def release(self, w: _Worker):
        if w.state == "busy":
            if w.jobs >= MAX_JOBS_PER_WORKER or w.stale():
                w.kill()
            else:
                w.state = "idle"
        self.ensure()

    def shutdown(self):
        for w in self.workers:
            w.kill()
        self.workers = []

    async def aclose(self):
        workers, self.workers = self.workers, []
        for w in workers:
            w.kill()
            if w.proc is not None:
                await w.proc.wait()
                if w.proc.stdin:
                    w.proc.stdin.close()
                w.proc._transport.close()  # noqa: SLF001 - avoid 'Event loop is closed' noise at exit


_POOL: _Pool | None = None


def _pool() -> _Pool | None:
    global _POOL
    if POOL_SIZE <= 0 or not shutil.which("bwrap"):
        return None
    loop = asyncio.get_running_loop()
    if _POOL is None or _POOL.loop is not loop:  # asyncio.run() per call (CLI/tests): pool per loop
        if _POOL is not None:
            _POOL.shutdown()
        _POOL = _Pool(loop, POOL_SIZE)
    return _POOL


@atexit.register
def _shutdown_pool():
    if _POOL is not None:
        _POOL.shutdown()


async def warm():
    """Start the warm workers now (e.g. at server start, or while Kimi is still writing)."""
    pool = _pool()
    if pool:
        pool.ensure()


# ---------------------------------------------------------------- running scripts

async def _run_oneshot(script: Path, outdir: Path) -> dict:
    proc = await asyncio.create_subprocess_exec(*sandbox_cmd(script, outdir), stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, start_new_session=True)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), TIMEOUT)
    except asyncio.TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        return {"ok": False, "timeout": True, "error": f"Timed out after {TIMEOUT}s (script too slow)."}
    timings = {}
    for line in err.decode(errors="replace").splitlines():
        if line.startswith("opto-timings "):
            try:
                timings = json.loads(line[len("opto-timings "):])
            except ValueError:
                pass
    if proc.returncode == 0:
        return {"ok": True, "timings": timings}
    tail = err.decode(errors="replace")[-3000:] or out.decode(errors="replace")[-3000:]
    return {"ok": False, "timings": timings, "error": tail}


def _check_scene(outdir: Path) -> tuple[dict | None, str]:
    try:
        scene = json.loads((outdir / "scene.json").read_text())
    except (OSError, ValueError) as exc:
        return None, f"Runner produced no readable scene.json ({exc})."
    if not (outdir / "model.glb").exists():
        return None, "Runner produced no model.glb."
    if not (scene.get("stats") or {}).get("tris"):
        return None, ("Your script produced no mesh geometry (0 triangles after modifiers). Every visible "
                      "object must be a mesh with faces (or a curve with bevel_depth) linked into the scene.")
    if scene.get("parts") and not any(p.get("tris") for p in scene["parts"]):
        return None, "None of the part(...) registrations has any geometry: pass the mesh objects to part()."
    return scene, ""


async def run_script(code: str, outdir: Path) -> dict:
    """Execute one bpy script in the sandbox. Returns {"ok", "seconds", "error"?, "scene"?, "timings"?}."""
    outdir = Path(outdir).resolve()
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)
    script = outdir / "scene.py"
    script.write_text(code)
    t0 = time.time()
    pool = _pool() if outdir.is_relative_to(FORGE.resolve()) else None
    worker = await pool.acquire() if pool else None
    if worker is not None:
        try:
            res = await worker.run(script, outdir, TIMEOUT)
        finally:
            pool.release(worker)
        res["worker"] = True
    else:
        res = await _run_oneshot(script, outdir)
    secs = round(time.time() - t0, 2)
    out = {"ok": False, "seconds": secs}
    if res.get("timings"):
        out["timings"] = res["timings"]
    if res.get("timeout"):
        return out | {"seconds": TIMEOUT, "error": res["error"]}
    if res["ok"]:
        scene, problem = _check_scene(outdir)
        if scene is not None:
            return out | {"ok": True, "scene": scene}
        msg = problem
    else:
        msg = (outdir / "error.txt").read_text() if (outdir / "error.txt").exists() else res.get("error", "")
    return out | {"error": (msg or "Blender failed without an error message.")[-3000:]}


async def forge(query: str, sid: str | None = None, on_event=None, repairs: int = 2) -> dict:
    """Generate → run → repair. Returns a record with scene, stats, attempts."""
    sid = sid or slug(query)
    outdir = FORGE / sid
    await warm()  # workers boot while Kimi writes
    messages = prompts_forge.messages(query)
    attempts = []
    for attempt in range(repairs + 1):
        st = llm.Stats(llm.KIMI)
        if on_event:
            await on_event({"phase": "kimi", "attempt": attempt})
        chunks: list[str] = []
        async for c in llm.astream(messages, max_tokens=24000, stats=st):
            chunks.append(c)
            if on_event and len(chunks) % 40 == 0:
                await on_event({"phase": "writing", "chars": sum(map(len, chunks))})
        text = "".join(chunks)
        code = extract_code(text)
        if on_event:
            await on_event({"phase": "blender", "attempt": attempt, "lines": code.count("\n") + 1})
        res = await run_script(code, outdir)
        attempts.append({"stats": st.as_dict(), "blender_s": res["seconds"], "ok": res["ok"],
                         "error": res.get("error", "")[-600:], "lines": code.count("\n") + 1})
        (outdir / f"attempt{attempt}.py").write_text(code)
        if res["ok"]:
            rec = {"id": sid, "query": query, "scene": res["scene"], "attempts": attempts,
                   "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "backend": llm.BACKEND, "model": llm.KIMI}
            (outdir / "record.json").write_text(json.dumps(rec, indent=1))
            return rec
        if st.error and not code.strip():
            break
        messages = messages + [{"role": "assistant", "content": f"```python\n{code}\n```"},
                               {"role": "user", "content": prompts_forge.repair(res["error"])}]
    rec = {"id": sid, "query": query, "scene": None, "attempts": attempts, "error": attempts[-1]["error"],
           "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "backend": llm.BACKEND, "model": llm.KIMI}
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "record.json").write_text(json.dumps(rec, indent=1))
    return rec


async def run_file(path: str, sid: str) -> dict:
    """Run an existing script (examples/tests) without Kimi."""
    return await run_script(Path(path).read_text(), FORGE / sid)


if __name__ == "__main__":
    if sys.argv[1] == "--file":
        async def _main():
            try:
                return await run_file(sys.argv[2], sys.argv[3])
            finally:
                if _POOL is not None:
                    await _POOL.aclose()
        r = asyncio.run(_main())
        print(json.dumps({k: v for k, v in r.items() if k != "scene"}), (r.get("scene") or {}).get("stats"))
    else:
        q = " ".join(sys.argv[1:])
        r = asyncio.run(forge(q))
        print(json.dumps({"id": r["id"], "ok": r["scene"] is not None, "attempts": r["attempts"]}, indent=1)[:3000])
