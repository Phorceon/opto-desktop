"""OptoScene: the tiny scene language Kimi writes and both renderers read.

The model streams NDJSON: one JSON object per line. Each line is one of:

  {"t":"meta",  "title":str, "subtitle":str, "cut":{"axis":"x|y|z","keep":"neg|pos"}, "camera":[x,y,z]}
  {"t":"part",  "id":str, "name":str, "shape":SHAPE, "size":[...], "pos":[x,y,z], "rot":[rx,ry,rz],
                "color":"#rrggbb", "opacity":0..1, "internal":bool, "info":str,
                "repeat":{"n":int, "step":[dx,dy,dz], "turn":[rx,ry,rz],
                          "around":"x|y|z", "pivot":[x,y,z]}}
                (radial repeat: copy i is additionally rotated 360*i/n degrees about the axis
                 through `pivot`, position and orientation together; world R = R_around · R_euler)
  {"t":"arrow", "from":[x,y,z], "to":[x,y,z], "color":"#rrggbb", "label":str}
  {"t":"label", "part":id, "text":str, "color":"yellow|pink|green|blue|orange|purple"}
  {"t":"beat",  "say":str, "focus":[id,...], "do":"build|highlight|cut|explode|flow|orbit"}

Coordinates: y is up (three.js convention), the whole object fits roughly inside [-4, 4]^3.
Rotations are Euler XYZ in degrees. Sizes per shape (all >0):

  box      [w, h, d]
  wedge    [w, h, d]          triangular prism: right-angle triangle in the x/y plane, extruded along z
  cylinder [r_top, r_bottom, h]  axis = local y
  cone     [r, h]                axis = local y, tip up
  sphere   [r]                   (use "ellipsoid" for squashed)
  ellipsoid[rx, ry, rz]
  capsule  [r, length]           axis = local y
  torus    [R, r]                ring in the local x/z plane
  tube     [r_outer, r_inner, h] hollow cylinder, axis = local y
  panel    [thickness] + "points":[[x,y],...]  any flat outline (3-24 points, local x/y plane),
                                                extruded along local z, centred on z=0
  lathe    [] + "points":[[r,y],...]          profile (2-24 points, r>=0) revolved about local y
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

SHAPES = {
    "box": 3, "wedge": 3, "cylinder": 3, "cone": 2, "sphere": 1,
    "ellipsoid": 3, "capsule": 2, "torus": 2, "tube": 3, "panel": 1, "lathe": 0,
}
POINT_SHAPES = {"panel", "lathe"}
SHAPE_ALIASES = {
    "cube": "box", "cuboid": "box", "prism": "wedge", "disc": "cylinder", "disk": "cylinder",
    "pipe": "tube", "ring": "torus", "ball": "sphere", "pill": "capsule", "triangle": "wedge",
    "plate": "panel", "fin": "panel", "polygon": "panel", "extrude": "panel", "revolve": "lathe",
    "profile": "lathe",
}
LABEL_COLORS = {"yellow", "pink", "green", "blue", "orange", "purple"}
BEAT_ACTIONS = {"build", "highlight", "cut", "explode", "flow", "orbit"}
MAX_PARTS = 160          # after expanding `repeat`
MAX_REPEAT = 48
BOUND = 4.0              # target half-extent after fitting

_HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")
_ID_OK = re.compile(r"[^a-z0-9_]+")


def _num(v: Any, default: float) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _vec(v: Any, n: int = 3, default: float = 0.0) -> list[float]:
    if isinstance(v, (int, float)):
        return [float(v)] * n
    if not isinstance(v, (list, tuple)):
        return [default] * n
    out = [_num(x, default) for x in list(v)[:n]]
    return out + [default] * (n - len(out))


def _color(v: Any, default: str = "#9aa3ad") -> str:
    if isinstance(v, str) and _HEX.match(v.strip()):
        s = v.strip()
        return (s if s.startswith("#") else "#" + s).lower()
    return default


def _slug(v: Any, fallback: str) -> str:
    s = _ID_OK.sub("_", str(v or "").lower()).strip("_")
    return s[:40] or fallback


@dataclass
class Scene:
    title: str = "Untitled"
    subtitle: str = ""
    cut: dict = field(default_factory=lambda: {"axis": "z", "keep": "neg"})
    camera: list = field(default_factory=lambda: [6.0, 4.0, 7.0])
    parts: list = field(default_factory=list)
    arrows: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    beats: list = field(default_factory=list)
    errors: list = field(default_factory=list)  # lines we could not use, for evals

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ("title", "subtitle", "cut", "camera", "parts", "arrows", "labels", "beats")}

    def to_ndjson(self) -> str:
        lines = [{"t": "meta", "title": self.title, "subtitle": self.subtitle,
                  "cut": self.cut, "camera": self.camera}]
        lines += [{"t": "part", **p} for p in self.parts]
        lines += [{"t": "arrow", **a} for a in self.arrows]
        lines += [{"t": "label", **l} for l in self.labels]
        lines += [{"t": "beat", **b} for b in self.beats]
        return "\n".join(json.dumps(x, separators=(",", ":")) for x in lines) + "\n"


def extract_json_objects(text: str) -> list[dict]:
    """Pull every top-level {...} object out of model text (tolerates fences, prose, arrays)."""
    objs, depth, start, in_str, esc = [], 0, None, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    o = json.loads(text[start:i + 1])
                    if isinstance(o, dict):
                        objs.append(o)
                except json.JSONDecodeError:
                    pass
                start = None
    return objs


class SceneBuilder:
    """Incremental normaliser: feed objects as they stream, read normalised items back."""

    def __init__(self) -> None:
        self.scene = Scene()
        self._ids: set[str] = set()
        self._n_parts = 0

    # Each add_* returns the list of normalised items to emit (possibly empty).
    def add(self, obj: dict) -> list[dict]:
        if not isinstance(obj, dict):
            return []
        kind = str(obj.get("t") or obj.get("type") or "").lower()
        if not kind:  # guess from keys
            kind = "part" if "shape" in obj else "arrow" if "from" in obj else \
                "label" if "text" in obj and "part" in obj else "beat" if "say" in obj else \
                "meta" if "title" in obj else ""
        try:
            fn = getattr(self, f"_add_{kind}", None)
            if fn is None:
                self.scene.errors.append(f"unknown line type {kind!r}")
                return []
            return fn(obj)
        except Exception as e:  # never let one bad line kill the stream
            self.scene.errors.append(f"{kind}: {e}")
            return []

    def _add_meta(self, o: dict) -> list[dict]:
        s = self.scene
        s.title = str(o.get("title") or s.title)[:80]
        s.subtitle = str(o.get("subtitle") or "")[:140]
        cut = o.get("cut") if isinstance(o.get("cut"), dict) else {}
        axis = str(cut.get("axis", "z")).lower()
        keep = str(cut.get("keep", "neg")).lower()
        s.cut = {"axis": axis if axis in ("x", "y", "z") else "z",
                 "keep": "pos" if keep.startswith("pos") else "neg"}
        if o.get("camera") is not None:
            cam = _vec(o.get("camera"), 3, 5.0)
            if math.hypot(*cam) > 1.0:
                s.camera = cam
        return [{"t": "meta", "title": s.title, "subtitle": s.subtitle, "cut": s.cut, "camera": s.camera}]

    def _add_part(self, o: dict) -> list[dict]:
        shape = str(o.get("shape", "box")).lower().strip()
        shape = SHAPE_ALIASES.get(shape, shape)
        if shape not in SHAPES:
            self.scene.errors.append(f"part shape {shape!r} unsupported -> box")
            shape = "box"
        n = SHAPES[shape]
        raw = o.get("size", 1.0)
        size = _vec(raw, n, 0.5)
        if shape == "cylinder" and isinstance(raw, (list, tuple)) and len(raw) == 2:
            size = [_num(raw[0], .5), _num(raw[0], .5), _num(raw[1], 1)]  # [r, h] shorthand
        if shape == "box" and isinstance(raw, (int, float)):
            size = [float(raw)] * 3
        size = [min(max(abs(x), 0.01), 20.0) for x in size]
        pts = None
        if shape in POINT_SHAPES:
            raw_pts = o.get("points") or o.get("profile") or o.get("outline")
            if isinstance(raw_pts, list):
                pts = [[round(_num(q[0], 0), 4), round(_num(q[1], 0), 4)] for q in raw_pts[:24]
                       if isinstance(q, (list, tuple)) and len(q) >= 2]
            if shape == "lathe" and pts:
                pts = [[abs(x), y] for x, y in pts]
            need = 3 if shape == "panel" else 2
            if not pts or len(pts) < need:
                self.scene.errors.append(f"{shape} without enough points -> box")
                shape, size, pts = "box", [0.5, 0.5, 0.5], None
            elif shape == "panel" and size[0] > 2.0:
                size = [0.08]
        if shape == "tube" and size[1] >= size[0]:
            size[1] = size[0] * 0.8
        base_id = _slug(o.get("id") or o.get("name"), f"part{self._n_parts}")
        pid = base_id
        k = 2
        while pid in self._ids:
            pid, k = f"{base_id}_{k}", k + 1
        part = {
            "id": pid,
            "name": str(o.get("name") or pid.replace("_", " ").title())[:48],
            "shape": shape,
            "size": [round(x, 4) for x in size],
            "pos": [round(x, 4) for x in _vec(o.get("pos", o.get("position")), 3, 0.0)],
            "rot": [round(x, 3) for x in _vec(o.get("rot", o.get("rotation")), 3, 0.0)],
            "color": _color(o.get("color")),
            "opacity": round(min(max(_num(o.get("opacity", 1), 1), 0.08), 1.0), 3),
            "internal": bool(o.get("internal", False)),
            "info": str(o.get("info") or "")[:240],
        }
        if pts:
            part["points"] = pts
        rep = o.get("repeat")
        if isinstance(rep, dict):
            cnt = int(min(max(_num(rep.get("n", rep.get("count", 1)), 1), 1), MAX_REPEAT))
            if cnt > 1:
                r = {"n": cnt,
                     "step": [round(x, 4) for x in _vec(rep.get("step", rep.get("offset")), 3, 0.0)],
                     "turn": [round(x, 3) for x in _vec(rep.get("turn", rep.get("rotate")), 3, 0.0)]}
                around = str(rep.get("around") or "").lower()
                if around in ("x", "y", "z"):
                    r["around"] = around
                    r["pivot"] = [round(x, 4) for x in _vec(rep.get("pivot"), 3, 0.0)] \
                        if rep.get("pivot") is not None else list(part["pos"])
                part["repeat"] = r
        count = part.get("repeat", {}).get("n", 1)
        if self._n_parts + count > MAX_PARTS:
            self.scene.errors.append("part budget exceeded; dropped " + pid)
            return []
        self._n_parts += count
        self._ids.add(pid)
        self.scene.parts.append(part)
        return [{"t": "part", **part}]

    def _add_arrow(self, o: dict) -> list[dict]:
        a = {"from": [round(x, 4) for x in _vec(o.get("from"))],
             "to": [round(x, 4) for x in _vec(o.get("to"))],
             "color": _color(o.get("color"), "#4fc3f7"),
             "label": str(o.get("label") or "")[:40]}
        if math.dist(a["from"], a["to"]) < 1e-3:
            raise ValueError("zero-length arrow")
        self.scene.arrows.append(a)
        return [{"t": "arrow", **a}]

    def _add_label(self, o: dict) -> list[dict]:
        pid = _slug(o.get("part"), "")
        if pid not in self._ids:
            # labels may arrive before their part in sloppy output; resolve later in finish()
            self.scene.labels.append({"part": pid, "text": str(o.get("text") or "")[:32],
                                      "color": self._label_color(o.get("color")), "_pending": True})
            return []
        lab = {"part": pid, "text": str(o.get("text") or "")[:32] or pid,
               "color": self._label_color(o.get("color"))}
        self.scene.labels.append(lab)
        return [{"t": "label", **lab}]

    def _label_color(self, c: Any) -> str:
        c = str(c or "").lower()
        if c in LABEL_COLORS:
            return c
        palette = ["yellow", "pink", "green", "blue", "orange", "purple"]
        return palette[len(self.scene.labels) % len(palette)]

    def _add_beat(self, o: dict) -> list[dict]:
        do = str(o.get("do") or o.get("action") or "highlight").lower()
        b = {"say": str(o.get("say") or "")[:280],
             "focus": [_slug(x, "") for x in (o.get("focus") or []) if x][:8],
             "do": do if do in BEAT_ACTIONS else "highlight"}
        if not b["say"]:
            raise ValueError("beat without narration")
        self.scene.beats.append(b)
        return [{"t": "beat", **b}]

    def finish(self) -> Scene:
        """Resolve late references, drop dangling ones, fit the object into view."""
        s = self.scene
        labels = []
        for lab in s.labels:
            if lab.pop("_pending", False) and lab["part"] not in self._ids:
                s.errors.append(f"label for unknown part {lab['part']!r}")
                continue
            labels.append(lab)
        # one label per part
        seen = set()
        s.labels = [l for l in labels if not (l["part"] in seen or seen.add(l["part"]))]
        for b in s.beats:
            bad = [f for f in b["focus"] if f not in self._ids]
            if bad:
                s.errors.append(f"beat focus unknown {bad}")
            b["focus"] = [f for f in b["focus"] if f in self._ids]
        fit_scene(s)
        return s


Mat = list  # 3x3 row-major nested list


def _mm(a: Mat, b: Mat) -> Mat:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _mv(a: Mat, v: list[float]) -> list[float]:
    return [sum(a[i][k] * v[k] for k in range(3)) for i in range(3)]


def axis_rot(axis: str, deg: float) -> Mat:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    if axis == "x":
        return [[1, 0, 0], [0, c, -s], [0, s, c]]
    if axis == "y":
        return [[c, 0, s], [0, 1, 0], [-s, 0, c]]
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def euler_xyz(rot: list[float]) -> Mat:
    """three.js Euler order 'XYZ' (intrinsic): R = Rx · Ry · Rz."""
    return _mm(_mm(axis_rot("x", rot[0]), axis_rot("y", rot[1])), axis_rot("z", rot[2]))


def part_instances(p: dict) -> list[tuple[list[float], Mat]]:
    """Expand `repeat` into (world position, 3x3 world rotation) per copy (y-up frame)."""
    rep = p.get("repeat") or {"n": 1, "step": [0, 0, 0], "turn": [0, 0, 0]}
    out = []
    for i in range(rep["n"]):
        pos = [p["pos"][k] + rep["step"][k] * i for k in range(3)]
        rot = euler_xyz([p["rot"][k] + rep.get("turn", [0, 0, 0])[k] * i for k in range(3)])
        if rep.get("around"):
            ang = 360.0 * i / rep["n"]
            ra = axis_rot(rep["around"], ang)
            pv = rep["pivot"]
            pos = [a + b for a, b in zip(_mv(ra, [pos[k] - pv[k] for k in range(3)]), pv)]
            rot = _mm(ra, rot)
        out.append((pos, rot))
    return out


def part_radius(p: dict) -> float:
    s = p["size"]
    sh = p["shape"]
    if sh in ("box", "wedge", "ellipsoid"):
        return 0.5 * math.sqrt(sum(x * x for x in s)) if sh != "ellipsoid" else max(s)
    if sh in ("cylinder", "tube"):
        return math.hypot(max(s[0], s[1] if sh == "cylinder" else s[0]), s[2] / 2)
    if sh == "cone":
        return math.hypot(s[0], s[1] / 2)
    if sh == "sphere":
        return s[0]
    if sh == "capsule":
        return s[0] + s[1] / 2
    if sh == "torus":
        return s[0] + s[1]
    if sh in POINT_SHAPES and p.get("points"):
        return max(math.hypot(x, y) for x, y in p["points"]) + (s[0] if sh == "panel" else 0)
    return 1.0


def bounds(scene: Scene) -> tuple[list[float], list[float]]:
    lo, hi = [1e9] * 3, [-1e9] * 3
    for p in scene.parts:
        r = part_radius(p)
        for pos, _ in part_instances(p):
            for k in range(3):
                lo[k] = min(lo[k], pos[k] - r * 0.6)
                hi[k] = max(hi[k], pos[k] + r * 0.6)
    if not scene.parts:
        return [-1, -1, -1], [1, 1, 1]
    return lo, hi


def fit_scene(scene: Scene) -> None:
    """Recentre on the origin and scale so the largest half-extent is BOUND."""
    if not scene.parts:
        return
    lo, hi = bounds(scene)
    center = [(lo[k] + hi[k]) / 2 for k in range(3)]
    half = max((hi[k] - lo[k]) / 2 for k in range(3)) or 1.0
    f = BOUND / half
    if 0.8 < f < 1.25 and max(abs(c) for c in center) < 0.3:
        return

    def tx(v):
        return [round((v[k] - center[k]) * f, 4) for k in range(3)]

    for p in scene.parts:
        p["pos"] = tx(p["pos"])
        p["size"] = [round(x * f, 4) for x in p["size"]]
        if p.get("points"):
            p["points"] = [[round(x * f, 4), round(y * f, 4)] for x, y in p["points"]]
        if "repeat" in p:
            p["repeat"]["step"] = [round(x * f, 4) for x in p["repeat"]["step"]]
            if "pivot" in p["repeat"]:
                p["repeat"]["pivot"] = tx(p["repeat"]["pivot"])
    for a in scene.arrows:
        a["from"], a["to"] = tx(a["from"]), tx(a["to"])
    scene.camera = [round(c * 1.0, 3) for c in scene.camera]


def parse_text(text: str) -> Scene:
    b = SceneBuilder()
    for o in extract_json_objects(text):
        b.add(o)
    return b.finish()


def load(path: str) -> Scene:
    with open(path) as f:
        return parse_text(f.read())
