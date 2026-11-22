# Operation Opto

Real-time 3D explainer graphics, built on **Kimi K3.1 (Cerebras) running through the OpenClaw
harness**. Ask about a physical thing and Kimi writes a **Blender** script that builds a 3D cutaway
model. The model streams into a web viewer where you can rotate it, slice it, explode it, and click
a part to ask Kimi about it. The same scene compiles to a **3Blue1Brown-style Manim video**.

## Pipeline

```
question ─► OpenClaw gateway (/v1/chat/completions, agent "openclaw/default",
            x-openclaw-model: cerebras/moonshotai-kimi-k3.1-pro-trial)
        ─► Kimi K3.1 writes a bpy script (helpers: meta / mat / part / arrow / beat)
        ─► headless Blender 5.3 (pip `bpy`), sandboxed with bubblewrap + warm worker pool
              └─ on error: traceback goes back to Kimi for repair (up to 2 rounds)
        ─► out/forge/<id>/model.glb + scene.json + mesh.npz
        ─► web viewer (three.js): clipping-plane cross-section, explode, sticky labels, part Q&A
        ─► Kimi-driven Manim Forge (opto/manim_forge.py + opto/manim_bridge.py):
              Kimi K3.1 writes custom 3Blue1Brown Manim Python scripts (video_scene.py)
              ├─ traceback repair loop (up to 2 rounds)
              └─ autonomous multimodal rewatch loop (opto/visual_qa.py): Kimi inspects its own
                 rendered contact sheet and iteratively fixes visual/overlap defects
```

`showcase/` holds final eval summaries, 26-model render sheets, and Kimi's custom 3Blue1Brown Manim
scripts + sheets.

There is also an older "primitives" mode, where Kimi streams a fixed list of shapes as NDJSON. It's
faster but much less expressive. It stays available in the app's mode picker and in `opto/schema.py`.

## Mac app (menu bar + floating 3D HUD)

```bash
mac/install.sh          # uv sync, login item, right-click Quick Actions
mac/install.sh --remove # uninstall
```

- A cube in the macOS menu bar opens a slim prompt bar (Ask Opto…, Ask About Screen…, with an elapsed timer).
- On ask, one Kimi K3.1 call (through OpenClaw) streams the 3D scene and then a 3B1B storyboard; the HUD
  expands into a transparent window: the model floats over the desktop, next to a panel with Kimi stats and a
  collapsible live log. The Manim video renders from that storyboard with no second model call.
- Named real-world things get a web reference first (Wikipedia summary + up to 3 Wikimedia Commons photos,
  `opto/research.py`) that Kimi sees as image input, so they look like the real object.
- Right-click selected text or an image file → Services → Ask Opto. From a shell: `mac/ask-opto.sh`.
- Kimi K3.1 only (`OPTO_BACKEND=openclaw`, `OPTO_MODE=kimi`); the OpenClaw gateway must be running.

## Run it

```bash
cd ~/operation-opto
uv run python -m opto.server                 # http://127.0.0.1:8765   (?q=how+does+a+jet+engine+work)
uv run python -m opto.forge "how does a V8 engine work?"       # one scene from the CLI
uv run python -m opto.video out/forge/v8_engine out/videos/v8.mp4 -q m   # Manim video
```

The OpenClaw gateway must be running (`openclaw gateway status`) with
`gateway.http.endpoints.chatCompletions.enabled = true`. Set `OPTO_BACKEND=direct` to call Cerebras
directly instead; that mode also reports Cerebras queue and completion timings.

## Evals

```bash
uv run python evals/forge_run.py --split core     # 16 tuning queries
uv run python evals/forge_run.py --split hard     # 10 held-out queries: F-22, Apache, Falcon 9, Saturn V, ...
uv run python evals/render.py --forge --split hard     # screenshots → out/qa/
```

The hard tier is held out. Its required-part lists were written before seeing any output, and no
prompt change mentions a specific eval object. The mechanical checks cover: the script runs,
required parts are present, internals exist, label/arrow counts, story structure, connectivity,
and triangle budget. Passing them is necessary but not sufficient, so the screenshots get reviewed
by eye as well.

Results are written to `out/evals/*/summary.md`.
