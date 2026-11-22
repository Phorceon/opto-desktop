"""Compile an OptoScene or Forge scene into a 3Blue1Brown-style Manim video.

    python -m opto.video out/scenes/jet_engine.ndjson out/videos/jet_engine.mp4 --quality m
    python -m opto.video out/forge/jet_engine out/videos/jet_engine.mp4 --quality m

The scene's beats drive the edit: build → highlight → cut (cross-section) → flow → explode → orbit,
with narration captions, sticky-note labels with leader lines, and a slow ambient orbit.
Each part becomes two GPU triangle meshes: the faces that stay, and the faces on the near side of the
cut plane that lift away during the cross-section.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np

from . import geometry, schema

# three.js/glTF y-up  ->  manim z-up  (det = +1, a proper rotation)
P = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=float)

STICKY = {"yellow": "#f7e07b", "pink": "#f4a6c0", "green": "#a3e4ad", "blue": "#a6cdf7",
          "orange": "#f7bb7d", "purple": "#cdb6f4"}
BG = "#0f1218"
INK = "#1b1f24"
FONT = None


def _font() -> str:
    global FONT
    if FONT:
        return FONT
    for name in ("Inter", "Noto Sans", "DejaVu Sans", "Liberation Sans"):
        try:
            out = subprocess.run(["fc-list", f":family={name}"], capture_output=True, text=True, timeout=5).stdout
            if out.strip():
                FONT = name
                return name
        except Exception:
            pass
    FONT = "Sans"
    return FONT


def words_time(say: str) -> float:
    return max(2.8, len(say.split()) / 2.6 + 0.8)


def triangulate(faces: list) -> np.ndarray:
    tris = []
    for f in faces:
        for k in range(1, len(f) - 1):
            tris.append((f[0], f[k], f[k + 1]))
    return np.asarray(tris, dtype=float).reshape(-1, 3, 3)


def smooth_normals(tris: np.ndarray, crease_deg: float = 42.0) -> np.ndarray:
    """Per-corner normals: average adjacent face normals unless the angle exceeds the crease."""
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
    # fall back to the face normal at sharp edges (abs: orientation of faces is not consistent)
    cos = np.abs(np.sum(nrm * own, axis=1))
    sharp = cos < math.cos(math.radians(crease_deg))
    nrm[sharp] = own[sharp]
    return nrm


def load_forge(dirpath: str | Path) -> tuple[schema.Scene, dict]:
    """Load a Forge scene and its exporter-supplied glTF Y-up triangle meshes."""
    dirpath = Path(dirpath)
    data = json.loads((dirpath / "scene.json").read_text())

    parts = []
    for source in data.get("parts", []):
        bbox_min = np.asarray(source["bbox_min"], dtype=float)
        bbox_max = np.asarray(source["bbox_max"], dtype=float)
        parts.append({
            "id": source["id"],
            "name": source.get("name", source["id"]),
            "shape": "mesh",
            "size": [],
            "pos": ((bbox_min + bbox_max) / 2.0).tolist(),
            "rot": [0, 0, 0],
            "color": source.get("color", "#ffffff"),
            "opacity": source.get("opacity", 1.0),
            "internal": bool(source.get("internal", False)),
            "info": source.get("info", ""),
        })

    meshes = {}
    with np.load(dirpath / "mesh.npz") as archive:
        for key in archive.files:
            if not key.endswith("__tris"):
                continue
            part_id = key[:-len("__tris")]
            tris = np.array(archive[key], dtype=float, copy=True).reshape(-1, 3, 3)
            normals = np.array(
                archive[f"{part_id}__nrm"], dtype=float, copy=True
            ).reshape(len(tris) * 3, 3)
            rgba = np.array(
                archive[f"{part_id}__color"], dtype=float, copy=True
            ).reshape(4)
            meshes[part_id] = (tris, normals, rgba)

    scene = schema.Scene(
        title=data.get("title", ""),
        subtitle=data.get("subtitle", ""),
        cut=data.get("cut", {"axis": "y", "keep": "neg"}),
        camera=data.get("camera") or [6, 4, 7],
        parts=parts,
        arrows=data.get("arrows", []),
        labels=data.get("labels", []),
        beats=data.get("beats", []),
    )
    return scene, meshes


def build_scene_class(scene: schema.Scene, meshes: dict | None = None, *, ambient: float = 0.07):
    from manim import (DEGREES, DOWN, LEFT, ORIGIN, RIGHT, UP, config, AnimationGroup, Arrow3D, Create, Dot3D, FadeIn,
                       FadeOut, LaggedStart, Line, MoveAlongPath, RoundedRectangle, Square, Text,
                       ThreeDScene, VGroup, Write, color_to_rgb, linear, rgb_to_color, smooth)
    from manim.mobject.opengl.opengl_surface import OpenGLSurface

    font = _font()
    cut_axis = "xyz".index(scene.cut.get("axis", "z"))
    cut_sign = 1.0 if scene.cut.get("keep", "neg") == "neg" else -1.0   # remove where sign*coord > 0

    class TriMesh(OpenGLSurface):
        """A triangle soup rendered by Manim's lit surface shader."""

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

    def to_manim(v):
        return P @ np.asarray(v, dtype=float)

    def lighten(hex_color: str, amt: float) -> str:
        rgb = color_to_rgb(hex_color)
        return rgb_to_color(rgb + (1 - rgb) * amt)

    class OptoVideo(ThreeDScene):
        def construct(self):
            self.parts: dict[str, dict] = {}
            self._cap = None
            self._cut_done = False
            self.labels_on: dict[str, VGroup] = {}
            self._build_meshes()
            self._orient_camera()
            self._title()
            beats = list(scene.beats) or [{"say": scene.subtitle or scene.title, "focus": [], "do": "build"}]
            if beats[0]["do"] != "build":
                beats.insert(0, {"say": scene.subtitle or f"This is a {scene.title}.", "focus": [], "do": "build"})
            self.add_updater(self._label_updater)
            self.begin_ambient_camera_rotation(rate=ambient)
            built = False
            for b in beats:
                dur = words_time(b["say"])
                do = b["do"]
                if do == "build" and not built:
                    self._do_build(b["say"], dur)
                    built = True
                    continue
                if not built:
                    self._do_build(None, 2.5)
                    built = True
                if do == "cut" and not self._cut_done:
                    self._do_cut(b["say"], dur, b["focus"])
                elif do == "flow" and scene.arrows:
                    self._do_flow(b["say"], dur, b["focus"])
                elif do == "explode":
                    self._do_explode(b["say"], dur)
                elif do == "orbit":
                    self._do_orbit(b["say"], dur)
                else:
                    self._do_highlight(b["say"], dur, b["focus"])
            if beats[-1]["do"] != "orbit":
                self._do_orbit(None, 3.0)
            self.play(FadeOut(self._cap), run_time=0.5)
            self.wait(0.4)

        # ---------- meshes ----------
        def _build_meshes(self):
            if meshes is not None:
                # Forge triangles are already complete world-space instances in glTF Y-up coordinates.
                source_parts = [dict(p) for p in scene.parts]
                known = {p["id"] for p in source_parts}
                for part_id in meshes:
                    if part_id in known:
                        continue
                    source_parts.append({
                        "id": part_id,
                        "name": "Structure" if part_id == "_structure" else part_id,
                        "shape": "mesh",
                        "size": [],
                        "pos": [0, 0, 0],
                        "rot": [0, 0, 0],
                        "color": "#ffffff",
                        "opacity": 1.0,
                        "internal": False,
                        "info": "",
                    })

                # Internal parts first so transparent shells blend over them.
                order = sorted(source_parts, key=lambda p: 0 if p["internal"] else 1)
                for original in order:
                    part_id = original["id"]
                    mesh_data = meshes.get(part_id)
                    if mesh_data is None:
                        continue

                    tris, normals, rgba = mesh_data
                    world = np.asarray(tris, dtype=float).reshape(-1, 3, 3)
                    corner_normals = np.asarray(normals, dtype=float).reshape(-1, 3)
                    if len(corner_normals) != len(world) * 3:
                        raise ValueError(f"Forge mesh {part_id!r} has mismatched triangles and normals")
                    if not len(world):
                        continue

                    rgba = np.asarray(rgba, dtype=float).reshape(4)
                    color = "#{:02x}{:02x}{:02x}".format(
                        *(int(round(c * 255.0)) for c in np.clip(rgba[:3], 0.0, 1.0))
                    )
                    p = dict(original)
                    p["color"] = color
                    p["opacity"] = float(np.clip(rgba[3], 0.0, 1.0))

                    centroids = world.mean(axis=1)
                    removable = (
                        np.zeros(len(world), dtype=bool)
                        if p["internal"]
                        else cut_sign * centroids[:, cut_axis] > 1e-6
                    )

                    manim_tris = world @ P.T
                    manim_normals = (corner_normals @ P.T).reshape(-1, 3, 3)
                    keep_t = manim_tris[~removable]
                    keep_n = manim_normals[~removable].reshape(-1, 3)
                    cut_t = manim_tris[removable]
                    cut_n = manim_normals[removable].reshape(-1, 3)

                    # The anchor is the top-centre of the complete, uncut part.
                    points = manim_tris.reshape(-1, 3)
                    low = points.min(axis=0)
                    high = points.max(axis=0)
                    anchor = np.array([
                        (low[0] + high[0]) / 2.0,
                        (low[1] + high[1]) / 2.0,
                        high[2],
                    ])

                    style = dict(color=p["color"], opacity=p["opacity"], gloss=0.35, shadow=0.22)
                    # In particular, all _structure triangles become at most one keep and one cut mesh.
                    keep = TriMesh(keep_t, keep_n, **style) if len(keep_t) else None
                    cut = TriMesh(cut_t, cut_n, **style) if len(cut_t) else None
                    self.parts[part_id] = {
                        "keep": keep,
                        "cut": cut,
                        "part": p,
                        "anchor": anchor,
                        "meshes": [m for m in (keep, cut) if m is not None],
                    }
                return

            # Original OptoScene path: construct and transform each procedural part instance.
            order = sorted(scene.parts, key=lambda p: 0 if p["internal"] else 1)
            for p in order:
                local = triangulate(geometry.faces_for_part(p, 1.0))
                lnorm = smooth_normals(local)
                keep_t, keep_n, cut_t, cut_n = [], [], [], []
                insts = schema.part_instances(p)
                top = -1e9
                for pos, R in insts:
                    Rm = np.asarray(R, dtype=float)
                    w = local @ Rm.T + np.asarray(pos)              # (n,3,3) world, y-up
                    nw = lnorm @ Rm.T
                    cen = w.mean(axis=1)
                    removable = np.zeros(len(w), bool) if p["internal"] else cut_sign * cen[:, cut_axis] > 1e-6
                    mw = w @ P.T
                    mn = (nw @ P.T).reshape(-1, 3, 3)
                    keep_t.append(mw[~removable]); keep_n.append(mn[~removable])
                    cut_t.append(mw[removable]); cut_n.append(mn[removable])
                    top = max(top, float(mw[..., 2].max()))
                kt, kn = np.concatenate(keep_t), np.concatenate(keep_n).reshape(-1, 3)
                ct, cn = np.concatenate(cut_t), np.concatenate(cut_n).reshape(-1, 3)
                style = dict(color=p["color"], opacity=p["opacity"], gloss=0.35, shadow=0.22)
                keep = TriMesh(kt, kn, **style) if len(kt) else None
                cut = TriMesh(ct, cn, **style) if len(ct) else None
                a0 = to_manim(insts[0][0])
                anchor = np.array([a0[0], a0[1], min(top, a0[2] + 3.0)])
                if len(insts) > 1:
                    allpos = np.array([to_manim(q) for q, _ in insts])
                    c = allpos.mean(axis=0)
                    anchor = np.array([c[0], c[1], top])
                self.parts[p["id"]] = {"keep": keep, "cut": cut, "part": p, "anchor": anchor,
                                       "meshes": [m for m in (keep, cut) if m is not None]}

        def _orient_camera(self):
            cam = to_manim(scene.camera)
            r = np.linalg.norm(cam) or 1.0
            phi = math.degrees(math.acos(max(-1, min(1, cam[2] / r))))
            theta = math.degrees(math.atan2(cam[1], cam[0]))
            phi = min(max(phi, 55), 75)
            self.set_camera_orientation(phi=phi * DEGREES, theta=theta * DEGREES, zoom=0.86)

        # ---------- 2D overlays ----------
        def _fixed(self, *mobs):
            self.add_fixed_in_frame_mobjects(*mobs)
            self.remove(*mobs)

        def _title(self):
            t = Text(scene.title, font=font, font_size=58, weight="BOLD", color="#f2f2f2")
            s = Text(scene.subtitle or " ", font=font, font_size=28, color="#9fb3c8")
            if s.width > 12.5:
                s.scale_to_fit_width(12.5)
            s.next_to(t, DOWN, buff=0.3)
            VGroup(t, s).move_to(ORIGIN)
            self._fixed(t, s)
            self.play(Write(t), run_time=1.2)
            self.play(FadeIn(s, shift=UP * 0.2), run_time=0.7)
            self.wait(1.0)
            small = Text(scene.title, font=font, font_size=30, weight="BOLD", color="#f2f2f2")
            small.to_corner(UP + LEFT, buff=0.4)
            self._fixed(small)
            self.play(FadeOut(s), FadeOut(t), FadeIn(small), run_time=0.7)

        def _caption(self, say: str):
            lines = textwrap.wrap(say, 60)[:3]
            txt = VGroup(*[Text(l, font=font, font_size=26, color="#eef2f6") for l in lines]).arrange(DOWN, buff=0.14)
            bg = RoundedRectangle(corner_radius=0.15, width=txt.width + 0.7, height=txt.height + 0.4,
                                  fill_color="#05070a", fill_opacity=0.72, stroke_width=0)
            g = VGroup(bg, txt)
            txt.move_to(bg)
            g.to_edge(DOWN, buff=0.3)
            self._fixed(g)
            return g

        def _show_caption(self, say):
            if say is None:
                return
            cap = self._caption(say)
            if self._cap is not None:
                self.play(FadeOut(self._cap), FadeIn(cap), run_time=0.45)
            else:
                self.play(FadeIn(cap), run_time=0.45)
            self._cap = cap

        def project(self, p) -> np.ndarray:
            """World point -> fixed-in-frame coordinates (mirrors manim's OpenGL vertex shader)."""
            cam = self.camera
            R = np.asarray(cam.inverse_rotation_matrix)
            q = R @ (np.asarray(p, dtype=float) - cam.get_center())
            f = cam.get_focal_distance()
            psf = max(0.05, f / max(1e-6, f - q[2]))
            w, h = cam.get_shape()
            return np.array([q[0] * psf * config.frame_width / w, q[1] * psf * config.frame_height / h, 0.0])

        def _label(self, pid: str):
            from manim import Dot
            lab = next((l for l in scene.labels if l["part"] == pid), None)
            info = self.parts[pid]
            text = lab["text"] if lab else info["part"]["name"]
            color = STICKY.get(lab["color"] if lab else "yellow", STICKY["yellow"])
            t = Text(text, font=font, font_size=22, color=INK, weight="BOLD")
            bg = RoundedRectangle(corner_radius=0.05, width=t.width + 0.3, height=t.height + 0.22,
                                  fill_color=color, fill_opacity=0.97, stroke_color=INK, stroke_width=1.5)
            t.move_to(bg)
            chip = VGroup(bg, t)
            line = Line(ORIGIN, RIGHT, color="#f2f2f2", stroke_width=2.2)
            dot = Dot(ORIGIN, radius=0.05, color="#ffffff")
            g = VGroup(line, dot, chip)
            g.anchor3d = info["anchor"]
            self._fixed(g)
            self._place_labels_now([g])
            return g

        def _place_labels_now(self, extra=()):
            """Lay out chips radially around the projected model centre, avoiding overlaps."""
            groups = list(self.labels_on.values()) + [g for g in extra if g not in self.labels_on.values()]
            if not groups:
                return
            centre = self.project(ORIGIN)
            entries = []
            for g in groups:
                a = self.project(g.anchor3d)
                d = a - centre
                n = np.linalg.norm(d)
                d = d / n if n > 1e-3 else np.array([0.0, 1.0, 0.0])
                entries.append((math.atan2(d[1], d[0]), g, a, d))
            entries.sort(key=lambda e: e[0])
            placed = []
            fw, fh = config.frame_width / 2, config.frame_height / 2
            for _, g, a, d in entries:
                line, dot, chip = g
                w, h = chip.width, chip.height
                best = None
                for dist in (1.0, 1.4, 1.8, 2.3):
                    for turn in (0, 28, -28, 56, -56):
                        r = math.radians(turn)
                        dd = np.array([d[0] * math.cos(r) - d[1] * math.sin(r), d[0] * math.sin(r) + d[1] * math.cos(r), 0])
                        c = a + dd * dist
                        c[0] = float(np.clip(c[0], -fw + w / 2 + 0.2, fw - w / 2 - 0.2))
                        c[1] = float(np.clip(c[1], -fh + 1.5 + h / 2, fh - h / 2 - 0.75))
                        box = (c[0] - w / 2 - 0.1, c[0] + w / 2 + 0.1, c[1] - h / 2 - 0.08, c[1] + h / 2 + 0.08)
                        if not any(box[0] < b[1] and box[1] > b[0] and box[2] < b[3] and box[3] > b[2] for b in placed):
                            best = (c, box)
                            break
                    if best:
                        break
                if best is None:
                    best = (c, box)
                c, box = best
                placed.append(box)
                chip.move_to(c)
                end = np.array([np.clip(a[0], box[0] + 0.1, box[1] - 0.1), np.clip(a[1], box[2] + 0.08, box[3] - 0.08), 0])
                if np.linalg.norm(end - a) < 1e-3:
                    end = a + np.array([0.01, 0, 0])
                line.put_start_and_end_on(a, end)
                dot.move_to(a)

        def _label_updater(self, dt):
            self._place_labels_now()

        # ---------- beats ----------
        def _do_build(self, say, dur):
            self._show_caption(say)
            order = [v for v in self.parts.values()]
            anims = [FadeIn(m, scale=0.9) for v in order for m in v["meshes"]]
            self.play(LaggedStart(*anims, lag_ratio=min(0.25, 3.0 / max(1, len(anims)))),
                      run_time=max(2.2, dur - 0.5))

        def _style_anims(self, focus: list[str], dim: float):
            anims = []
            for pid, v in self.parts.items():
                p = v["part"]
                hit = pid != "_structure" and pid in focus
                op = p["opacity"] if (not focus or hit) else min(dim, p["opacity"])
                col = lighten(p["color"], 0.28) if hit else p["color"]
                for m in v["meshes"]:
                    if m is v["cut"] and self._cut_done:
                        continue
                    anims.append(m.animate.set_color(col).set_opacity(op))
            return anims

        def _swap_labels(self, focus: list[str]):
            focus = [f for f in focus if f in self.parts and f != "_structure"]
            old = [self.labels_on.pop(k) for k in list(self.labels_on) if k not in focus]
            new_ids = [f for f in focus if f not in self.labels_on][:4]
            new = []
            for f in new_ids:
                lab = self._label(f)
                self.labels_on[f] = lab
                new.append(lab)
            return old, new

        def _do_highlight(self, say, dur, focus):
            focus = [f for f in focus if f in self.parts and f != "_structure"]
            self._show_caption(say)
            old, new = self._swap_labels(focus)
            self.play(*self._style_anims(focus, 0.22), *[FadeOut(o) for o in old], run_time=0.8)
            if new:
                self.play(LaggedStart(*[FadeIn(l) for l in new], lag_ratio=0.3), run_time=0.9)
            self.wait(max(0.6, dur - 2.3))

        def _do_cut(self, say, dur, focus):
            focus = [f for f in focus if f in self.parts and f != "_structure"]
            self._show_caption(say)
            normal3 = np.zeros(3)
            normal3[cut_axis] = 1.0
            n_m = to_manim(normal3)
            plane = Square(side_length=10, fill_color="#5ec8ff", fill_opacity=0.18,
                           stroke_color="#8fdcff", stroke_width=3)
            z = np.array([0, 0, 1.0])
            if abs(np.dot(z, n_m)) < 0.999:
                plane.rotate(math.acos(np.clip(np.dot(z, n_m), -1, 1)), axis=np.cross(z, n_m), about_point=ORIGIN)
            plane.move_to(n_m * 5.0 * cut_sign)
            self.play(FadeIn(plane), run_time=0.4)
            self.play(plane.animate.move_to(ORIGIN), run_time=1.3, rate_func=smooth)
            cuts = [v["cut"] for v in self.parts.values() if v["cut"] is not None]
            lift = n_m * 3.5 * cut_sign
            if cuts:
                self.play(*[c.animate.shift(lift).set_opacity(0) for c in cuts],
                          plane.animate.set_fill(opacity=0.05).set_stroke(opacity=0.3), run_time=1.5)
                self.remove(*cuts)
            self._cut_done = True
            old, new = self._swap_labels(focus)
            self.play(FadeOut(plane), *self._style_anims(focus, 0.35), *[FadeOut(o) for o in old], run_time=0.7)
            if new:
                self.play(LaggedStart(*[FadeIn(l) for l in new], lag_ratio=0.3), run_time=0.8)
            self.wait(max(0.5, dur - 4.7))

        def _do_flow(self, say, dur, focus):
            self._show_caption(say)
            arrows, lines = [], []
            for a in scene.arrows[:6]:
                s, e = to_manim(a["from"]), to_manim(a["to"])
                arrows.append(Arrow3D(s, e, color=a["color"], thickness=0.035, height=0.3, base_radius=0.11))
                lines.append((Line(s, e), a["color"]))
            self.play(LaggedStart(*[FadeIn(a) for a in arrows], lag_ratio=0.2), run_time=1.0)
            dots, runs = [], []
            for ln, col in lines:
                for k in range(3):
                    d = Dot3D(ln.get_start(), radius=0.07, color=col)
                    dots.append(d)
                    runs.append(MoveAlongPath(d, ln, rate_func=lambda t, k=k: ((t * 2.0) + k / 3) % 1.0))
            if runs:
                self.add(*dots)
                self.play(*runs, run_time=max(2.0, dur - 1.5), rate_func=linear)
                self.remove(*dots)
            self.flow_arrows = VGroup(*arrows)

        def _do_explode(self, say, dur):
            self._show_caption(say)
            out, back = [], []
            for v in self.parts.values():
                c = v["anchor"].copy()
                c[2] *= 0.5
                n = np.linalg.norm(c)
                if n < 1e-3:
                    continue
                sh = c / n * 1.2
                for m in v["meshes"]:
                    if m is v["cut"] and self._cut_done:
                        continue
                    out.append(m.animate.shift(sh))
                    back.append(m.animate.shift(-sh))
            labs = list(self.labels_on.values())
            self.play(*out, *[FadeOut(l) for l in labs], run_time=max(1.3, dur / 2))
            self.labels_on.clear()
            self.play(*back, run_time=max(1.0, dur / 2 - 0.3))

        def _do_orbit(self, say, dur):
            self._show_caption(say)
            show = [
                l["part"] for l in scene.labels
                if l["part"] in self.parts
                and l["part"] != "_structure"
                and l["part"] not in self.labels_on
            ][:6]
            new = []
            for pid in show:
                lab = self._label(pid)
                self.labels_on[pid] = lab
                new.append(lab)
            self.play(*self._style_anims([], 1.0), run_time=0.7)
            if new:
                self.play(LaggedStart(*[FadeIn(l) for l in new], lag_ratio=0.15), run_time=1.0)
            self.stop_ambient_camera_rotation()
            self.begin_ambient_camera_rotation(rate=0.25)
            self.wait(max(1.5, dur - 1.7))
            self.stop_ambient_camera_rotation()

    return OptoVideo


def render(scene: schema.Scene | str | Path, out_path: str | Path, quality: str = "l",
           meshes: dict | None = None) -> Path:
    from manim import config, tempconfig

    if isinstance(scene, (str, Path)):
        input_path = Path(scene)
        if input_path.is_dir() and (input_path / "scene.json").is_file():
            scene, meshes = load_forge(input_path)
        else:
            scene = schema.load(str(input_path))

    out_path = Path(out_path).resolve()
    media = out_path.parent / ".manim"
    q = {"l": "low_quality", "m": "medium_quality", "h": "high_quality"}[quality]
    cls = build_scene_class(scene, meshes=meshes)
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
    a = ap.parse_args(argv)

    input_path = Path(a.scene)
    if input_path.is_dir() and (input_path / "scene.json").is_file():
        sc, meshes = load_forge(input_path)
    else:
        sc = schema.load(a.scene)
        meshes = None

    if not sc.parts:
        print("scene has no parts", file=sys.stderr)
        return 2
    print(render(sc, a.out, a.quality, meshes=meshes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
