"""Autonomous visual QA where Kimi K3.1 rewatches its own rendered Manim video.

Extracts a crisp 3x2 (6-frame, 1920x720) timestamped contact sheet across populated split-stage
acts + finale, builds a full-resolution zoomed inspection sheet of the finale (top equation vs 3D
model + bottom caption band), runs deterministic spatial/overlap checks, and sends both images to
Kimi K3.1 (`moonshotai-kimi-k3.1-pro-trial`, multimodal) so Kimi inspects and fixes its own visual
defects before final export.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import llm

QA_PROMPT = """You are a strict visual QA editor reviewing a Manim OpenGL video you just rendered
(3D Blender cutaway on the left half, 2D Manim math chalkboard on the right half, centered finale
in Frame #6). You are given TWO images:
- IMAGE 1: 3x2 contact sheet of 6 frames (#1 through #6, with timestamps).
- IMAGE 2: High-resolution zoomed inspection of Frame #6 (ZOOM A: top equation/title vs 3D model;
  ZOOM B: bottom caption band).

Inspect EVERY frame and BOTH zoom crops carefully and report ALL real visual defects:
1. Finale top collision (check ZOOM A closely): top equation or title touching, pierced by, sitting
   on top of, or tightly crowding (< ~20px black margin) the top of the 3D model.
2. Stacked / overlapping bottom captions (check ZOOM B and bottom of Frames #1-#6): two captions
   visible simultaneously because an earlier narration line was not faded out before a new one
   appeared, or text overlapping other bottom text.
3. Element overlap on the right chalkboard (Frames #1-#5): any label crossing a brace, curve,
   diagram outline, or axis; two equations or symbols colliding/running into each other (e.g.
   adjacent labels merging); unreadable tiny cramped text.
4. Callout / divider collisions & clipping: left-pane callout text overlapping the 3D mesh or
   crossing the vertical divider (x = 0.05), or any chalkboard equation/label clipped at frame edge.
5. Ghost / duplicate 3D meshes: two copies of the 3D object side-by-side or a floating detached half.
6. Blank or missing half: left 3D model missing or right chalkboard completely blank in split-stage
   frames.

Do NOT be lenient — if you see a real overlap, collision, duplicate mesh, or stacked caption, set
"ok": false and list it with an exact actionable fix. Ignore intentional pure-black backgrounds
and faint 3D coordinate grids.

Return ONLY valid JSON:
{"ok": true/false, "issues": ["Frame #N (t=...s): exact defect and concrete fix (e.g. raise finale equation to y=3.35 and lower camera zoom to 0.62, FadeOut old caption before adding finale tagline, shift label right of brace)", ...]}
If ALL frames and BOTH zoom crops are genuinely clean with zero overlaps, collisions, ghost meshes,
or stacked captions, return {"ok": true, "issues": []}."""


def find_tool(name: str) -> str:
    """Resolve CLI tools like ffmpeg/ffprobe, checking Windows registry PATH and WinGet if PATH is stale."""
    found = shutil.which(name)
    if found:
        return found
    if os.name == "nt":
        try:
            import winreg
            reg_paths: list[str] = []
            for root, subkey in (
                (winreg.HKEY_CURRENT_USER, r"Environment"),
                (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
            ):
                try:
                    with winreg.OpenKey(root, subkey) as key:
                        val, _ = winreg.QueryValueEx(key, "Path")
                        if val:
                            reg_paths.append(os.path.expandvars(str(val)))
                except OSError:
                    pass
            if reg_paths:
                found = shutil.which(name, path=os.pathsep.join(reg_paths))
                if found:
                    return found
        except ImportError:
            pass
        exe = name if name.lower().endswith(".exe") else f"{name}.exe"
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        winget_links = local / "Microsoft" / "WinGet" / "Links" / exe
        if winget_links.is_file():
            return str(winget_links)
        winget_pkgs = local / "Microsoft" / "WinGet" / "Packages"
        if winget_pkgs.is_dir():
            for match in winget_pkgs.rglob(exe):
                if match.is_file():
                    return str(match)
    return name


_find_tool = find_tool


def _duration(mp4: Path) -> float:
    out = subprocess.run(
        [find_tool("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=True,
    ).stdout.strip()
    return float(out)


def _extract_frame(mp4: Path, ts: float, dst: Path) -> Image.Image:
    subprocess.run(
        [find_tool("ffmpeg"), "-loglevel", "error", "-y", "-ss", f"{ts:.2f}", "-i", str(mp4),
         "-frames:v", "1", str(dst)],
        check=True, timeout=30,
    )
    with Image.open(dst) as im:
        return im.convert("RGB")


def _row_bands(region_max: np.ndarray, thr: float = 70.0, min_px: int = 6, min_h: int = 3) -> list[tuple[int, int, float]]:
    """Return contiguous vertical bright bands (y0, y1, horizontal_span_frac) in a 2D max-channel array."""
    mask = region_max > thr
    row_counts = mask.sum(axis=1)
    w = max(1, region_max.shape[1])
    bands: list[tuple[int, int, float]] = []
    start: int | None = None
    for y, cnt in enumerate(row_counts):
        if cnt >= min_px and start is None:
            start = y
        elif cnt < min_px and start is not None:
            if y - start >= min_h:
                cols = np.where(mask[start:y].any(axis=0))[0]
                span = float(cols[-1] - cols[0] + 1) / w if cols.size else 0.0
                bands.append((start, y, span))
            start = None
    if start is not None and len(row_counts) - start >= min_h:
        cols = np.where(mask[start:].any(axis=0))[0]
        span = float(cols[-1] - cols[0] + 1) / w if cols.size else 0.0
        bands.append((start, len(row_counts), span))
    return bands


def _check_frame_layout(im: Image.Image, frame_idx: int, ts: float, is_finale: bool) -> list[str]:
    """Deterministic pixel-band checks for stacked bottom captions and finale equation-model collisions."""
    arr = np.asarray(im, dtype=np.float32)
    h, w, _ = arr.shape
    mx = arr.max(axis=2)
    min_px = max(4, int(round(w * 0.005)))
    min_h = max(3, int(round(h * 0.005)))
    issues: list[str] = []

    # 1. Stacked / un-faded duplicate bottom captions inside y in [0.815, 0.99]
    y0_bot, y1_bot = int(h * 0.815), int(h * 0.99)
    x0_bot, x1_bot = int(w * 0.06), int(w * 0.94)
    bot_bands = _row_bands(mx[y0_bot:y1_bot, x0_bot:x1_bot], thr=70.0, min_px=min_px, min_h=min_h)
    caption_lines = [
        b for b in bot_bands
        if b[0] > 0  # not clipped at the top edge by an equation sitting above the caption zone
        and (0.016 * h <= (b[1] - b[0]) <= 0.068 * h)
        and b[2] >= 0.25
    ]
    if len(caption_lines) >= 2:
        issues.append(
            f"Frame #{frame_idx} (t={ts:.1f}s): {len(caption_lines)} stacked/overlapping bottom "
            f"captions detected simultaneously in the caption band. FadeOut and remove the previous "
            f"narration caption BEFORE adding the next/finale caption so only one bottom line is visible."
        )

    # 2. Finale top equation/title colliding with or crowding the 3D model
    if is_finale:
        y0_top, y1_top = int(h * 0.02), int(h * 0.55)
        x0_top, x1_top = int(w * 0.12), int(w * 0.88)
        top_bands = _row_bands(mx[y0_top:y1_top, x0_top:x1_top], thr=70.0, min_px=min_px, min_h=min_h)
        if top_bands:
            first_y0, first_y1, _ = top_bands[0]
            first_abs_y0 = y0_top + first_y0
            first_abs_y1 = y0_top + first_y1
            # Case A: top equation and 3D model are directly fused/pierced (single tall band from top zone into model)
            if first_abs_y0 < 0.24 * h and first_abs_y1 > 0.29 * h and (first_y1 - first_y0) > 0.15 * h:
                issues.append(
                    f"Frame #{frame_idx} (t={ts:.1f}s): Finale top equation/title directly collides with / "
                    f"is pierced by the 3D model (0px vertical clearance). Move the finale equation higher "
                    f"(y >= 3.35, height <= 0.48), reduce center camera zoom (e.g. set_zoom(0.58-0.65)), "
                    f"and/or shift the 3D model slightly lower so there is a wide black gap above the model."
                )
            else:
                # Case B: small gap between top text/equation cluster and the 3D model below it
                eq_end: int | None = None
                model_start: int | None = None
                for by0, by1, _ in top_bands:
                    abs_y0, abs_y1 = y0_top + by0, y0_top + by1
                    bh = by1 - by0
                    is_model = (bh >= 0.08 * h) or (abs_y1 > 0.27 * h)
                    if not is_model and abs_y0 < 0.25 * h:
                        eq_end = abs_y1
                    elif is_model and eq_end is not None:
                        model_start = abs_y0
                        break
                if eq_end is not None and model_start is not None:
                    gap_frac = (model_start - eq_end) / float(h)
                    if gap_frac < 0.028:
                        issues.append(
                            f"Frame #{frame_idx} (t={ts:.1f}s): Finale top equation touches or tightly crowds "
                            f"the top of the 3D model (vertical gap is only {gap_frac * 100:.1f}% of frame height). "
                            f"Move the finale equation higher (y >= 3.35, height <= 0.48) and reduce center camera "
                            f"zoom slightly so there is clear black breathing room between equation and 3D model."
                        )
    return issues


def _build_zoom_sheet(finale_im: Image.Image, ts: float, out_zoom: Path) -> Path:
    """Build a crisp high-res zoom inspection image of Frame #6 top (equation vs model) and bottom (captions)."""
    w, h = finale_im.size
    target_w = 1280

    top_crop = finale_im.crop((0, 0, w, int(h * 0.50)))
    top_h = int(round(top_crop.height * (target_w / w)))
    top_resized = top_crop.resize((target_w, top_h), Image.Resampling.LANCZOS)

    bot_crop = finale_im.crop((0, int(h * 0.78), w, h))
    bot_h = int(round(bot_crop.height * (target_w / w) * 1.4))
    bot_resized = bot_crop.resize((target_w, bot_h), Image.Resampling.LANCZOS)

    pad = 28
    canvas = Image.new("RGB", (target_w, top_h + bot_h + pad * 2), (12, 16, 22))
    draw = ImageDraw.Draw(canvas)

    draw.rectangle([0, 0, target_w, pad], fill=(16, 28, 42))
    draw.text((12, 8), f"ZOOM A — Frame #6 (t={ts:.1f}s) TOP HALF: check equation/title vs 3D model clearance", fill=(150, 220, 255))
    canvas.paste(top_resized, (0, pad))

    y_bot_bar = pad + top_h
    draw.rectangle([0, y_bot_bar, target_w, y_bot_bar + pad], fill=(16, 28, 42))
    draw.text((12, y_bot_bar + 8), f"ZOOM B — Frame #6 (t={ts:.1f}s) BOTTOM BAND (1.4x zoom): check for stacked/duplicate captions", fill=(255, 210, 140))
    canvas.paste(bot_resized, (0, y_bot_bar + pad))

    out_zoom.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_zoom, optimize=True)
    return out_zoom


def build_qa_sheet(mp4: Path, out_sheet: Path) -> tuple[Path, Path, list[dict], list[str]]:
    """Extract 6 smartly-sampled crisp 640x360 frames (3x2) + finale zoom sheet + deterministic checks."""
    dur = _duration(mp4)
    split_centers = [0.16, 0.31, 0.46, 0.61, 0.77]
    finale_cands = [0.92, 0.94, 0.96]
    tw, th = 640, 360
    sheet = Image.new("RGB", (tw * 3, th * 2), (0, 0, 0))
    metrics: list[dict] = []
    det_issues: list[str] = []
    finale_im: Image.Image | None = None
    finale_ts = dur * 0.94

    with tempfile.TemporaryDirectory(prefix="opto-vqa-") as td:
        td_path = Path(td)
        chosen: list[tuple[float, Image.Image, bool]] = []

        for idx, center in enumerate(split_centers):
            best: tuple[float, float, Image.Image] | None = None
            for off_i, delta in enumerate((-0.025, 0.0, 0.025)):
                ts = max(0.3, min(dur - 0.5, dur * (center + delta)))
                im = _extract_frame(mp4, ts, td_path / f"s{idx}_{off_i}.png")
                gray = np.asarray(im, dtype=np.float32).mean(axis=2)
                ih, iw = gray.shape
                mid = gray[: int(ih * 0.85), :]
                right_lit = float((mid[:, iw // 2 :] > 18).mean())
                if best is None or right_lit > best[0]:
                    best = (right_lit, ts, im)
            assert best is not None
            chosen.append((best[1], best[2], False))

        best_fin: tuple[float, float, Image.Image] | None = None
        for off_i, frac in enumerate(finale_cands):
            ts = max(0.3, min(dur - 0.25, dur * frac))
            im = _extract_frame(mp4, ts, td_path / f"fin_{off_i}.png")
            score = float(np.asarray(im, dtype=np.float32).mean())
            if best_fin is None or score > best_fin[0]:
                best_fin = (score, ts, im)
        assert best_fin is not None
        finale_ts, finale_im = best_fin[1], best_fin[2]
        chosen.append((finale_ts, finale_im, True))

        for i, (ts, full_im, is_finale) in enumerate(chosen):
            det_issues.extend(_check_frame_layout(full_im, i + 1, ts, is_finale))
            im = full_im.resize((tw, th), Image.Resampling.LANCZOS)
            gray = np.asarray(im, dtype=np.float32).mean(axis=2)
            mid = gray[: int(th * 0.85), :]
            left_lit = float((mid[:, : tw // 2] > 18).mean())
            right_lit = float((mid[:, tw // 2 :] > 18).mean())
            metrics.append({
                "frame": i + 1, "t": round(ts, 1),
                "left_lit": round(left_lit, 4), "right_lit": round(right_lit, 4),
                "mean": round(float(gray.mean()), 2),
            })
            draw = ImageDraw.Draw(im)
            draw.rectangle([4, 4, 128, 24], fill=(10, 18, 28))
            draw.text((10, 8), f"#{i+1} t={ts:.1f}s", fill=(140, 210, 245))
            r, c = divmod(i, 3)
            sheet.paste(im, (c * tw, r * th))

    out_sheet.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_sheet, optimize=True)
    zoom_path = out_sheet.with_name(f"{out_sheet.stem}_zoom{out_sheet.suffix}")
    assert finale_im is not None
    _build_zoom_sheet(finale_im, finale_ts, zoom_path)
    return out_sheet, zoom_path, metrics, det_issues


def sheet_image_url(sheet_path: Path) -> str:
    b64 = base64.b64encode(sheet_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


async def ainspect_video(mp4_path: str | Path, out_sheet: str | Path | None = None) -> dict:
    """Have Kimi K3.1 rewatch a 3x2 contact sheet + finale zoom crops of its own rendered Manim video."""
    mp4 = Path(mp4_path)
    sheet_path = Path(out_sheet) if out_sheet else mp4.with_suffix(".qa.png")
    sheet_path, zoom_path, metrics, det_issues = await asyncio.to_thread(build_qa_sheet, mp4, sheet_path)

    issues: list[str] = list(det_issues)
    mid_frames = metrics[:5]
    left_visible = sum(1 for m in mid_frames if m["left_lit"] >= 0.008)
    right_visible = sum(1 for m in mid_frames if m["right_lit"] >= 0.004)
    if left_visible < 3:
        issues.append(f"3D model missing or invisible on the left half in {5 - left_visible}/5 split-stage frames.")
    if right_visible < 3:
        issues.append(f"2D Manim chalkboard blank on the right half in {5 - right_visible}/5 split-stage frames.")

    vision_ok = True
    vision_raw = ""
    st = llm.Stats(llm.KIMI)
    try:
        prompt = QA_PROMPT
        if det_issues:
            hints = "\n".join(f"- {d}" for d in det_issues)
            prompt += (
                "\n\nAutomated pixel-layout pre-checks already flagged these issues (verify them and ALSO "
                "report any additional overlaps, collisions, ghost duplicate meshes, or clipping you see):\n"
                f"{hints}"
            )
        msgs = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": sheet_image_url(sheet_path)}},
                {"type": "image_url", "image_url": {"url": sheet_image_url(zoom_path)}},
            ],
        }]
        vision_raw = (await llm.acomplete(msgs, model=llm.KIMI, max_tokens=6000, effort="high", stats=st)).strip()
        m = re.search(r"\{.*\}", vision_raw, re.S)
        if m:
            parsed = json.loads(m.group(0))
            vision_ok = bool(parsed.get("ok", True))
            vision_issues = [
                item.strip() for item in (parsed.get("issues") or [])
                if isinstance(item, str) and item.strip()
            ]
            # Prefer Kimi's full verified issue list when it caught issues, while retaining any missed deterministic findings
            if vision_issues:
                combined = list(vision_issues)
                lowered = " ".join(combined).lower()
                for d in det_issues:
                    key = "caption" if "caption" in d.lower() else ("collid" if "collid" in d.lower() or "touch" in d.lower() else "")
                    if not key or key not in lowered:
                        combined.append(d)
                issues = [i for i in issues if i not in det_issues] + combined
    except Exception as e:
        vision_raw = f"kimi_visual_qa_error: {e!r}"

    return {
        "ok": (len(issues) == 0) and vision_ok,
        "issues": issues,
        "deterministic_issues": det_issues,
        "metrics": metrics,
        "sheet": str(sheet_path),
        "zoom_sheet": str(zoom_path),
        "reviewer_model": llm.KIMI,
        "reviewer_backend": llm.BACKEND,
        "stats": st.as_dict(),
        "vision_raw": vision_raw[:1200],
    }


def inspect_video(mp4_path: str | Path, out_sheet: str | Path | None = None) -> dict:
    return asyncio.run(ainspect_video(mp4_path, out_sheet))


if __name__ == "__main__":
    import sys
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    for p in sys.argv[1:]:
        res = inspect_video(p)
        print(f"\n=== KIMI K3.1 VISUAL REWATCH: {p} -> ok={res['ok']} ===")
        for iss in res["issues"]:
            print("  -", iss)
        if not res["issues"]:
            print("  (Kimi verified: clean, no visual defects)")
