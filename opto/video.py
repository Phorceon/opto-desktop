"""Compile a Forge (Blender) or OptoScene into an authentic 3Blue1Brown-style Manim video.

    python -m opto.video out/forge/v8_engine out/videos/v8_engine.mp4 -q m

Visual style (3Blue1Brown + 3D Blender Cutaway):
  - Pure #000000 canvas + 3D NumberPlane coordinate grid under the model
  - Glowing cyan feature-edge blueprint wireframe reveal (Create) -> shaded 3D cutaway
  - Split-stage choreography: 3D cutaway pinned on the left half while the right half acts
    as a live 3Blue1Brown chalkboard: Computer Modern LaTeX equations (Write), glowing
    SurroundingRectangles, color-coded symbol legends, and animated 2D Axes plots /
    thermodynamic cycle loops / vector diagrams / flow chains (Create + moving tracer Dot)
  - Borderless colored serif callouts + thin leader lines matched to highlighted 3D parts
  - Driven by Kimi K3.1 (via OpenClaw) storyboards in out/forge/<id>/story_3b1b.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np

from . import geometry, manim_bridge, schema, story3b1b, visual_qa

# three.js/glTF y-up  ->  manim z-up  (det = +1, a proper rotation)
P = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=float)

BG = "#000000"
C_BLUE = "#58C4DD"
C_BLUE_DIM = "#25577A"
C_TEAL = "#5CD0B3"
C_YELLOW = "#F9E154"
C_GOLD = "#F0AC5F"
C_MAROON = "#EC92AB"
C_GREEN = "#83C167"
C_RED = "#FF7A70"
C_WHITE = "#ECECEC"
C_MUTED = "#9DB4C8"
C_DIM_MESH = "#2D4963"

PX_PER_UNIT = 165
DECIMATE_ABOVE = 20_000
DECIMATE_TO = 12_000
TOTAL_TRI_BUDGET = 42_000
FIT_HALF_EXTENT = 3.8

_FONT_FILES: dict[tuple[bool, bool], str | None] = {}
_SERIF_FAMILY: str | None = None


def _serif_family() -> str:
    global _SERIF_FAMILY
    if _SERIF_FAMILY:
        return _SERIF_FAMILY
    for name in ("CMU Serif", "Latin Modern Roman", "Liberation Serif", "Noto Serif", "DejaVu Serif"):
        try:
            out = subprocess.run(["fc-list", f":family={name}"], capture_output=True, text=True, timeout=5).stdout
            if out.strip():
                _SERIF_FAMILY = name
                return name
        except Exception:
            pass
    _SERIF_FAMILY = "Serif"
    return _SERIF_FAMILY


def _font_file(bold: bool = False, italic: bool = False) -> str | None:
    key = (bold, italic)
    if key not in _FONT_FILES:
        _FONT_FILES[key] = manim_bridge._font_path(bold, italic)
    return _FONT_FILES[key]


def _hex_rgba(h: str, a: float = 1.0) -> tuple[int, int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(round(255 * a)))


def raster_text(lines: list[str], *, line_h: float, color: str = C_WHITE, bold: bool = False,
                italic: bool = False, bg: str | None = None, bg_alpha: float = 0.0,
                pad: tuple[float, float] = (0.04, 0.02), radius: float = 0.0,
                border: str | None = None, border_w: float = 0.0, align: str = "center",
                line_gap: float = 0.24) -> np.ndarray:
    """Rasterise crisp anti-aliased serif text to RGBA array (1 Manim unit = PX_PER_UNIT px)."""
    from PIL import Image, ImageDraw, ImageFont

    k = PX_PER_UNIT
    size = max(10, int(round(line_h * k)))
    path = _font_file(bold=bold, italic=italic)
    try:
        fnt = ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
    except Exception:
        fnt = ImageFont.load_default()
    asc, desc = fnt.getmetrics()
    lh = asc + desc
    widths = [max(1, int(math.ceil(fnt.getlength(l)))) for l in lines] or [1]
    tw = max(widths)
    th = lh * len(lines) + int(lh * line_gap) * max(0, len(lines) - 1)
    px, py = max(2, int(pad[0] * k)), max(2, int(pad[1] * k))
    W, H = max(4, tw + 2 * px), max(4, th + 2 * py)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if bg and bg_alpha > 0:
        bw = max(1, int(round(border_w * k))) if border else 0
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=int(radius * k),
                            fill=_hex_rgba(bg, bg_alpha),
                            outline=_hex_rgba(border) if border else None, width=bw)
    elif border:
        bw = max(1, int(round(border_w * k)))
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=int(radius * k),
                            outline=_hex_rgba(border), width=bw)
    y = py
    for l, w in zip(lines, widths):
        x = px + (tw - w) // 2 if align == "center" else (px + (tw - w) if align == "right" else px)
        d.text((x, y), l, font=fnt, fill=_hex_rgba(color))
        y += lh + int(lh * line_gap)
    return np.asarray(img)


def raster_mathtext_png(tex: str, color: str = C_WHITE, fontsize: int = 26) -> np.ndarray | None:
    """Render a short Computer Modern math symbol/expression to crisp transparent RGBA via matplotlib."""
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image

    tex = tex.strip().strip("$")
    if not tex:
        return None
    try:
        plt.rcParams["mathtext.fontset"] = "cm"
        fig = plt.figure(figsize=(4.0, 0.9), dpi=180)
        fig.patch.set_visible(False)
        fig.text(0.5, 0.5, f"${tex}$", color=color, fontsize=fontsize, ha="center", va="center")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", transparent=True, bbox_inches="tight", pad_inches=0.03)
        plt.close(fig)
        buf.seek(0)
        return np.asarray(Image.open(buf).convert("RGBA"))
    except Exception:
        return None


def render_mathtext_svg(tex: str, out_dir: Path, color: str = C_WHITE) -> Path | None:
    """Compile a LaTeX math expression to pure Computer Modern vector SVG paths for Manim Write()."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    tex = tex.strip().strip("$")
    if not tex:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{tex}|{color}".encode()).hexdigest()[:18]
    svg_path = out_dir / f"eq_{key}.svg"
    if svg_path.exists():
        return svg_path
    try:
        plt.rcParams["mathtext.fontset"] = "cm"
        plt.rcParams["svg.fonttype"] = "path"
        fig = plt.figure(figsize=(6.5, 1.5), dpi=150)
        fig.patch.set_visible(False)
        fig.text(0.5, 0.5, f"${tex}$", color=color, fontsize=34, ha="center", va="center")
        fig.savefig(svg_path, format="svg", transparent=True, bbox_inches="tight", pad_inches=0.04)
        plt.close(fig)
        s = svg_path.read_text()
        s = re.sub(r'<g id="patch_1">.*?</g>', "", s, flags=re.S)
        svg_path.write_text(s)
        return svg_path
    except Exception:
        return None


def words_time(say: str) -> float:
    return max(3.6, min(6.2, len((say or "").split()) / 2.8 + 1.6))


def triangulate(faces: list) -> np.ndarray:
    tris = []
    for f in faces:
        for k in range(1, len(f) - 1):
            tris.append((f[0], f[k], f[k + 1]))
    return np.asarray(tris, dtype=float).reshape(-1, 3, 3)


def smooth_normals(tris: np.ndarray, crease_deg: float = 42.0) -> np.ndarray:
    fn = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    ln = np.linalg.norm(fn, axis=1, keepdims=True)
    fn = np.where(ln > 1e-12, fn / np.maximum(ln, 1e-12), np.array([0, 0, 1.0]))
    corners = tris.reshape(-1, 3)
    keys = np.round(corners, 5)
    _, inv = np.unique(keys, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    face_of = np.repeat(np.arange(len(tris)), 3)
    acc = np.zeros((inv.max() + 1, 3))
    np.add.at(acc, inv, fn[face_of] * ln[face_of].clip(1e-9))
    nrm = acc[inv]
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    own = fn[face_of]
    cos = np.abs(np.sum(nrm * own, axis=1))
    sharp = cos < math.cos(math.radians(crease_deg))
    nrm[sharp] = own[sharp]
    return nrm


def decimate(tris: np.ndarray, nrm: np.ndarray, target: int) -> tuple[np.ndarray, np.ndarray]:
    pts = tris.reshape(-1, 3)
    n0 = nrm.reshape(-1, 3)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    ext = np.maximum(hi - lo, 1e-9)
    nb = np.clip(np.round(n0 * 1.5).astype(np.int64) + 2, 0, 4)
    nkey = nb[:, 0] * 25 + nb[:, 1] * 5 + nb[:, 2]

    def cluster(cell):
        g = np.floor((pts - lo) / cell).astype(np.int64)
        dims = g.max(axis=0) + 1
        key = (g[:, 0] * dims[1] + g[:, 1]) * dims[2] + g[:, 2]
        _, cid = np.unique(key, return_inverse=True)
        cid = cid.reshape(-1)
        tri_c = cid.reshape(-1, 3)
        ok = (tri_c[:, 0] != tri_c[:, 1]) & (tri_c[:, 1] != tri_c[:, 2]) & (tri_c[:, 0] != tri_c[:, 2])
        idx = np.flatnonzero(ok)
        _, first = np.unique(np.sort(tri_c[idx], axis=1), axis=0, return_index=True)
        return cid, idx[np.sort(first)]

    cell = float(ext.max()) / 300.0
    best = None
    for _ in range(8):
        cid, idx = cluster(cell)
        n = len(idx)
        if n <= target * 1.15 and (best is None or n > len(best[1])):
            best = (cid, idx)
        if target * 0.7 <= n <= target * 1.15:
            break
        cell *= float(np.clip(math.sqrt(max(n, 1) / target), 0.5, 3.0))
    if best is None:
        best = (cid, idx)
    cid, idx = best
    if len(idx) == 0:
        return tris, nrm
    cnt = np.bincount(cid).astype(float)[:, None]
    cpos = np.stack([np.bincount(cid, weights=pts[:, k]) for k in range(3)], axis=1) / cnt
    _, gid = np.unique(cid * 125 + nkey, return_inverse=True)
    gid = gid.reshape(-1)
    gn = np.stack([np.bincount(gid, weights=n0[:, k]) for k in range(3)], axis=1)
    gn /= np.maximum(np.linalg.norm(gn, axis=1, keepdims=True), 1e-12)
    corner = (idx[:, None] * 3 + np.arange(3)[None, :]).reshape(-1)
    new_t = cpos[cid[corner]].reshape(-1, 3, 3)
    new_n = gn[gid[corner]]
    bad = np.linalg.norm(new_n, axis=1) < 0.5
    if bad.any():
        new_n[bad] = n0[corner][bad]
    return new_t, new_n


def dedupe(tris: np.ndarray, nrm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if not len(tris):
        return tris, nrm
    span = float(np.ptp(tris.reshape(-1, 3), axis=0).max()) or 1.0
    q = np.round(tris / (span * 1e-6)).astype(np.int64)
    keyc = q[:, :, 0] * 73856093 ^ q[:, :, 1] * 19349663 ^ q[:, :, 2] * 83492791
    srt = np.sort(keyc, axis=1)
    degenerate = (srt[:, 0] == srt[:, 1]) | (srt[:, 1] == srt[:, 2])
    _, first = np.unique(srt, axis=0, return_index=True)
    keep = np.zeros(len(tris), bool)
    keep[first] = True
    keep &= ~degenerate
    if keep.all():
        return tris, nrm
    return tris[keep], nrm.reshape(-1, 3, 3)[keep].reshape(-1, 3)


def extract_feature_edges(tris: np.ndarray, crease_deg: float = 36.0, max_edges: int = 1200) -> np.ndarray:
    """Extract sharp dihedral crease & boundary edges from a triangle soup as (M, 2, 3) segments."""
    if not len(tris):
        return np.zeros((0, 2, 3), dtype=float)
    fn = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    ln = np.linalg.norm(fn, axis=1, keepdims=True)
    ok = ln[:, 0] > 1e-10
    tris = tris[ok]
    fn = fn[ok] / ln[ok]
    if not len(tris):
        return np.zeros((0, 2, 3), dtype=float)

    pts = tris.reshape(-1, 3)
    q = np.round(pts * 1000.0).astype(np.int64)
    _, vid = np.unique(q, axis=0, return_inverse=True)
    vid = vid.reshape(-1, 3)

    # 3 undirected edges per triangle
    e_a = np.concatenate([vid[:, 0], vid[:, 1], vid[:, 2]])
    e_b = np.concatenate([vid[:, 1], vid[:, 2], vid[:, 0]])
    p_a = np.concatenate([tris[:, 0], tris[:, 1], tris[:, 2]], axis=0)
    p_b = np.concatenate([tris[:, 1], tris[:, 2], tris[:, 0]], axis=0)
    f_idx = np.tile(np.arange(len(tris)), 3)

    lo = np.minimum(e_a, e_b)
    hi = np.maximum(e_a, e_b)
    ekey = lo * (int(vid.max()) + 2) + hi
    order = np.argsort(ekey)
    ek_s = ekey[order]
    f_s = f_idx[order]

    # Find unique edges and compare adjacent face normals where count == 2
    cos_thresh = math.cos(math.radians(crease_deg))
    n_e = len(ek_s)
    keep_ord = []
    i = 0
    while i < n_e:
        j = i + 1
        while j < n_e and ek_s[j] == ek_s[i]:
            j += 1
        cnt = j - i
        if cnt == 1:
            keep_ord.append(order[i])
        elif cnt == 2:
            if abs(float(np.dot(fn[f_s[i]], fn[f_s[i + 1]]))) < cos_thresh:
                keep_ord.append(order[i])
        else:
            keep_ord.append(order[i])
        i = j

    if not keep_ord:
        return np.zeros((0, 2, 3), dtype=float)
    idx = np.asarray(keep_ord, dtype=np.int64)
    segs = np.stack([p_a[idx], p_b[idx]], axis=1)
    lens = np.linalg.norm(segs[:, 1] - segs[:, 0], axis=1)
    segs = segs[lens > 1e-3]
    lens = lens[lens > 1e-3]
    if len(segs) > max_edges:
        top = np.argpartition(lens, -max_edges)[-max_edges:]
        segs = segs[top]
    return segs


def _hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(int(round(c * 255.0)) for c in np.clip(rgb, 0.0, 1.0)))


def video_color(rgb) -> str:
    rgb = np.clip(np.asarray(rgb, dtype=float), 0.0, 1.0)
    lum = float(0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2])
    if lum < 0.28:
        t = (0.28 - lum) / max(1e-6, 1.0 - lum)
        rgb = rgb + (1.0 - rgb) * t
    return _hex(rgb)


def color_to_rgb_hex(h: str) -> list[float]:
    h = (h or "#9aa3ad").lstrip("#")
    try:
        return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    except ValueError:
        return [0.6, 0.64, 0.68]


def load_forge(dirpath: str | Path, *, decimate_above: int = DECIMATE_ABOVE,
               decimate_to: int = DECIMATE_TO) -> tuple[schema.Scene, dict]:
    dirpath = Path(dirpath)
    data = json.loads((dirpath / "scene.json").read_text())
    src_parts = [p for p in data.get("parts", []) if isinstance(p, dict) and p.get("id")]
    by_id = {p["id"]: p for p in src_parts}

    raw: dict[str, tuple] = {}
    with np.load(dirpath / "mesh.npz") as archive:
        files = set(archive.files)
        for key in archive.files:
            if not key.endswith("__tris"):
                continue
            pid = key[: -len("__tris")]
            tris = np.asarray(archive[key], dtype=np.float64).reshape(-1, 3, 3)
            nrm = None
            if f"{pid}__nrm" in files:
                nrm = np.asarray(archive[f"{pid}__nrm"], dtype=np.float64).reshape(-1, 3)
                if len(nrm) != len(tris) * 3:
                    nrm = None
            if f"{pid}__color" in files:
                rgba = np.asarray(archive[f"{pid}__color"], dtype=np.float64).reshape(-1)[:4]
                rgba = np.concatenate([rgba, [1.0] * (4 - len(rgba))])
            else:
                sp = by_id.get(pid, {})
                rgba = np.r_[np.asarray(color_to_rgb_hex(sp.get("color", "#9aa3ad"))), float(sp.get("opacity", 1.0))]
            good = np.isfinite(tris).all(axis=(1, 2))
            if nrm is not None:
                good &= np.isfinite(nrm).reshape(-1, 3, 3).all(axis=(1, 2))
            tris = tris[good]
            if nrm is not None:
                nrm = nrm.reshape(-1, 3, 3)[good].reshape(-1, 3)
            if not len(tris):
                continue
            raw[pid] = (tris, nrm, rgba)

    if not raw:
        raise ValueError(f"{dirpath}/mesh.npz has no triangles")

    allp = np.concatenate([t.reshape(-1, 3) for t, _, _ in raw.values()])
    lo, hi = allp.min(axis=0), allp.max(axis=0)
    centre = (lo + hi) / 2.0
    half = float(np.max(hi - lo)) / 2.0
    scale = FIT_HALF_EXTENT / half if half > 1e-9 else 1.0

    def xf(v):
        return (np.asarray(v, dtype=np.float64) - centre) * scale

    meshes = {}
    for pid, (tris, nrm, rgba) in raw.items():
        tris = xf(tris)
        if nrm is None:
            nrm = smooth_normals(tris)
        else:
            ln = np.linalg.norm(nrm, axis=1, keepdims=True)
            nrm = np.where(ln > 1e-9, nrm / np.maximum(ln, 1e-12), 0.0)
            bad = ln[:, 0] <= 1e-9
            if bad.any():
                nrm[bad] = smooth_normals(tris).reshape(-1, 3)[bad]
        tris, nrm = dedupe(tris, nrm)
        if not len(tris):
            continue
        if decimate_above and len(tris) > decimate_above:
            tris, nrm = decimate(tris, nrm, decimate_to)
        meshes[pid] = (tris, nrm, rgba)

    total_tris = sum(len(t) for t, _, _ in meshes.values())
    if TOTAL_TRI_BUDGET and total_tris > TOTAL_TRI_BUDGET:
        ratio = TOTAL_TRI_BUDGET / total_tris
        for pid, (tris, nrm, rgba) in list(meshes.items()):
            tgt = max(400, int(len(tris) * ratio))
            if len(tris) > tgt * 1.15:
                tris, nrm = decimate(tris, nrm, tgt)
                meshes[pid] = (tris, nrm, rgba)

    parts = []
    for sp in src_parts:
        pid = sp["id"]
        if pid not in meshes:
            continue
        t = meshes[pid][0].reshape(-1, 3)
        rgba = meshes[pid][2]
        parts.append({
            "id": pid,
            "name": sp.get("name") or pid,
            "shape": "mesh",
            "size": [],
            "pos": ((t.min(axis=0) + t.max(axis=0)) / 2.0).tolist(),
            "rot": [0, 0, 0],
            "color": _hex(rgba[:3]),
            "opacity": float(np.clip(rgba[3], 0.08, 1.0)),
            "internal": bool(sp.get("internal", False)),
            "info": sp.get("info", ""),
        })

    arrows = []
    for a in data.get("arrows", []) or []:
        try:
            arrows.append({**a, "from": xf(a["from"]).tolist(), "to": xf(a["to"]).tolist(),
                           "color": a.get("color") or C_BLUE})
        except Exception:
            pass
    known = {p["id"] for p in parts}
    labels = [l for l in data.get("labels", []) or [] if l.get("part") in known]
    cut = data.get("cut") or {}
    cut = {"axis": cut.get("axis", "z") if cut.get("axis") in ("x", "y", "z") else "z",
           "keep": cut.get("keep", "neg") if cut.get("keep") in ("neg", "pos") else "neg"}
    beats = [b for b in data.get("beats", []) or [] if isinstance(b, dict) and b.get("say")]
    for b in beats:
        b.setdefault("focus", [])
        b.setdefault("do", "highlight")
    scene = schema.Scene(
        title=data.get("title") or "Untitled",
        subtitle=data.get("subtitle", ""),
        cut=cut,
        camera=data.get("camera") or [6.0, 4.0, 7.0],
        parts=parts,
        arrows=arrows,
        labels=labels,
        beats=beats,
    )
    return scene, meshes


def build_scene_class(scene: schema.Scene, meshes: dict | None = None,
                      story: dict | None = None, *, ambient: float = 0.08):
    from manim import (DEGREES, DOWN, LEFT, ORIGIN, RIGHT, UP, config, Animation, Arrow, Axes, Create,
                       DashedLine, Dot, FadeIn, FadeOut, Group, LaggedStart, Line, MoveAlongPath,
                       NumberPlane, Polygon, RoundedRectangle, SVGMobject, Square, SurroundingRectangle,
                       Text, ThreeDScene, VGroup, ValueTracker, VMobject, Write, color_to_rgb, linear,
                       rgb_to_color, smooth)
    from manim.mobject.opengl.opengl_surface import OpenGLSurface, OpenGLTexturedSurface
    from manim.mobject.opengl.opengl_vectorized_mobject import OpenGLVMobject
    from manim.renderer import opengl_renderer as _glr
    import manim.renderer.shader_wrapper as _sw

    # Fix Manim OpenGL 16-texture-unit hardware cap (bind active texture to unit 0 + LINEAR filter)
    if not getattr(_glr.OpenGLRenderer, "_opto_tex_fixed", False):
        import contextlib
        import moderngl
        from PIL import Image as _PILImage

        def _opto_get_texture_id(self, path):
            cache = getattr(self, "_opto_textures", None)
            if cache is None:
                cache = self._opto_textures = {}
            key = f"<image {id(path)}>" if isinstance(path, _PILImage.Image) else str(path)
            tex = cache.get(key)
            if tex is None:
                ctx_img = contextlib.nullcontext(path) if isinstance(path, _PILImage.Image) else _PILImage.open(path)
                with ctx_img as img:
                    img = img.convert("RGBA")
                    tex = self.context.texture(size=img.size, components=4, data=img.tobytes())
                tex.repeat_x = False
                tex.repeat_y = False
                tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
                tex.swizzle = "RGBA"
                cache[key] = tex
            tex.use(location=0)
            return 0

        _glr.OpenGLRenderer.get_texture_id = _opto_get_texture_id
        _glr.OpenGLRenderer._opto_tex_fixed = True

    if not getattr(_sw, "_opto_cached", False):
        _orig_code, _code_cache = _sw.get_shader_code_from_file, {}

        def _cached_code(filename):
            if filename not in _code_cache:
                _code_cache[filename] = _orig_code(filename)
            return _code_cache[filename]

        _sw.get_shader_code_from_file = _cached_code
        _sw._opto_cached = True

    class Tint(Animation):
        def __init__(self, mobject, color, opacity: float, **kw):
            super().__init__(mobject, **kw)
            rgb = color_to_rgb(color)
            self._dst = np.array([rgb[0], rgb[1], rgb[2], float(opacity)], dtype=np.float32)

        def begin(self):
            self._src = np.asarray(self.mobject.rgbas[0], dtype=np.float32).copy()
            super().begin()

        def interpolate_mobject(self, alpha: float):
            self.mobject.rgbas[:] = self._src + (self._dst - self._src) * alpha

    class ShiftFade(Animation):
        def __init__(self, mobject, shift_vec, target_opacity: float | None = None, **kw):
            super().__init__(mobject, **kw)
            self._vec = np.asarray(shift_vec, dtype=float)
            self._dst_op = target_opacity
            self._last = 0.0

        def begin(self):
            self._last = 0.0
            self._src_op = float(self.mobject.rgbas[0, 3])
            super().begin()

        def interpolate_mobject(self, alpha: float):
            da = alpha - self._last
            if da:
                self.mobject.shift(self._vec * da)
                self._last = alpha
            if self._dst_op is not None:
                self.mobject.rgbas[:, 3] = self._src_op + (self._dst_op - self._src_op) * alpha

    class Reveal(Animation):
        def __init__(self, mobject, target_opacity: float | None = None, **kw):
            super().__init__(mobject, introducer=True, **kw)
            self._dst_op = float(mobject.rgbas[0, 3]) if target_opacity is None else float(target_opacity)

        def begin(self):
            self.mobject.rgbas[:, 3] = 0.0
            super().begin()

        def interpolate_mobject(self, alpha: float):
            self.mobject.rgbas[:, 3] = self._dst_op * alpha

    class SlideAlong(Animation):
        def __init__(self, mobject, start, end, phase: float = 0.0, cycles: float = 2.0, **kw):
            super().__init__(mobject, **kw)
            self._s = np.asarray(start, dtype=float)
            self._d = np.asarray(end, dtype=float) - self._s
            self._phase = phase
            self._cycles = cycles
            self._pos = self._s.copy()

        def begin(self):
            p0 = self._s + self._d * (self._phase % 1.0)
            self.mobject.shift(p0 - self._pos)
            self._pos = p0
            super().begin()

        def interpolate_mobject(self, alpha: float):
            u = (alpha * self._cycles + self._phase) % 1.0
            p = self._s + self._d * u
            self.mobject.shift(p - self._pos)
            self._pos = p

    class TriMesh(OpenGLSurface):
        def __init__(self, tris: np.ndarray, normals: np.ndarray, **kw):
            self._tris = tris
            self._normals = normals
            n = len(tris) * 3
            super().__init__(resolution=(0, 0), **kw)
            self.triangle_indices = np.arange(n, dtype=int)

        def init_points(self):
            pts = self._tris.reshape(-1, 3)
            nrm = self._normals
            if len(pts) == 0:
                self.set_points(np.zeros((0, 3)))
                return self
            helper = np.where(np.abs(nrm[:, [0]]) < 0.9, np.array([[1.0, 0, 0]]), np.array([[0, 1.0, 0]]))
            t1 = np.cross(nrm, helper)
            t1 /= np.maximum(np.linalg.norm(t1, axis=1, keepdims=True), 1e-12)
            t2 = np.cross(nrm, t1)
            eps = 1e-3
            self.set_points(np.vstack([pts, pts + eps * t1, pts + eps * t2]))
            return self

        def compute_triangle_indices(self):
            self.triangle_indices = np.arange(len(self.points) // 3, dtype=int)
            return self

    class FlatImage(OpenGLTexturedSurface):
        shader_folder = str(Path(__file__).resolve().parent / "shaders" / "flat_image")

        def __init__(self, arr: np.ndarray, height: float):
            from PIL import Image
            h, w = arr.shape[:2]
            width = height * w / h
            tex_dir = Path(config.media_dir) / "opto_text"
            tex_dir.mkdir(parents=True, exist_ok=True)
            path = tex_dir / (hashlib.sha1(arr.tobytes() + str(arr.shape).encode()).hexdigest()[:20] + ".png")
            if not path.exists():
                Image.fromarray(arr, "RGBA").save(path)
            surf = OpenGLSurface(lambda u, v: np.array([u, v, 0.0]), [-width / 2, width / 2],
                                 [-height / 2, height / 2], resolution=(2, 2), gloss=0, shadow=0,
                                 depth_test=False)
            super().__init__(surf, str(path), resolution=(2, 2), depth_test=False, gloss=0, shadow=0)
            self.texture_paths.pop("DarkTexture", None)

        def init_colors(self):
            self.opacity = np.ones((len(self.im_coords), 1), dtype=np.float32)
            return self

        def get_image_from_file(self, image_file, image_mode):
            return str(image_file)

    def _basis_from_dir(d: np.ndarray):
        u = d / max(float(np.linalg.norm(d)), 1e-9)
        ref = np.array([1.0, 0.0, 0.0]) if abs(u[0]) < 0.85 else np.array([0.0, 1.0, 0.0])
        v = np.cross(u, ref)
        v /= max(float(np.linalg.norm(v)), 1e-9)
        w = np.cross(u, v)
        return u, v, w

    def _make_arrow_mesh(s: np.ndarray, e: np.ndarray, color: str,
                         thickness: float = 0.042, head_len: float = 0.34, head_r: float = 0.13,
                         segs: int = 12) -> TriMesh:
        d = e - s
        L = float(np.linalg.norm(d))
        hl = min(head_len, L * 0.45)
        u, v, w = _basis_from_dir(d)
        neck = e - u * hl
        ang = np.linspace(0, 2 * math.pi, segs, endpoint=False)
        ca, sa = np.cos(ang), np.sin(ang)
        ring = ca[:, None] * v + sa[:, None] * w
        s_ring, n_ring, h_ring = s + ring * thickness, neck + ring * thickness, neck + ring * head_r
        tris = []
        for i in range(segs):
            j = (i + 1) % segs
            tris.append((s_ring[i], s_ring[j], n_ring[j]))
            tris.append((s_ring[i], n_ring[j], n_ring[i]))
            tris.append((h_ring[i], h_ring[j], e))
            tris.append((neck, h_ring[j], h_ring[i]))
        t_arr = np.asarray(tris, dtype=float)
        return TriMesh(t_arr, smooth_normals(t_arr), color=color, opacity=1.0, gloss=0.35, shadow=0.12)

    def _make_sphere_mesh(center: np.ndarray, radius: float, color: str,
                          u_segs: int = 10, v_segs: int = 6) -> TriMesh:
        tris = []
        phis = np.linspace(0, math.pi, v_segs + 1)
        thetas = np.linspace(0, 2 * math.pi, u_segs, endpoint=False)
        pts = np.zeros((v_segs + 1, u_segs, 3))
        for vi, ph in enumerate(phis):
            sp, cp = math.sin(ph), math.cos(ph)
            for ui, th in enumerate(thetas):
                pts[vi, ui] = center + radius * np.array([sp * math.cos(th), sp * math.sin(th), cp])
        for vi in range(v_segs):
            for ui in range(u_segs):
                uj = (ui + 1) % u_segs
                a, b, c, d = pts[vi, ui], pts[vi, uj], pts[vi + 1, uj], pts[vi + 1, ui]
                if vi > 0:
                    tris.append((a, b, c))
                if vi < v_segs - 1:
                    tris.append((a, c, d))
        t_arr = np.asarray(tris, dtype=float)
        nrm = (t_arr.reshape(-1, 3) - center) / max(radius, 1e-9)
        return TriMesh(t_arr, nrm, color=color, opacity=1.0, gloss=0.5, shadow=0.1)

    def _build_wireframe_vmob(segs: np.ndarray, color: str = C_BLUE, stroke_width: float = 1.35,
                              opacity: float = 0.78) -> OpenGLVMobject:
        """Batch all 3D crease segments into ONE OpenGLVMobject (quadratic bezier: 3 pts/seg)."""
        vm = OpenGLVMobject(stroke_color=color, stroke_width=stroke_width, stroke_opacity=opacity,
                            fill_opacity=0.0, depth_test=True)
        if len(segs):
            p0 = segs[:, 0, :]
            p1 = segs[:, 1, :]
            pts = np.empty((len(segs) * 3, 3), dtype=float)
            pts[0::3] = p0
            pts[1::3] = 0.5 * (p0 + p1)
            pts[2::3] = p1
            vm.set_points(pts)
        return vm

    def to_manim(v):
        return P @ np.asarray(v, dtype=float)

    def mix_color(hex_a: str, hex_b: str, t: float) -> str:
        ra, rb = np.asarray(color_to_rgb(hex_a)), np.asarray(color_to_rgb(hex_b))
        return rgb_to_color(ra * (1.0 - t) + rb * t)

    def fix_all(*mobs):
        for m in mobs:
            if m is None:
                continue
            for sub in m.get_family():
                sub.fix_in_frame()

    cut_axis = "xyz".index(scene.cut.get("axis", "z"))
    cut_sign = 1.0 if scene.cut.get("keep", "neg") == "neg" else -1.0
    font_serif = _serif_family()

    # Use Kimi's 3B1B storyboard if available, else deterministic fallback from scene beats
    plan = story or story3b1b.fallback_story({
        "title": scene.title, "subtitle": scene.subtitle,
        "parts": scene.parts, "arrows": scene.arrows, "beats": scene.beats,
    })

    class Opto3B1BVideo(ThreeDScene):
        def construct(self):
            self.parts: dict[str, dict] = {}
            self._cap = None
            self._board: list = []
            self._divider = None
            self._cut_done = False
            self.labels_on: dict[str, Group] = {}
            self._split_x = ValueTracker(0.0)
            self._split_y = ValueTracker(0.18)
            self._in_split = False
            self._wireframe = None
            self._grid = None
            self._svg_dir = Path(config.media_dir) / "opto_svg"

            self._build_meshes()
            allp = np.concatenate([m.points[: len(m.points) // 3] for v in self.parts.values() for m in v["meshes"]])
            lo, hi = allp.min(axis=0), allp.max(axis=0)
            self._lo, self._hi = lo, hi
            self._corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
            self._sample = allp[np.linspace(0, len(allp) - 1, min(len(allp), 3500)).astype(int)]

            self._orient_camera()
            self._title_card()

            # Build 3D NumberPlane sitting cleanly beneath the Blender model
            grid_z = float(lo[2]) - 0.25
            span = max(6.5, float(np.max(hi[:2] - lo[:2])) * 1.15)
            self._grid = NumberPlane(
                x_range=[-span, span, 1.0],
                y_range=[-span, span, 1.0],
                background_line_style={"stroke_color": "#1a3c59", "stroke_width": 1.1, "stroke_opacity": 0.55},
                axis_config={"stroke_color": "#3988bd", "stroke_width": 2.0, "stroke_opacity": 0.78},
            )
            self._grid.shift(np.array([0.0, 0.0, grid_z]))

            # Keep 3D model pinned horizontally at -split_x even while orbiting around (0,0,0)!
            self.add_updater(self._camera_and_label_updater)
            self.begin_ambient_camera_rotation(rate=ambient)

            chapters = list(plan.get("chapters") or [])
            built = False
            for idx, ch in enumerate(chapters):
                act = ch.get("action", "highlight")
                nar = ch.get("narration") or ""
                dur = words_time(nar)
                focus_specs = ch.get("focus") or []

                if act == "blueprint_build" and not built:
                    self._do_blueprint_build(ch, dur)
                    built = True
                    continue
                if not built:
                    self._do_blueprint_build(ch, 3.0)
                    built = True

                self._clear_flow()
                if act == "synthesis":
                    self._do_synthesis(ch, dur)
                else:
                    self._ensure_split(True)
                    if act == "cutaway" and not self._cut_done:
                        self._do_cutaway(ch, dur)
                    elif act == "flow" and scene.arrows:
                        self._do_flow(ch, dur)
                    else:
                        self._do_chapter(ch, dur)

            if not chapters or chapters[-1].get("action") != "synthesis":
                self._do_synthesis({
                    "heading": "Synthesis",
                    "narration": plan.get("hook") or scene.subtitle or "",
                    "focus": [],
                    "equation": {"tex": plan.get("final_equation") or ""},
                }, 4.5)

            if self._cap is not None:
                self.play(FadeOut(self._cap), run_time=0.45)
            self.wait(0.35)

        # ---------- meshes + blueprint crease edges ----------
        def _build_meshes(self):
            all_edges = []
            if meshes is not None:
                source_parts = [dict(p) for p in scene.parts]
                known = {p["id"] for p in source_parts}
                for pid in meshes:
                    if pid not in known:
                        source_parts.append({"id": pid, "name": pid, "shape": "mesh", "size": [],
                                             "pos": [0, 0, 0], "rot": [0, 0, 0], "color": "#a8b8c8",
                                             "opacity": 1.0, "internal": False, "info": ""})
                order = sorted(source_parts, key=lambda p: 0 if p["internal"] else 1)
                per_part_edge_cap = max(45, 1100 // max(1, len(order)))
                for orig in order:
                    pid = orig["id"]
                    md = meshes.get(pid)
                    if md is None:
                        continue
                    tris, normals, rgba = md
                    world = np.asarray(tris, dtype=float).reshape(-1, 3, 3)
                    cn = np.asarray(normals, dtype=float).reshape(-1, 3)
                    if not len(world) or len(cn) != len(world) * 3:
                        continue
                    rgba = np.asarray(rgba, dtype=float).reshape(4)
                    p = dict(orig)
                    p["color"] = video_color(rgba[:3])
                    p["opacity"] = float(np.clip(rgba[3], 0.14, 1.0))

                    cen = world.mean(axis=1)
                    rem = np.zeros(len(world), dtype=bool) if p["internal"] else cut_sign * cen[:, cut_axis] > 1e-6
                    mt = world @ P.T
                    mn = (cn @ P.T).reshape(-1, 3, 3)
                    kt, kn = mt[~rem], mn[~rem].reshape(-1, 3)
                    ct, cn2 = mt[rem], mn[rem].reshape(-1, 3)

                    pts = mt.reshape(-1, 3)
                    lo, hi = pts.min(axis=0), pts.max(axis=0)
                    tgt = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2] + 0.72 * (hi[2] - lo[2])])
                    cand = (kt if len(kt) else mt).mean(axis=1)
                    anchor = cand[int(np.argmin(np.linalg.norm(cand - tgt, axis=1)))].copy()

                    style = dict(color=p["color"], opacity=p["opacity"], gloss=0.38, shadow=0.20)
                    keep = TriMesh(kt, kn, **style) if len(kt) else None
                    cut = TriMesh(ct, cn2, **style) if len(ct) else None
                    self.parts[pid] = {
                        "keep": keep, "cut": cut, "part": p, "anchor": anchor,
                        "meshes": [m for m in (keep, cut) if m is not None],
                    }
                    # Extract blueprint crease edges from outer + notable parts
                    edges = extract_feature_edges(mt, crease_deg=38.0, max_edges=per_part_edge_cap)
                    if len(edges):
                        all_edges.append(edges)
            else:
                order = sorted(scene.parts, key=lambda p: 0 if p["internal"] else 1)
                for p in order:
                    local = triangulate(geometry.faces_for_part(p, 1.0))
                    lnorm = smooth_normals(local)
                    kt_l, kn_l, ct_l, cn_l = [], [], [], []
                    insts = schema.part_instances(p)
                    top = -1e9
                    for pos, R in insts:
                        Rm = np.asarray(R, dtype=float)
                        w = local @ Rm.T + np.asarray(pos)
                        nw = lnorm @ Rm.T
                        cen = w.mean(axis=1)
                        rem = np.zeros(len(w), bool) if p["internal"] else cut_sign * cen[:, cut_axis] > 1e-6
                        mw, mn = w @ P.T, (nw @ P.T).reshape(-1, 3, 3)
                        kt_l.append(mw[~rem]); kn_l.append(mn[~rem])
                        ct_l.append(mw[rem]); cn_l.append(mn[rem])
                        top = max(top, float(mw[..., 2].max()))
                    kt, kn = np.concatenate(kt_l), np.concatenate(kn_l).reshape(-1, 3)
                    ct, cn = np.concatenate(ct_l), np.concatenate(cn_l).reshape(-1, 3)
                    style = dict(color=p["color"], opacity=p["opacity"], gloss=0.38, shadow=0.20)
                    keep = TriMesh(kt, kn, **style) if len(kt) else None
                    cut = TriMesh(ct, cn, **style) if len(ct) else None
                    a0 = to_manim(insts[0][0])
                    anchor = np.array([a0[0], a0[1], min(top, a0[2] + 3.0)])
                    self.parts[p["id"]] = {"keep": keep, "cut": cut, "part": p, "anchor": anchor,
                                           "meshes": [m for m in (keep, cut) if m is not None]}
                    if len(kt):
                        all_edges.append(extract_feature_edges(kt, crease_deg=38.0, max_edges=80))

            if all_edges:
                cat = np.concatenate(all_edges, axis=0)
                if len(cat) > 1300:
                    lens = np.linalg.norm(cat[:, 1] - cat[:, 0], axis=1)
                    cat = cat[np.argpartition(lens, -1300)[-1300:]]
                self._wireframe = _build_wireframe_vmob(cat, color=C_BLUE, stroke_width=1.35, opacity=0.82)

        def _orient_camera(self):
            cam = to_manim(scene.camera)
            r = np.linalg.norm(cam) or 1.0
            phi = math.degrees(math.acos(max(-1, min(1, cam[2] / r))))
            theta = math.degrees(math.atan2(cam[1], cam[0]))
            phi = min(max(phi, 58), 72)
            # Fit cleanly inside LEFT half with generous margin for borderless 3B1B callouts
            pts = self._sample
            avail_w = 4.6
            avail_h = 3.7
            zoom = 1.0
            for _ in range(2):
                need = 0.0
                for dt in range(0, 360, 30):
                    self.set_camera_orientation(phi=phi * DEGREES, theta=(theta + dt) * DEGREES, zoom=zoom)
                    q = self.project_many(pts)
                    ext = np.abs(q).max(axis=0) * 2
                    need = max(need, ext[0] / avail_w, ext[1] / avail_h)
                zoom = float(np.clip(zoom / max(need, 1e-3), 0.26, 2.1))
            self._split_zoom = zoom
            self._center_zoom = min(2.4, zoom * 1.28)
            self.set_camera_orientation(phi=phi * DEGREES, theta=theta * DEGREES, zoom=self._center_zoom)

        def _camera_and_label_updater(self, dt):
            sx = float(self._split_x.get_value())
            sy = float(self._split_y.get_value())
            cam = self.camera
            R = np.asarray(cam.inverse_rotation_matrix)
            # Shift camera right along screen-right (R[0]) so model stays pinned left at -sx in screen space!
            w, h = cam.get_shape()
            world_sx = sx * (w / config.frame_width)
            world_sy = sy * (h / config.frame_height)
            cam.move_to(R[0] * world_sx - R[1] * world_sy)
            self._place_labels_now()

        def _ensure_split(self, on: bool):
            if on == self._in_split:
                return
            self._in_split = on
            if on:
                div = Line(np.array([0.05, 3.05, 0.0]), np.array([0.05, -2.85, 0.0]),
                           color="#1c4463", stroke_width=1.5)
                fix_all(div)
                self._divider = div
                self.play(
                    self._split_x.animate.set_value(3.25),
                    self._split_y.animate.set_value(0.28),
                    self.camera.animate.set_zoom(self._split_zoom),
                    Create(div),
                    run_time=0.85, rate_func=smooth,
                )
            else:
                anims = [
                    self._split_x.animate.set_value(0.0),
                    self._split_y.animate.set_value(0.18),
                    self.camera.animate.set_zoom(self._center_zoom),
                ]
                if self._divider is not None:
                    anims.append(FadeOut(self._divider))
                    self._divider = None
                self.play(*anims, run_time=0.85, rate_func=smooth)

        # ---------- 2D typography & LaTeX helpers ----------
        def _img(self, arr: np.ndarray, scale: float = 1.0):
            m = FlatImage(arr, (arr.shape[0] / PX_PER_UNIT) * scale)
            fix_all(m)
            return m

        def _math_svg(self, tex: str, *, max_w: float = 5.6, height: float = 0.72, color: str = C_WHITE):
            svg = render_mathtext_svg(tex, self._svg_dir, color)
            if svg is None:
                return None
            try:
                m = SVGMobject(str(svg))
                if not len(m.submobjects):
                    return None
                m.set_height(height)
                if m.width > max_w:
                    m.scale_to_fit_width(max_w)
                m.set_fill(color, opacity=1.0).set_stroke(color, width=0.22)
                fix_all(m)
                return m
            except Exception:
                return None

        def _title_card(self):
            title_txt = plan.get("title") or scene.title
            hook_txt = plan.get("hook") or scene.subtitle or ""
            t = Text(title_txt, font=font_serif, font_size=54, color=C_WHITE)
            if t.width > 12.2:
                t.scale_to_fit_width(12.2)
            t.move_to(UP * 0.45)
            ul = Line(t.get_left() + DOWN * 0.45, t.get_right() + DOWN * 0.45, color=C_BLUE, stroke_width=2.2)
            s = Text(hook_txt or " ", font=font_serif, font_size=26, slant="ITALIC", color=C_BLUE)
            if s.width > 11.8:
                s.scale_to_fit_width(11.8)
            s.next_to(ul, DOWN, buff=0.35)
            fix_all(t, ul, s)
            self.play(Write(t), run_time=1.2)
            self.play(Create(ul), FadeIn(s, shift=UP * 0.15), run_time=0.75)
            self.wait(0.9)

            small = self._img(raster_text([textwrap.shorten(title_txt, 54, placeholder="…")],
                                          line_h=0.30, color=C_MUTED, italic=False))
            small.to_corner(UP + LEFT, buff=0.28)
            self.play(FadeOut(t), FadeOut(ul), FadeOut(s), FadeIn(small), run_time=0.65)

        def _show_caption(self, say: str | None):
            if not say:
                return
            lines = textwrap.wrap(say.strip(), 78)[:2]
            arr = raster_text(lines, line_h=0.30, color=C_WHITE, pad=(0.24, 0.10), line_gap=0.22)
            cap = self._img(arr)
            cap.to_edge(DOWN, buff=0.22)
            if self._cap is not None:
                self.play(FadeOut(self._cap), FadeIn(cap), run_time=0.38)
            else:
                self.play(FadeIn(cap), run_time=0.38)
            self._cap = cap

        # ---------- 3D projection + borderless 3B1B callouts ----------
        def project_many(self, pts) -> np.ndarray:
            cam = self.camera
            R = np.asarray(cam.inverse_rotation_matrix)
            q = (np.asarray(pts, dtype=float) - cam.get_center()) @ R.T
            f = cam.get_focal_distance()
            psf = np.maximum(0.05, f / np.maximum(1e-6, f - q[:, 2]))
            w, h = cam.get_shape()
            return np.stack([q[:, 0] * psf * config.frame_width / w, q[:, 1] * psf * config.frame_height / h,
                             np.zeros(len(q))], axis=1)

        def project(self, p) -> np.ndarray:
            cam = self.camera
            R = np.asarray(cam.inverse_rotation_matrix)
            q = R @ (np.asarray(p, dtype=float) - cam.get_center())
            f = cam.get_focal_distance()
            psf = max(0.05, f / max(1e-6, f - q[2]))
            w, h = cam.get_shape()
            return np.array([q[0] * psf * config.frame_width / w, q[1] * psf * config.frame_height / h, 0.0])

        def _label(self, pid: str, text: str, color_hex: str, anchor=None):
            if anchor is None:
                anchor = self.parts[pid]["anchor"]
            text = textwrap.shorten(str(text), 24, placeholder="…")
            # Borderless 3Blue1Brown colored serif label (NO sticky-note rectangle!)
            chip = self._img(raster_text([text], line_h=0.26, color=color_hex, bold=False,
                                         pad=(0.08, 0.04)))
            line = Line(ORIGIN, RIGHT, color=color_hex, stroke_width=1.8)
            dot = Dot(ORIGIN, radius=0.055, color=color_hex)
            fix_all(line, dot, chip)
            g = Group(line, dot, chip)
            g.anchor3d = np.asarray(anchor, dtype=float)
            self._place_labels_now([g])
            return g

        def _place_labels_now(self, extra=()):
            groups = list(self.labels_on.values()) + [g for g in extra if g not in self.labels_on.values()]
            if not groups:
                return
            fw, fh = config.frame_width / 2, config.frame_height / 2
            x_min = -fw + 0.22
            x_max = -0.18 if self._in_split else fw - 0.22
            corners = self.project_many(self._corners)
            xl, xr = corners[:, 0].min(), corners[:, 0].max()
            cx = (xl + xr) / 2
            anchors = {id(g): self.project(g.anchor3d) for g in groups}
            cap_top = float(self._cap.get_top()[1]) + 0.20 if self._cap is not None else -fh + 1.45
            top, bottom, gap = fh - 0.72, max(-fh + 1.45, cap_top), 0.14

            if self._in_split:
                # Place callouts cleanly ABOVE and BELOW the left-pane 3D model so text NEVER overlaps mesh!
                yt = float(corners[:, 1].max())
                yb = float(corners[:, 1].min())
                ymid = (yt + yb) / 2.0
                top_row = sorted([g for g in groups if anchors[id(g)][1] >= ymid], key=lambda g: anchors[id(g)][0])
                bot_row = sorted([g for g in groups if anchors[id(g)][1] < ymid], key=lambda g: anchors[id(g)][0])
                # Balance if all 3 landed on one side
                if len(top_row) == 3:
                    bot_row.append(top_row.pop(1))
                elif len(bot_row) == 3:
                    top_row.append(bot_row.pop(1))

                def place_row(row, y_target):
                    if not row:
                        return
                    n = len(row)
                    xs = [max(x_min + g[2].width / 2, min(x_max - g[2].width / 2, anchors[id(g)][0])) for g in row]
                    if n == 2:
                        min_sep = (row[0][2].width + row[1][2].width) / 2 + 0.35
                        if xs[1] - xs[0] < min_sep:
                            mid = max(x_min + min_sep / 2 + 0.4, min(x_max - min_sep / 2 - 0.4, (xs[0] + xs[1]) / 2))
                            xs = [mid - min_sep / 2, mid + min_sep / 2]
                    for g, x in zip(row, xs):
                        line, dot, chip = g
                        a = anchors[id(g)]
                        x = max(x_min + chip.width / 2, min(x_max - chip.width / 2, x))
                        chip.move_to(np.array([x, y_target, 0.0]))
                        dy = -chip.height / 2 - 0.05 if y_target > a[1] else chip.height / 2 + 0.05
                        end = np.array([x, y_target + dy, 0.0])
                        if np.linalg.norm(end - a) < 1e-3:
                            end = a + np.array([0.0, 0.02, 0.0])
                        line.put_start_and_end_on(a, end)
                        dot.move_to(a)

                place_row(top_row, min(top - 0.18, max(yt + 0.42, 2.35)))
                place_row(bot_row, max(bottom + 0.22, min(yb - 0.42, -1.95)))
                return

            # Center-stage mode (synthesis/orbit): balanced left & right columns
            for g in groups:
                if getattr(g, "side", None) is None:
                    want = 1 if anchors[id(g)][0] >= cx else -1
                    n_same = sum(1 for o in groups if getattr(o, "side", None) == want)
                    n_other = sum(1 for o in groups if getattr(o, "side", None) == -want)
                    g.side = -want if n_same > n_other + 1 else want
            for side in (1, -1):
                col = sorted([g for g in groups if g.side == side], key=lambda g: -anchors[id(g)][1])
                if not col:
                    continue
                hs = [g[2].height for g in col]
                ys = []
                for i, g in enumerate(col):
                    y = min(anchors[id(g)][1], top - hs[i] / 2)
                    if ys:
                        y = min(y, ys[-1] - hs[i - 1] / 2 - hs[i] / 2 - gap)
                    ys.append(y)
                for i in range(len(col) - 1, -1, -1):
                    lim = bottom + hs[i] / 2 if i == len(col) - 1 else ys[i + 1] + hs[i + 1] / 2 + hs[i] / 2 + gap
                    ys[i] = max(ys[i], lim)
                for g, y in zip(col, ys):
                    line, dot, chip = g
                    a = anchors[id(g)]
                    w = chip.width
                    if side == 1:
                        x = min(max(xr + 0.35, a[0] + 0.75) + w / 2, x_max - w / 2)
                        end = np.array([x - w / 2 - 0.04, y, 0.0])
                    else:
                        x = max(min(xl - 0.35, a[0] - 0.75) - w / 2, x_min + w / 2)
                        end = np.array([x + w / 2 + 0.04, y, 0.0])
                    chip.move_to(np.array([x, y, 0.0]))
                    if np.linalg.norm(end - a) < 1e-3:
                        end = a + np.array([0.01, 0, 0])
                    line.put_start_and_end_on(a, end)
                    dot.move_to(a)

        # ---------- Right-half 3Blue1Brown Chalkboard ----------
        def _clear_board(self):
            if not self._board:
                return
            self.play(*[FadeOut(m) for m in self._board], run_time=0.4)
            self._board.clear()

        def _present_board(self, ch: dict):
            """Animate a full 3Blue1Brown chapter board on the right half:
               Heading -> Computer Modern LaTeX Equation + SurroundingRectangle ->
               Color-coded Symbol Legend -> Animated 2D Diagram (curve / cycle / vectors / chain)."""
            self._clear_board()
            rx = 3.42
            board_mobs = []

            # 1. Chapter heading + glowing blue rule
            heading = ch.get("heading") or ""
            hdr = self._img(raster_text([heading], line_h=0.33, color=C_BLUE, bold=True, align="left"))
            hdr.move_to(np.array([rx, 3.12, 0.0]))
            if hdr.width > 5.9:
                hdr.scale_to_fit_width(5.9)
            hdr.align_to(np.array([0.55, 0, 0]), LEFT)
            rule = Line(np.array([0.55, 2.86, 0.0]), np.array([6.45, 2.86, 0.0]),
                        color="#265d82", stroke_width=1.4)
            fix_all(rule)
            self.play(FadeIn(hdr, shift=RIGHT * 0.15), Create(rule), run_time=0.55)
            board_mobs.extend([hdr, rule])

            # 2. Computer Modern LaTeX equation (Write!) + SurroundingRectangle
            eq_spec = ch.get("equation")
            y_cursor = 2.25
            if isinstance(eq_spec, dict) and eq_spec.get("tex"):
                eq_mob = self._math_svg(eq_spec["tex"], max_w=5.4, height=0.68, color=C_WHITE)
                if eq_mob is not None:
                    eq_mob.move_to(np.array([rx, y_cursor, 0.0]))
                    box_col = story3b1b.color_hex(eq_spec.get("box_color"), 1)
                    box = SurroundingRectangle(eq_mob, color=box_col, buff=0.14, stroke_width=1.7)
                    fix_all(box)
                    self.play(Write(eq_mob), run_time=1.0)
                    self.play(Create(box), run_time=0.45)
                    board_mobs.extend([eq_mob, box])
                    y_cursor = float(box.get_bottom()[1]) - 0.30

                # Color-coded symbol legend directly beneath equation
                terms = eq_spec.get("terms") or []
                if terms:
                    term_mobs = []
                    for ti, tm in enumerate(terms[:3]):
                        col_h = story3b1b.color_hex(tm.get("color"), ti)
                        sym_arr = raster_mathtext_png(tm["sym"], color=col_h, fontsize=24)
                        txt_arr = raster_text([": " + tm["meaning"]], line_h=0.26, color="#C8DCEF", align="left")
                        g_parts = []
                        if sym_arr is not None:
                            sm = self._img(sym_arr, scale=0.56)
                            g_parts.append(sm)
                        tm_img = self._img(txt_arr)
                        if g_parts:
                            tm_img.next_to(g_parts[0], RIGHT, buff=0.05)
                        g_parts.append(tm_img)
                        tg = Group(*g_parts)
                        term_mobs.append(tg)
                    row = Group(*term_mobs).arrange(RIGHT, buff=0.35)
                    if row.width > 5.95:
                        row.scale_to_fit_width(5.95)
                    row.move_to(np.array([rx, y_cursor, 0.0]))
                    self.play(LaggedStart(*[FadeIn(t, shift=UP * 0.08) for t in term_mobs], lag_ratio=0.18),
                              run_time=0.55)
                    board_mobs.append(row)
                    y_cursor = float(row.get_bottom()[1]) - 0.30

            # 3. Animated 2D Diagram in remaining space y in [-2.35, y_cursor]
            diag = ch.get("diagram")
            if isinstance(diag, dict):
                y_bot = -2.30
                y_top = min(y_cursor, 0.95)
                if y_top - y_bot >= 1.4:
                    dmobs = self._animate_diagram(diag, rx, (y_top + y_bot) / 2.0,
                                                  width=5.45, height=y_top - y_bot)
                    board_mobs.extend(dmobs)

            self._board = board_mobs

        def _animate_diagram(self, diag: dict, cx: float, cy: float, width: float, height: float) -> list:
            kind = diag.get("kind")
            mobs = []
            title = diag.get("title") or ""
            if title:
                t_img = self._img(raster_text([title], line_h=0.25, color="#C8DCEF", italic=True, pad=(0.08, 0.03)))
                if t_img.width > width:
                    t_img.scale_to_fit_width(width)
                t_img.move_to(np.array([cx, cy + height / 2.0 - 0.14, 0.0]))
                self.play(FadeIn(t_img), run_time=0.25)
                mobs.append(t_img)
                cy -= 0.17
                height -= 0.36

            if kind in ("curve", "cycle"):
                xr = diag["x_range"]
                yr = diag["y_range"]
                ax = Axes(
                    x_range=xr, y_range=yr,
                    x_length=width * 0.80, y_length=height * 0.78,
                    axis_config={"color": "#64a7cf", "stroke_width": 1.9, "include_tip": True,
                                 "tip_length": 0.15, "tick_size": 0.06},
                )
                ax.move_to(np.array([cx + 0.14, cy + 0.05, 0.0]))
                xl = self._img(raster_text([diag.get("x_label", "x")], line_h=0.24, color="#C8DCEF", italic=True, pad=(0.08, 0.03)))
                xl.next_to(ax.x_axis, DOWN, buff=0.14)
                yl = self._img(raster_text([diag.get("y_label", "y")], line_h=0.24, color="#C8DCEF", italic=True, pad=(0.08, 0.03)))
                yl.next_to(ax.y_axis, LEFT, buff=0.14).shift(UP * 0.1)
                fix_all(ax)
                self.play(Create(ax), FadeIn(xl), FadeIn(yl), run_time=0.65)
                mobs.extend([ax, xl, yl])

                def clamp_pt(px, py):
                    return ax.c2p(max(xr[0], min(xr[1], px)), max(yr[0], min(yr[1], py)))

                if kind == "curve":
                    prim_path = None
                    for ci, c in enumerate(diag.get("curves") or []):
                        pts = [clamp_pt(px, py) for px, py in c["points"]]
                        col = story3b1b.color_hex(c.get("color"), ci)
                        curve = OpenGLVMobject(stroke_color=col, stroke_width=3.0)
                        curve.set_points_smoothly(pts)
                        fix_all(curve)
                        anims = [Create(curve)]
                        if c.get("fill") and len(pts) >= 3:
                            base0 = ax.c2p(max(xr[0], min(xr[1], c["points"][0][0])), yr[0])
                            base1 = ax.c2p(max(xr[0], min(xr[1], c["points"][-1][0])), yr[0])
                            poly = Polygon(base0, *pts, base1, stroke_width=0, fill_color=col, fill_opacity=0.16)
                            fix_all(poly)
                            anims.append(FadeIn(poly))
                            mobs.append(poly)
                        self.play(*anims, run_time=0.85)
                        mobs.append(curve)
                        if ci == 0:
                            prim_path = curve
                        if c.get("label"):
                            cl = self._img(raster_text([c["label"]], line_h=0.20, color=col))
                            cl.move_to(pts[-1] + np.array([-0.45, 0.24 if ci == 0 else -0.24, 0.0]))
                            self.play(FadeIn(cl), run_time=0.22)
                            mobs.append(cl)
                    hp = diag.get("highlight_point")
                    if hp:
                        p_hi = clamp_pt(hp[0], hp[1])
                        px0 = ax.c2p(max(xr[0], min(xr[1], hp[0])), yr[0])
                        dl = DashedLine(px0, p_hi, color=C_YELLOW, stroke_width=1.4, dash_length=0.08)
                        dt_hi = Dot(p_hi, radius=0.065, color=C_YELLOW)
                        fix_all(dl, dt_hi)
                        h_anims = [Create(dl), FadeIn(dt_hi)]
                        mobs.extend([dl, dt_hi])
                        if hp[2]:
                            hl = self._img(raster_text([hp[2]], line_h=0.20, color=C_YELLOW))
                            hl.next_to(dt_hi, UP, buff=0.12)
                            h_anims.append(FadeIn(hl))
                            mobs.append(hl)
                        self.play(*h_anims, run_time=0.45)
                    if prim_path is not None:
                        tracer = Dot(prim_path.get_start(), radius=0.07, color=C_YELLOW)
                        fix_all(tracer)
                        self.add(tracer)
                        self.play(MoveAlongPath(tracer, prim_path), run_time=1.1, rate_func=smooth)
                        mobs.append(tracer)
                else:
                    # Closed thermodynamic / mechanical cycle loop
                    pts = [clamp_pt(px, py) for px, py in diag["loop"]]
                    if np.linalg.norm(pts[0] - pts[-1]) > 1e-3:
                        pts.append(pts[0])
                    col = story3b1b.color_hex(diag.get("shade_color"), 0)
                    loop_mob = OpenGLVMobject(stroke_color=col, stroke_width=3.0)
                    loop_mob.set_points_smoothly(pts)
                    fill_poly = Polygon(*pts, stroke_width=0, fill_color=col, fill_opacity=0.20)
                    fix_all(loop_mob, fill_poly)
                    self.play(Create(loop_mob), run_time=1.0)
                    self.play(FadeIn(fill_poly), run_time=0.35)
                    mobs.extend([loop_mob, fill_poly])
                    st_anims = []
                    for si, st in enumerate(diag.get("stages") or []):
                        sp = clamp_pt(st["pos"][0], st["pos"][1])
                        scol = story3b1b.color_hex(st.get("color"), si + 1)
                        sd = Dot(sp, radius=0.055, color=scol)
                        sl = self._img(raster_text([st["label"]], line_h=0.19, color=scol))
                        off = UP * 0.22 if sp[1] >= cy else DOWN * 0.22
                        sl.move_to(sp + off)
                        fix_all(sd)
                        st_anims.extend([FadeIn(sd), FadeIn(sl)])
                        mobs.extend([sd, sl])
                    if st_anims:
                        self.play(*st_anims, run_time=0.45)
                    tracer = Dot(pts[0], radius=0.075, color=C_YELLOW)
                    fix_all(tracer)
                    self.add(tracer)
                    self.play(MoveAlongPath(tracer, loop_mob), run_time=1.35, rate_func=linear)
                    mobs.append(tracer)

            elif kind == "vectors":
                # Local coords x in [-2.4, 2.4], y in [-1.3, 1.3] mapped cleanly into (cx, cy, width, height)
                sx = (width * 0.88) / 4.8
                sy = (height * 0.84) / 2.6

                def vpt(p):
                    return np.array([cx + max(-2.4, min(2.4, p[0])) * sx,
                                     cy + max(-1.3, min(1.3, p[1])) * sy, 0.0])

                if diag.get("axes_cross", True):
                    hx = DashedLine(vpt([-2.3, 0]), vpt([2.3, 0]), color="#2c597a", stroke_width=1.2, dash_length=0.1)
                    vy = DashedLine(vpt([0, -1.2]), vpt([0, 1.2]), color="#2c597a", stroke_width=1.2, dash_length=0.1)
                    fix_all(hx, vy)
                    self.play(Create(hx), Create(vy), run_time=0.4)
                    mobs.extend([hx, vy])
                for dl in diag.get("dashed") or []:
                    dline = DashedLine(vpt(dl["from"]), vpt(dl["to"]), color=C_MUTED, stroke_width=1.4, dash_length=0.09)
                    fix_all(dline)
                    self.play(Create(dline), run_time=0.25)
                    mobs.append(dline)
                for vi, v in enumerate(diag.get("vectors") or []):
                    p0, p1 = vpt(v["from"]), vpt(v["to"])
                    if np.linalg.norm(p1 - p0) < 0.08:
                        continue
                    vcol = story3b1b.color_hex(v.get("color"), vi)
                    arr = Arrow(p0, p1, buff=0, color=vcol, stroke_width=3.2, max_tip_length_to_length_ratio=0.22)
                    fix_all(arr)
                    anims = [Create(arr)]
                    mobs.append(arr)
                    if v.get("label"):
                        vl = self._img(raster_text([v["label"]], line_h=0.21, color=vcol, italic=True))
                        d_u = (p1 - p0) / max(float(np.linalg.norm(p1 - p0)), 1e-6)
                        vl.move_to(p1 + d_u * 0.24 + np.array([0, 0.14, 0]))
                        anims.append(FadeIn(vl))
                        mobs.append(vl)
                    self.play(*anims, run_time=0.45)

            elif kind == "chain":
                nodes = diag.get("nodes") or []
                n = len(nodes)
                nw = min(1.32, (width - 0.35 * (n - 1)) / max(1, n))
                nh = min(0.95, height * 0.56)
                xs = np.linspace(cx - (width - nw) / 2.0, cx + (width - nw) / 2.0, n) if n > 1 else [cx]
                boxes = []
                for ni, nd in enumerate(nodes):
                    col = story3b1b.color_hex(nd.get("color"), ni)
                    rect = RoundedRectangle(corner_radius=0.10, width=nw, height=nh,
                                            stroke_color=col, stroke_width=2.0,
                                            fill_color=col, fill_opacity=0.12)
                    rect.move_to(np.array([xs[ni], cy, 0.0]))
                    fix_all(rect)
                    lines = [nd["label"]] + ([nd["sub"]] if nd.get("sub") else [])
                    lbl = self._img(raster_text(lines, line_h=0.20, color=col, pad=(0.04, 0.04)))
                    if lbl.width > nw - 0.12:
                        lbl.scale_to_fit_width(nw - 0.12)
                    lbl.move_to(rect.get_center())
                    boxes.append((rect, lbl))
                    anims = [Create(rect), FadeIn(lbl)]
                    if ni > 0:
                        prev = boxes[ni - 1][0]
                        arr = Arrow(prev.get_right(), rect.get_left(), buff=0.06, color=C_MUTED,
                                    stroke_width=2.0, max_tip_length_to_length_ratio=0.35)
                        fix_all(arr)
                        anims.append(Create(arr))
                        mobs.append(arr)
                    self.play(*anims, run_time=0.45)
                    mobs.extend([rect, lbl])
                if len(boxes) >= 2:
                    pulse = Dot(boxes[0][0].get_center(), radius=0.075, color=C_YELLOW)
                    path = OpenGLVMobject()
                    path.set_points_as_corners([b[0].get_center() for b in boxes])
                    fix_all(pulse)
                    self.add(pulse)
                    self.play(MoveAlongPath(pulse, path), run_time=1.0, rate_func=smooth)
                    self.play(FadeOut(pulse), run_time=0.25)

            return mobs

        # ---------- 3D styling & chapters ----------
        def _style_anims(self, focus_map: dict[str, str], dim_op: float = 0.18):
            anims = []
            has_focus = bool(focus_map)
            for pid, v in self.parts.items():
                p = v["part"]
                if pid in focus_map:
                    col = mix_color(p["color"], focus_map[pid], 0.52)
                    op = max(0.88, p["opacity"])
                elif not has_focus:
                    col = p["color"]
                    op = p["opacity"]
                else:
                    col = mix_color(p["color"], C_DIM_MESH, 0.65)
                    op = min(dim_op, p["opacity"])
                for m in v["meshes"]:
                    if m is v["cut"] and self._cut_done:
                        continue
                    anims.append(Tint(m, col, op))
            return anims

        def _swap_labels(self, focus_specs: list[dict]):
            want = {}
            for i, f in enumerate(focus_specs[:3]):
                pid = f.get("part")
                if pid in self.parts and pid != "_structure":
                    want[pid] = (f.get("label") or self.parts[pid]["part"]["name"],
                                 story3b1b.color_hex(f.get("color"), i))
            old = [self.labels_on.pop(k) for k in list(self.labels_on) if k not in want]
            new = []
            for pid, (lbl, col) in want.items():
                if pid not in self.labels_on:
                    lab = self._label(pid, lbl, col)
                    self.labels_on[pid] = lab
                    new.append(lab)
            return old, new, {pid: col for pid, (_, col) in want.items()}

        def _do_blueprint_build(self, ch: dict, dur: float):
            self._show_caption(ch.get("narration"))
            # 1. Draw the 3D NumberPlane
            self.play(Create(self._grid), run_time=1.0)
            # 2. Draw the glowing cyan blueprint wireframe!
            if self._wireframe is not None:
                self.play(Create(self._wireframe), run_time=1.5)
            # 3. Bloom shaded 3D Blender surfaces inside the wireframe
            anims = [Reveal(m) for v in self.parts.values() for m in v["meshes"]]
            if self._wireframe is not None:
                anims.append(self._wireframe.animate.set_stroke(opacity=0.20))
            self.play(LaggedStart(*anims, lag_ratio=min(0.18, 2.2 / max(1, len(anims)))), run_time=1.9)
            # 4. Glide into split-stage and write Chapter 1's math/diagram on the right!
            if ch.get("equation") or ch.get("diagram"):
                self._ensure_split(True)
                old, new, fmap = self._swap_labels(ch.get("focus") or [])
                if fmap:
                    self.play(*self._style_anims(fmap, 0.22), *[FadeIn(l) for l in new], run_time=0.6)
                self._present_board(ch)
                self.wait(max(0.8, dur - 2.6))

        def _do_chapter(self, ch: dict, dur: float):
            self._show_caption(ch.get("narration"))
            old, new, fmap = self._swap_labels(ch.get("focus") or [])
            self.play(*self._style_anims(fmap, 0.18), *[FadeOut(o) for o in old], run_time=0.65)
            if new:
                self.play(LaggedStart(*[FadeIn(l) for l in new], lag_ratio=0.2), run_time=0.55)
            self._present_board(ch)
            self.wait(max(0.8, dur - 2.4))

        def _do_cutaway(self, ch: dict, dur: float):
            self._show_caption(ch.get("narration"))
            normal3 = np.zeros(3)
            normal3[cut_axis] = 1.0
            n_m = to_manim(normal3)
            plane = Square(side_length=9.2, fill_color=C_BLUE, fill_opacity=0.14,
                           stroke_color=C_BLUE, stroke_width=2.6)
            z = np.array([0, 0, 1.0])
            if abs(np.dot(z, n_m)) < 0.999:
                plane.rotate(math.acos(np.clip(np.dot(z, n_m), -1, 1)), axis=np.cross(z, n_m), about_point=ORIGIN)
            plane.move_to(n_m * 4.5 * cut_sign)
            self.play(FadeIn(plane), run_time=0.35)
            self.play(plane.animate.move_to(ORIGIN), run_time=1.05, rate_func=smooth)
            cuts = [v["cut"] for v in self.parts.values() if v["cut"] is not None]
            lift = n_m * 3.2 * cut_sign
            if cuts:
                rm_anims = [ShiftFade(c, lift, 0.0) for c in cuts] + [
                    plane.animate.set_fill(opacity=0.04).set_stroke(opacity=0.25)
                ]
                if self._wireframe is not None:
                    rm_anims.append(self._wireframe.animate.set_stroke(opacity=0.08))
                self.play(*rm_anims, run_time=1.25)
                self.remove(*cuts)
            self._cut_done = True
            old, new, fmap = self._swap_labels(ch.get("focus") or [])
            self.play(FadeOut(plane), *self._style_anims(fmap, 0.20), *[FadeOut(o) for o in old], run_time=0.6)
            if new:
                self.play(LaggedStart(*[FadeIn(l) for l in new], lag_ratio=0.2), run_time=0.55)
            self._present_board(ch)
            self.wait(max(0.7, dur - 2.6))

        def _do_flow(self, ch: dict, dur: float):
            self._show_caption(ch.get("narration"))
            old, new, fmap = self._swap_labels(ch.get("focus") or [])
            self.play(*self._style_anims(fmap, 0.24), *[FadeOut(o) for o in old], run_time=0.55)
            if new:
                self.play(LaggedStart(*[FadeIn(l) for l in new], lag_ratio=0.2), run_time=0.45)
            arrows, segs = [], []
            palette_flow = [C_BLUE, C_YELLOW, C_GOLD, C_TEAL, C_MAROON, C_GREEN]
            for i, a in enumerate(scene.arrows[:6]):
                s, e = to_manim(a["from"]), to_manim(a["to"])
                if np.linalg.norm(e - s) < 1e-3:
                    continue
                arrows.append(_make_arrow_mesh(s, e, palette_flow[i % len(palette_flow)]))
                segs.append((s, e))
            if arrows:
                self.play(LaggedStart(*[Reveal(a) for a in arrows], lag_ratio=0.15), run_time=0.7)
            self._present_board(ch)
            dots, runs = [], []
            for s, e in segs:
                for k in range(3):
                    d = _make_sphere_mesh(s, radius=0.085, color=C_YELLOW)
                    dots.append(d)
                    runs.append(SlideAlong(d, s, e, phase=k / 3, cycles=2.0, rate_func=linear))
            if runs:
                self.add(*dots)
                self.play(*runs, run_time=max(2.2, dur - 1.5), rate_func=linear)
                self.remove(*dots)
            self.flow_arrows = arrows

        def _clear_flow(self):
            arrows = getattr(self, "flow_arrows", None)
            if not arrows:
                return
            self.play(*[Tint(a, a.color, 0.0) for a in arrows], run_time=0.4)
            self.remove(*arrows)
            self.flow_arrows = None

        def _do_synthesis(self, ch: dict, dur: float):
            self._show_caption(ch.get("narration"))
            self._clear_board()
            old = [self.labels_on.pop(k) for k in list(self.labels_on)]
            if old:
                self.play(*[FadeOut(o) for o in old], run_time=0.4)
            self._ensure_split(False)

            # Top-center overarching Computer Modern formula
            eq_tex = (ch.get("equation") or {}).get("tex") or plan.get("final_equation") or ""
            top_eq = self._math_svg(eq_tex, max_w=7.5, height=0.62, color=C_WHITE) if eq_tex else None
            top_box = None
            if top_eq is not None:
                top_eq.move_to(np.array([0.0, 3.05, 0.0]))
                top_box = SurroundingRectangle(top_eq, color=C_YELLOW, buff=0.14, stroke_width=1.6)
                fix_all(top_box)

            # Show 4-5 key borderless 3B1B callouts around the centered cutaway
            show_specs = list(ch.get("focus") or [])
            used = {f.get("part") for f in show_specs}
            for l in scene.labels:
                if len(show_specs) >= 5:
                    break
                pid = l.get("part")
                if pid in self.parts and pid != "_structure" and pid not in used:
                    used.add(pid)
                    show_specs.append({"part": pid, "label": l["text"],
                                       "color": story3b1b.COLOR_CYCLE[len(show_specs) % len(story3b1b.COLOR_CYCLE)]})
            new_labs = []
            for i, sp in enumerate(show_specs[:5]):
                pid = sp["part"]
                if pid in self.parts:
                    lab = self._label(pid, sp["label"], story3b1b.color_hex(sp.get("color"), i))
                    self.labels_on[pid] = lab
                    new_labs.append(lab)

            anims = self._style_anims({}, 1.0)
            if top_eq is not None:
                anims.append(Write(top_eq))
            self.play(*anims, run_time=0.9)
            post = []
            if top_box is not None:
                post.append(Create(top_box))
            if new_labs:
                post.append(LaggedStart(*[FadeIn(l) for l in new_labs], lag_ratio=0.15))
            if post:
                self.play(*post, run_time=0.8)

            self.stop_ambient_camera_rotation()
            self.begin_ambient_camera_rotation(rate=0.26)
            self.wait(max(2.5, dur - 1.2))
            self.stop_ambient_camera_rotation()

    return Opto3B1BVideo


def render(scene: schema.Scene | str | Path, out_path: str | Path, quality: str = "l",
           meshes: dict | None = None, story: dict | None = None) -> Path:
    import os
    from manim import tempconfig

    ffmpeg_path = visual_qa.find_tool("ffmpeg")
    if Path(ffmpeg_path).is_file():
        ffmpeg_dir = str(Path(ffmpeg_path).parent)
        cur_path = os.environ.get("PATH", "")
        if ffmpeg_dir.lower() not in cur_path.lower():
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + cur_path

    story_file = None
    if isinstance(scene, (str, Path)):
        input_path = Path(scene)
        story_file = input_path.with_suffix(".story.json")
        if input_path.is_dir() and (input_path / "scene.json").is_file():
            from . import manim_forge
            return manim_forge.render_forge_video(input_path, out_path, quality=quality)
        scene = schema.load(str(input_path))

    if story is None and story_file is not None and story_file.is_file():
        # written by the same Kimi call that built the 3D scene
        raw_story = json.loads(story_file.read_text(encoding="utf-8"))
        if raw_story.get("chapters"):
            story = story3b1b._clean_story(raw_story, scene.to_dict())
    if story is None:
        story = story3b1b.ensure_story_for_scene(scene.to_dict())

    out_path = Path(out_path).resolve()
    media = out_path.parent / ".manim" / out_path.stem
    q = {"l": "low_quality", "m": "medium_quality", "h": "high_quality"}[quality]
    cls = build_scene_class(scene, meshes=meshes, story=story)
    with tempconfig({"renderer": "opengl", "write_to_movie": True, "format": "mp4", "quality": q,
                     "media_dir": str(media), "output_file": out_path.stem, "disable_caching": True,
                     "verbosity": "WARNING", "progress_bar": "none", "preview": False,
                     "background_color": BG}):
        sc = cls()
        sc.render()
        produced = Path(sc.renderer.file_writer.movie_file_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(produced), out_path)
    return out_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("out")
    ap.add_argument("--quality", "-q", default="l", choices=["l", "m", "h"])
    ap.add_argument("--regen-story", action="store_true", help="regenerate 3B1B storyboard via Kimi")
    a = ap.parse_args(argv)

    input_path = Path(a.scene)
    if input_path.is_dir() and (input_path / "scene.json").is_file():
        from . import manim_forge
        print(manim_forge.render_forge_video(input_path, a.out, quality=a.quality, force=a.regen_story))
        return 0
    sc = schema.load(a.scene)
    meshes = None
    story = None
    story_file = input_path.with_suffix(".story.json")
    if story_file.is_file() and not a.regen_story:
        # storyboard written by the same Kimi call as the 3D scene: no second call
        raw_story = json.loads(story_file.read_text(encoding="utf-8"))
        if raw_story.get("chapters"):
            story = story3b1b._clean_story(raw_story, sc.to_dict())

    if not sc.parts:
        print("scene has no parts", file=sys.stderr)
        return 2
    print(render(sc, a.out, a.quality, meshes=meshes, story=story))
    return 0


if __name__ == "__main__":
    sys.exit(main())
