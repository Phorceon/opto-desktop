"""Opto Forge runtime: runs ONE untrusted Kimi bpy script inside the bwrap sandbox (see opto/forge.py).

Two modes (both run under .venv-blender, Python 3.13 + the `bpy` pip module):

    python forge_runtime.py SCRIPT.py OUTDIR     one-shot: run, write outputs, exit 0 / 3
    python forge_runtime.py --worker             warm worker: bpy imported once; one JSON request per
                                                  line on stdin {"script", "outdir"}, one JSON reply per
                                                  line on the ORIGINAL stdout {"ok", "error"?, "timings"}.
                                                  Everything else that prints (Blender, the script) is
                                                  redirected to stderr so it can't corrupt the protocol.

Pipeline:
  reset → exec script → cap silly modifier settings → evaluate depsgraph once → bake every visible
  mesh/curve/text object to a mesh → triangle budget (DECIMATE big meshes) → numpy: world transform,
  bbox, re-centre (centre → origin, largest half-extent 4.0) → glTF axes → model.glb (own numpy GLB
  writer; bpy exporter as fallback) + mesh.npz + scene.json.
"""

import gc
import json
import math
import os
import re
import struct
import sys
import time
import traceback
from pathlib import Path

if sys.argv[1:] == ["--worker"]:
    # claim the protocol pipes BEFORE importing bpy (Blender may print to stdout while starting):
    # fd 1 → stderr for everything else, fd 0 → /dev/null so the script can't read our requests
    _PROTO_OUT = os.fdopen(os.dup(1), "w", buffering=1)
    _PROTO_IN = os.fdopen(os.dup(0), "r")
    os.dup2(2, 1)
    os.dup2(os.open(os.devnull, os.O_RDONLY), 0)

import bpy
import bmesh
import numpy as np
from mathutils import Euler, Matrix, Vector


META = {}
PARTS = []
ARROWS = []
BEATS = []
MATERIALS = {}
SLUGS = set()
_HANDLERS = {}
PALETTE = ("yellow", "pink", "green", "blue", "orange", "purple")
DO_VALUES = {"build", "highlight", "cut", "explode", "flow", "orbit"}
GEOMETRY_TYPES = {"MESH", "CURVE", "FONT", "SURFACE", "META"}
TRIANGLE_BUDGET = 120_000
DECIMATE_MIN_TRIS = 2_000
DECIMATE_MIN_RATIO = 0.15
HALF_EXTENT = 4.0
USE_BPY_EXPORTER = os.environ.get("OPTO_GLTF") == "bpy"


class ScriptProblem(Exception):
    """The script ran but its result is unusable; the message is written verbatim for Kimi."""


# ---------------------------------------------------------------- script API (contract §1)

def _rgb(value, default="#ffffff"):
    try:
        if isinstance(value, (tuple, list)) and len(value) >= 3:
            return tuple(max(0.0, min(1.0, float(v))) for v in value[:3])
        text = str(value).strip().lstrip("#")
        if len(text) == 3:
            text = "".join(c * 2 for c in text)
        if len(text) != 6:
            raise ValueError
        return tuple(int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except (TypeError, ValueError):
        text = str(default).lstrip("#")
        return tuple(int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _point(value):
    v = Vector(value)
    return [float(v[i]) for i in range(3)]


def _slug(name):
    base = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")[:40].strip("_")
    base = base or "part"
    candidate, number = base, 1
    while candidate in SLUGS or candidate == "_structure":
        number += 1
        suffix = "_%d" % number
        candidate = base[:40 - len(suffix)].rstrip("_") + suffix
    SLUGS.add(candidate)
    return candidate


def meta(title, subtitle, cut_axis="y", keep="neg"):
    META.update(title=str(title), subtitle=str(subtitle))
    axis = str(cut_axis).lower()
    META["cut_axis"] = axis if axis in ("x", "y", "z") else "y"
    META["keep"] = str(keep).lower() if str(keep).lower() in ("neg", "pos") else "neg"


def mat(name, color, metallic=0.0, roughness=0.5, alpha=1.0, emission=None):
    name = str(name)
    if name in MATERIALS:
        return MATERIALS[name]
    alpha = float(alpha)
    rgba = (*_rgb(color), alpha)
    material = bpy.data.materials.new(name)
    if getattr(material, "node_tree", None) is None and hasattr(material, "use_nodes"):
        material.use_nodes = True  # Blender < 5 only; 5.x materials always have a node tree
    material.diffuse_color = rgba
    material.metallic = float(metallic)
    material.roughness = float(roughness)
    tree = getattr(material, "node_tree", None)
    bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if tree else None
    if bsdf:
        bsdf.inputs["Base Color"].default_value = rgba
        bsdf.inputs["Metallic"].default_value = float(metallic)
        bsdf.inputs["Roughness"].default_value = float(roughness)
        bsdf.inputs["Alpha"].default_value = alpha
        if emission is not None:
            socket = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
            if socket:
                socket.default_value = (*_rgb(emission), 1.0)
            if bsdf.inputs.get("Emission Strength"):
                bsdf.inputs["Emission Strength"].default_value = 2.0
    if alpha < 1.0:
        if hasattr(material, "surface_render_method"):
            material.surface_render_method = "DITHERED"
        if hasattr(material, "blend_method"):
            material.blend_method = "BLEND"
    MATERIALS[name] = material
    return material


def part(obj_or_objs, name, info, internal=False, label=None, label_color=None):
    if isinstance(obj_or_objs, bpy.types.Object):
        objects = [obj_or_objs]
    else:
        try:
            objects = list(obj_or_objs)
        except TypeError:
            objects = [obj_or_objs]
    objects = [obj for obj in objects if isinstance(obj, bpy.types.Object)]
    pid = _slug(name)
    color = str(label_color).lower() if label_color is not None else ""
    if color not in PALETTE:
        color = PALETTE[len(PARTS) % len(PALETTE)]
    for obj in objects:
        obj["opto_part"] = pid
        obj["opto_internal"] = int(bool(internal))
    PARTS.append({"id": pid, "name": str(name), "info": str(info),
                  "internal": bool(internal), "label": None if label is None else str(label),
                  "label_color": color})
    return objects[0] if objects else None


def arrow(start, end, color="#4fc3f7", label=""):
    ARROWS.append({"from": _point(start), "to": _point(end),
                   "color": str(color), "label": str(label)})


def beat(say, focus=(), do="highlight"):
    if isinstance(focus, str):
        focus = [focus]
    try:
        focus = list(focus or ())
    except TypeError:
        focus = [focus]
    BEATS.append({"say": str(say), "focus": focus,
                  "do": str(do) if str(do) in DO_VALUES else "highlight"})


# ---------------------------------------------------------------- fast mesh primitives
# Every bpy.ops call rebuilds the depsgraph relations of the WHOLE scene, so a script that adds a few
# hundred primitives is O(n^2) (~25 ms per op at 150 objects). These drop-in replacements build the
# exact same geometry with the same bmesh ops the C operators use, plus the same object semantics
# (names, active collection, selection, active object, cursor location default, valid matrix_world).
# Anything unusual (align != WORLD, enter_editmode, edit mode, unknown kwargs) uses the real operator.

_OP_COMMON = {"location", "rotation", "scale", "align", "enter_editmode", "calc_uvs"}


def _fast_ok(kw, allowed):
    return not (set(kw) - allowed - _OP_COMMON or kw.get("enter_editmode")
                or kw.get("align", "WORLD") != "WORLD" or bpy.context.mode != "OBJECT")


def _fast_object(name, mesh, kw):
    scene, layer = bpy.context.scene, bpy.context.view_layer
    loc = Vector(kw["location"]) if "location" in kw else scene.cursor.location.copy()
    rot = Euler(kw.get("rotation", (0.0, 0.0, 0.0)))
    obj = bpy.data.objects.new(name, mesh)
    (bpy.context.collection or scene.collection).objects.link(obj)
    for other in bpy.context.selected_objects:
        other.select_set(False)
    obj.matrix_world = Matrix.LocRotScale(loc, rot, None)
    obj.location, obj.rotation_euler, obj.scale = loc, rot, (1.0, 1.0, 1.0)  # exact values, matrix_world stays consistent
    try:
        obj.select_set(True)
        layer.objects.active = obj
    except RuntimeError:
        pass
    return {"FINISHED"}


def _fast_add(name, kw, allowed, build):
    if not _fast_ok(kw, allowed):
        return None
    scale = Vector(kw.get("scale", (1.0, 1.0, 1.0)))
    bm = bmesh.new()
    calc_uvs = bool(kw.get("calc_uvs", True))
    if calc_uvs:
        bm.loops.layers.uv.new("UVMap")
    build(bm, Matrix.Diagonal(scale).to_4x4(), calc_uvs)
    for seq in (bm.verts, bm.edges, bm.faces):  # the operators leave the new geometry selected
        for elem in seq:
            elem.select = True
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return _fast_object(name, mesh, kw)


def _fill(kw):
    fill = kw.get("end_fill_type", "NGON")
    return fill != "NOTHING", fill == "TRIFAN"


class _FastMeshOps:
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __dir__(self):
        return dir(self._real)

    def primitive_cube_add(self, *args, **kw):
        size = float(kw.get("size", 2.0))
        res = None if args else _fast_add("Cube", kw, {"size"}, lambda bm, m, uv: bmesh.ops.create_cube(
            bm, size=size, matrix=m, calc_uvs=uv))
        return res or self._real.primitive_cube_add(*args, **kw)

    def primitive_cylinder_add(self, *args, **kw):
        cap, tri = _fill(kw)
        r, d, n = float(kw.get("radius", 1.0)), float(kw.get("depth", 2.0)), int(kw.get("vertices", 32))
        res = None if args or n < 3 else _fast_add(
            "Cylinder", kw, {"vertices", "radius", "depth", "end_fill_type"},
            lambda bm, m, uv: bmesh.ops.create_cone(bm, cap_ends=cap, cap_tris=tri, segments=n, radius1=r,
                                                    radius2=r, depth=d, matrix=m, calc_uvs=uv))
        return res or self._real.primitive_cylinder_add(*args, **kw)

    def primitive_cone_add(self, *args, **kw):
        cap, tri = _fill(kw)
        r1, r2 = float(kw.get("radius1", 1.0)), float(kw.get("radius2", 0.0))
        d, n = float(kw.get("depth", 2.0)), int(kw.get("vertices", 32))
        res = None if args or n < 3 else _fast_add(
            "Cone", kw, {"vertices", "radius1", "radius2", "depth", "end_fill_type"},
            lambda bm, m, uv: bmesh.ops.create_cone(bm, cap_ends=cap, cap_tris=tri, segments=n, radius1=r1,
                                                    radius2=r2, depth=d, matrix=m, calc_uvs=uv))
        return res or self._real.primitive_cone_add(*args, **kw)

    def primitive_uv_sphere_add(self, *args, **kw):
        u, v = int(kw.get("segments", 32)), int(kw.get("ring_count", 16))
        r = float(kw.get("radius", 1.0))
        res = None if args or u < 3 or v < 3 else _fast_add(
            "Sphere", kw, {"segments", "ring_count", "radius"},
            lambda bm, m, uv: bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=r,
                                                        matrix=m, calc_uvs=uv))
        return res or self._real.primitive_uv_sphere_add(*args, **kw)

    def primitive_ico_sphere_add(self, *args, **kw):
        sub, r = int(kw.get("subdivisions", 2)), float(kw.get("radius", 1.0))
        res = None if args or not 1 <= sub <= 10 else _fast_add(
            "Icosphere", kw, {"subdivisions", "radius"},
            lambda bm, m, uv: bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=r, matrix=m,
                                                         calc_uvs=uv))
        return res or self._real.primitive_ico_sphere_add(*args, **kw)

    def primitive_torus_add(self, *args, **kw):
        allowed = {"major_segments", "minor_segments", "mode", "major_radius", "minor_radius",
                   "abso_major_rad", "abso_minor_rad", "generate_uvs"}
        if args or "scale" in kw or "calc_uvs" in kw or not _fast_ok(kw, allowed):
            return self._real.primitive_torus_add(*args, **kw)
        from bl_operators import add_mesh_torus as torus  # same geometry code the operator runs
        major, minor = float(kw.get("major_radius", 1.0)), float(kw.get("minor_radius", 0.25))
        if kw.get("mode") == "EXT_INT":
            helper = (float(kw.get("abso_major_rad", 1.25)) - float(kw.get("abso_minor_rad", 0.75))) * 0.5
            major, minor = float(kw.get("abso_minor_rad", 0.75)) + helper, helper
        nmaj, nmin = int(kw.get("major_segments", 48)), int(kw.get("minor_segments", 12))
        if nmaj < 3 or nmin < 3:
            return self._real.primitive_torus_add(*args, **kw)
        verts, faces = torus.add_torus(major, minor, nmaj, nmin)
        mesh = bpy.data.meshes.new("Torus")
        mesh.vertices.add(len(verts) // 3)
        mesh.loops.add(len(faces))
        mesh.polygons.add(len(faces) // 4)
        mesh.vertices.foreach_set("co", verts)
        mesh.polygons.foreach_set("loop_start", range(0, len(faces), 4))
        mesh.loops.foreach_set("vertex_index", faces)
        mesh.shade_flat()
        if kw.get("generate_uvs", True):
            torus.add_uvs(mesh, nmin, nmaj)
        mesh.update()
        return _fast_object("Torus", mesh, kw)


def _install_fast_ops():
    if os.environ.get("OPTO_REAL_OPS"):
        return
    real = getattr(bpy.ops, "mesh")
    if not isinstance(real, _FastMeshOps):
        bpy.ops.mesh = _FastMeshOps(real)


# ---------------------------------------------------------------- reset between jobs

def _reset():
    META.clear()
    META.update(title="", subtitle="", cut_axis="y", keep="neg")
    PARTS.clear()
    ARROWS.clear()
    BEATS.clear()
    MATERIALS.clear()
    SLUGS.clear()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # handlers the script registered (even persistent ones) must not fire in later jobs: restore the
    # lists to what Blender itself had installed before the first job
    for name in dir(bpy.app.handlers):
        handlers = getattr(bpy.app.handlers, name)
        if isinstance(handlers, list):
            base = _HANDLERS.setdefault(name, list(handlers))
            handlers[:] = [h for h in handlers if h in base]
    for _ in range(3):  # read_factory_settings gives a fresh Main; purge anything that survived anyway
        try:
            if not bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True):
                break
        except (AttributeError, RuntimeError, TypeError):
            break
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    gc.collect()


def _leftovers():
    return {"objects": len(bpy.data.objects), "meshes": len(bpy.data.meshes),
            "materials": len(bpy.data.materials), "curves": len(bpy.data.curves),
            "scenes": len(bpy.data.scenes), "parts": len(PARTS)}


# ---------------------------------------------------------------- geometry

def _cap_modifiers(objects):
    """Rein in settings that explode triangle counts / runtime BEFORE anything is evaluated: lowering a
    SUBSURF level is ~free, decimating its output afterwards costs seconds."""
    subsurfs = []  # (modifier, its object's running face estimate [list so it can be updated], _)
    estimates = []
    for obj in objects:
        try:
            if obj.type in ("CURVE", "FONT"):
                curve = obj.data
                curve.resolution_u = min(curve.resolution_u, 24)
                curve.render_resolution_u = min(curve.render_resolution_u, 24)
                curve.bevel_resolution = min(curve.bevel_resolution, 8)
            faces = float(len(obj.data.polygons)) if obj.type == "MESH" else 256.0
            est = [faces]
            for mod in obj.modifiers:
                if mod.type in ("SUBSURF", "MULTIRES"):
                    level = min(int(getattr(mod, "levels", 0)), 4)
                    if mod.type == "SUBSURF":
                        if mod.levels != level:
                            mod.levels = level
                        # limit-surface evaluation goes through OpenSubdiv patch eval on the CPU:
                        # ~1.5 s per 2k-quad sphere vs ~40 ms without, visually indistinguishable here
                        mod.use_limit_surface = False
                    elif mod.type == "MULTIRES" and mod.levels != level:
                        mod.levels = level
                    subsurfs.append((mod, est, est[0]))
                    est[0] *= 4 ** max(level, 0)
                elif mod.type == "SCREW":
                    mod.steps = min(mod.steps, 128)
                    mod.render_steps = min(mod.render_steps, 128)
                    mod.iterations = min(mod.iterations, 64)
                    est[0] *= max(1, mod.steps) * max(1, mod.iterations) if faces == 0 else 1
                elif mod.type == "ARRAY":
                    if mod.fit_type == "FIXED_COUNT":
                        mod.count = min(mod.count, 400)
                        est[0] *= max(1, mod.count)
                elif mod.type == "MIRROR":
                    est[0] *= 2 ** max(1, sum(bool(x) for x in mod.use_axis))
                elif mod.type == "REMESH" and mod.mode == "VOXEL":
                    mod.voxel_size = max(mod.voxel_size, 0.01)
            estimates.append(est)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    # global: lower the biggest subdivision levels until the estimate fits ~1.2x the triangle budget
    total = lambda: sum(e[0] for e in estimates) * 2  # quads → triangles  # noqa: E731
    while subsurfs and total() > TRIANGLE_BUDGET * 1.2:
        candidates = [(e[0], i) for i, (m, e, _) in enumerate(subsurfs) if m.levels > 1]
        if not candidates:
            break
        _, i = max(candidates)
        mod, est, _ = subsurfs[i]
        mod.levels -= 1
        est[0] /= 4


def _export_objects():
    """Visible geometry objects in the view layer. Hidden helpers (boolean cutters, wireframe guides)
    are skipped unless the script registered them with part()."""
    scene, layer = bpy.context.scene, bpy.context.view_layer
    # registered parts that the script never linked into the scene still belong in the model
    linked = set(scene.objects)
    for obj in bpy.data.objects:
        if "opto_part" in obj and obj not in linked and obj.type in GEOMETRY_TYPES:
            scene.collection.objects.link(obj)
    layer.update()  # view_layer.objects is lazily synced: objects linked via bpy.data may be missing
    layer_objects = list(layer.objects)
    helpers = set()
    for obj in layer_objects:
        for mod in getattr(obj, "modifiers", ()):
            if mod.type == "BOOLEAN" and getattr(mod, "operand_type", "OBJECT") == "OBJECT" and mod.object:
                helpers.add(mod.object.name)
    chosen = []
    for obj in layer_objects:
        if obj.type not in GEOMETRY_TYPES:
            continue
        registered = "opto_part" in obj
        if not registered:
            hidden = obj.hide_viewport or obj.hide_render or obj.hide_get() \
                or obj.display_type in ("WIRE", "BOUNDS") or obj.name in helpers
            if hidden:
                continue
        chosen.append(obj)
    for obj in chosen:  # make sure registered-but-hidden objects get evaluated
        if obj.hide_viewport:
            obj.hide_viewport = False
    return chosen


def _part_of(obj):
    node = obj
    while node is not None:
        if "opto_part" in node:
            return str(node["opto_part"]), bool(node.get("opto_internal", 0))
        node = node.parent
    return "_structure", False


def _bake(objects, depsgraph):
    """Evaluate each object once (modifiers, curves → mesh). Returns records with a baked bpy mesh."""
    records = []
    for obj in objects:
        try:
            evaluated = obj.evaluated_get(depsgraph)
            mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=False,
                                                   depsgraph=depsgraph)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            continue
        if mesh is None:
            continue
        if not mesh.polygons:
            bpy.data.meshes.remove(mesh)
            continue
        if not mesh.materials:
            for slot in obj.material_slots:
                mesh.materials.append(slot.material)
        mesh.calc_loop_triangles()
        pid, internal = _part_of(obj)
        records.append({"name": obj.name, "pid": pid, "internal": internal, "mesh": mesh,
                        "world": np.array(evaluated.matrix_world, dtype=np.float64),
                        "tris": len(mesh.loop_triangles)})
    return records


def _decimate(records, timings):
    total = sum(r["tris"] for r in records)
    timings["tris_raw"] = total
    if total <= TRIANGLE_BUDGET:
        return
    big = [r for r in records if r["tris"] > DECIMATE_MIN_TRIS]
    small = total - sum(r["tris"] for r in big)
    if not big:
        return
    ratio = max(DECIMATE_MIN_RATIO, min(1.0, (TRIANGLE_BUDGET - small) / max(1, total - small)))
    scene = bpy.context.scene
    temps = []
    for r in big:
        obj = bpy.data.objects.new("_opto_decimate", r["mesh"])
        scene.collection.objects.link(obj)
        mod = obj.modifiers.new("opto_budget", "DECIMATE")
        mod.decimate_type = "COLLAPSE"
        mod.ratio = ratio
        temps.append((r, obj))
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for r, obj in temps:
        try:
            mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph),
                                                   preserve_all_data_layers=False, depsgraph=depsgraph)
        except (RuntimeError, TypeError):
            mesh = None
        old = r["mesh"]
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and mesh.polygons:
            if not mesh.materials:
                for m in old.materials:
                    mesh.materials.append(m)
            mesh.calc_loop_triangles()
            r["mesh"], r["tris"] = mesh, len(mesh.loop_triangles)
            bpy.data.meshes.remove(old)
        elif mesh is not None:
            bpy.data.meshes.remove(mesh)
    timings["decimate_ratio"] = round(ratio, 3)


def _arrays(records):
    """numpy arrays per record, world space (Blender axes): verts (V,3), corner vertex idx (T*3,),
    corner normals (T*3,3), material index per triangle (T,)."""
    for r in records:
        mesh, world = r["mesh"], r["world"]
        nv, nt, nl = len(mesh.vertices), len(mesh.loop_triangles), len(mesh.loops)
        co = np.empty(nv * 3, np.float32)
        mesh.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3).astype(np.float64) @ world[:3, :3].T + world[:3, 3]
        tv = np.empty(nt * 3, np.int32)
        tl = np.empty(nt * 3, np.int32)
        mi = np.empty(nt, np.int32)
        mesh.loop_triangles.foreach_get("vertices", tv)
        mesh.loop_triangles.foreach_get("loops", tl)
        mesh.loop_triangles.foreach_get("material_index", mi)
        cn = np.empty(nl * 3, np.float32)
        try:
            mesh.corner_normals.foreach_get("vector", cn)
        except (AttributeError, RuntimeError, TypeError):
            mesh.loops.foreach_get("normal", cn)
        cn = cn.reshape(-1, 3)[tl].astype(np.float64)
        lin = world[:3, :3]
        det = np.linalg.det(lin)
        try:
            nmat = np.linalg.inv(lin).T
        except np.linalg.LinAlgError:
            nmat = np.eye(3)
        cn = cn @ nmat.T
        if det < 0:  # mirrored object: keep winding consistent with outward normals
            tv = tv.reshape(-1, 3)[:, ::-1].reshape(-1)
            cn = cn.reshape(-1, 3, 3)[:, ::-1].reshape(-1, 3)
        r.update(co=co, tv=tv, cn=cn, mi=mi)


def _to_gltf(a):
    return np.stack((a[..., 0], a[..., 2], -a[..., 1]), axis=-1)


def _normalize_normals(cn, tris):
    length = np.linalg.norm(cn, axis=1)
    bad = ~(np.isfinite(length) & (length > 1e-12))
    length[bad] = 1.0
    cn = cn / length[:, None]
    if bad.any():
        face = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
        fl = np.linalg.norm(face, axis=1)
        ok = np.isfinite(fl) & (fl > 1e-20)
        face[ok] /= fl[ok, None]
        face[~ok] = (0.0, 1.0, 0.0)
        cn[bad] = np.repeat(face, 3, axis=0)[bad]
    return cn


def _recentre(records, timings):
    """Centre bbox at origin, largest half-extent 4.0; converts everything to glTF axes in place.
    Returns the Blender-axes affine (scale, centre) so arrows get the identical transform."""
    lows = [r["co"].min(axis=0) for r in records if len(r["co"])]
    highs = [r["co"].max(axis=0) for r in records if len(r["co"])]
    if lows:
        low, high = np.min(lows, axis=0), np.max(highs, axis=0)
        centre = (low + high) * 0.5
        extent = float(np.max((high - low) * 0.5))
        scale = HALF_EXTENT / extent if extent > 1e-9 and math.isfinite(extent) else 1.0
    else:
        centre, scale = np.zeros(3), 1.0
    for r in records:
        co = _to_gltf((r["co"] - centre) * scale).astype(np.float32)
        tris = co[r["tv"]].reshape(-1, 3, 3)
        cn = _normalize_normals(_to_gltf(r["cn"]), tris).astype(np.float32)
        r.update(co=co, tris=tris, cn=cn)
    timings["scale"] = round(scale, 5)
    return centre, scale


# ---------------------------------------------------------------- materials / styles

def _material_props(material):
    if material is None:
        return {"rgba": (0.8, 0.8, 0.8, 1.0), "metallic": 0.0, "roughness": 0.5,
                "emission": None, "strength": 0.0, "name": "default"}
    rgba = tuple(float(v) for v in material.diffuse_color)
    metallic = float(getattr(material, "metallic", 0.0))
    roughness = float(getattr(material, "roughness", 0.5))
    emission, strength = None, 0.0
    tree = getattr(material, "node_tree", None)
    bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if tree else None
    if bsdf:
        try:
            base = bsdf.inputs["Base Color"].default_value
            rgba = (float(base[0]), float(base[1]), float(base[2]),
                    float(bsdf.inputs["Alpha"].default_value))
            metallic = float(bsdf.inputs["Metallic"].default_value)
            roughness = float(bsdf.inputs["Roughness"].default_value)
            socket = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
            power = bsdf.inputs.get("Emission Strength")
            strength = float(power.default_value) if power else 1.0
            if socket and strength > 0:
                col = tuple(float(socket.default_value[i]) for i in range(3))
                if max(col) > 0:
                    emission = col
        except (KeyError, TypeError, ValueError, IndexError):
            pass
    clamp = lambda v: max(0.0, min(1.0, v))  # noqa: E731
    return {"rgba": tuple(clamp(v) for v in rgba), "metallic": clamp(metallic),
            "roughness": clamp(roughness), "emission": emission, "strength": strength,
            "name": material.name}


def _style(records, pid, cache):
    for r in records:
        if r["pid"] == pid and r["mesh"].materials:
            props = cache(r["mesh"].materials[0])
            rgba = props["rgba"]
            return {"rgba": rgba, "hex": "#%02x%02x%02x" % tuple(round(v * 255) for v in rgba[:3])}
    return {"rgba": (1.0, 1.0, 1.0, 1.0), "hex": "#ffffff"}


# ---------------------------------------------------------------- GLB writer

class _Glb:
    def __init__(self):
        self.bin = bytearray()
        self.views, self.accessors = [], []

    def add(self, array, component, kind, target=None, minmax=False):
        array = np.ascontiguousarray(array)
        while len(self.bin) % 4:
            self.bin.append(0)
        offset = len(self.bin)
        self.bin += array.tobytes()
        view = {"buffer": 0, "byteOffset": offset, "byteLength": array.nbytes}
        if target:
            view["target"] = target
        self.views.append(view)
        acc = {"bufferView": len(self.views) - 1, "componentType": component,
               "count": int(array.shape[0]), "type": kind}
        if minmax:
            acc["min"] = [float(v) for v in array.min(axis=0)]
            acc["max"] = [float(v) for v in array.max(axis=0)]
        self.accessors.append(acc)
        return len(self.accessors) - 1


def _write_glb(path, records, material_cache):
    glb = _Glb()
    materials, mat_index = [], {}
    uses_strength = False

    def material_id(material):
        nonlocal uses_strength
        key = material.as_pointer() if material is not None else 0
        if key not in mat_index:
            p = material_cache(material)
            entry = {"name": p["name"], "doubleSided": True,
                     "pbrMetallicRoughness": {"baseColorFactor": list(p["rgba"]),
                                              "metallicFactor": p["metallic"],
                                              "roughnessFactor": p["roughness"]}}
            if p["rgba"][3] < 1.0:
                entry["alphaMode"] = "BLEND"
            if p["emission"]:
                entry["emissiveFactor"] = list(p["emission"])
                if p["strength"] > 1.0:
                    entry["extensions"] = {"KHR_materials_emissive_strength":
                                           {"emissiveStrength": p["strength"]}}
                    uses_strength = True
            mat_index[key] = len(materials)
            materials.append(entry)
        return mat_index[key]

    nodes, meshes = [], []
    for r in records:
        if not len(r["tv"]):
            continue
        # one glTF vertex per unique (vertex, quantised corner normal) → indexed, smooth where smooth
        q = np.clip(np.rint((r["cn"] + 1.0) * 511.5), 0, 1023).astype(np.int64)
        key = (r["tv"].astype(np.int64) << 30) | (q[:, 0] << 20) | (q[:, 1] << 10) | q[:, 2]
        uniq, first, inverse = np.unique(key, return_index=True, return_inverse=True)
        positions = r["co"][r["tv"][first]]
        normals = r["cn"][first]
        itype, ictype = (np.uint16, 5123) if len(uniq) < 65536 else (np.uint32, 5125)
        pos_acc = glb.add(positions, 5126, "VEC3", 34962, minmax=True)
        nrm_acc = glb.add(normals, 5126, "VEC3", 34962)
        corner_idx = inverse.reshape(-1, 3).astype(itype)
        mesh_mats = list(r["mesh"].materials) or [None]
        mi = np.clip(r["mi"], 0, len(mesh_mats) - 1)
        primitives = []
        for slot in np.unique(mi):
            idx = corner_idx[mi == slot].reshape(-1)
            prim = {"attributes": {"POSITION": pos_acc, "NORMAL": nrm_acc},
                    "indices": glb.add(idx, ictype, "SCALAR", 34963), "mode": 4}
            material = mesh_mats[int(slot)]
            prim["material"] = material_id(material)
            primitives.append(prim)
        meshes.append({"name": r["mesh"].name, "primitives": primitives})
        nodes.append({"name": r["name"], "mesh": len(meshes) - 1,
                      "extras": {"opto_part": r["pid"], "opto_internal": bool(r["internal"])}})
    while len(glb.bin) % 4:
        glb.bin.append(0)
    doc = {"asset": {"version": "2.0", "generator": "Opto Forge runtime"},
           "scene": 0, "scenes": [{"name": "Scene", "nodes": list(range(len(nodes)))}],
           "nodes": nodes, "meshes": meshes, "materials": materials,
           "accessors": glb.accessors, "bufferViews": glb.views,
           "buffers": [{"byteLength": len(glb.bin)}]}
    if uses_strength:
        doc["extensionsUsed"] = ["KHR_materials_emissive_strength"]
    if not nodes:
        for k in ("meshes", "materials", "accessors", "bufferViews", "buffers"):
            doc.pop(k)
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    chunks = struct.pack("<II", len(js), 0x4E4F534A) + js
    if nodes:
        chunks += struct.pack("<II", len(glb.bin), 0x004E4942) + bytes(glb.bin)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, 12 + len(chunks)) + chunks)


def _export_bpy_gltf(path, records):
    """Fallback: Blender's own exporter on objects rebuilt from the final (re-centred) arrays."""
    import logging
    scene = bpy.context.scene
    for obj in list(scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for r in records:
        mesh = r["mesh"]
        blender = r["co"][:, (0, 2, 1)] * np.array((1, -1, 1), np.float32)  # glTF → Blender axes
        if len(blender) == len(mesh.vertices):
            mesh.vertices.foreach_set("co", blender.reshape(-1))
            mesh.update()
        obj = bpy.data.objects.new(r["name"], mesh)
        obj["opto_part"] = r["pid"]
        obj["opto_internal"] = bool(r["internal"])
        scene.collection.objects.link(obj)
    for name in ("glTFImporter", "io_scene_gltf2", ""):
        logging.getLogger(name).setLevel(logging.WARNING)
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", export_yup=True,
                              export_apply=False, export_extras=True, use_selection=False,
                              export_materials="EXPORT", export_cameras=False, export_lights=False,
                              export_animations=False, export_tangents=False, export_texcoords=False,
                              export_image_format="NONE", export_draco_mesh_compression_enable=False)


# ---------------------------------------------------------------- job

def _error_text(exc, source):
    if isinstance(exc, ScriptProblem):
        return "ScriptProblem: %s\n" % exc
    lines = ["Traceback (most recent call last):"]
    source_lines = source.splitlines()
    for frame, lineno in traceback.walk_tb(exc.__traceback__):
        if frame.f_code.co_filename == "kimi_scene.py":
            lines.append('  File "kimi_scene.py", line %d, in %s' % (lineno, frame.f_code.co_name))
            if 0 < lineno <= len(source_lines):
                lines.append("    " + source_lines[lineno - 1].strip())
    if isinstance(exc, SyntaxError) and exc.filename == "kimi_scene.py":
        lines.append('  File "kimi_scene.py", line %s' % exc.lineno)
        if exc.text:
            lines.append("    " + exc.text.strip())
    if len(lines) == 1 and not isinstance(exc, SyntaxError):
        # crash inside the runtime (not the model's script): keep the full trace for debugging
        return "".join(traceback.format_exception(exc))
    lines.append("%s: %s" % (type(exc).__name__, exc))
    return "\n".join(lines) + "\n"


def build(source, outdir, timings):
    start = time.perf_counter()
    mark = [start]

    def lap(name):
        now = time.perf_counter()
        timings[name] = round(now - mark[0], 4)
        mark[0] = now

    _install_fast_ops()
    script_globals = {"__name__": "__main__", "__builtins__": __builtins__,
                      "bpy": bpy, "bmesh": bmesh, "math": math,
                      "Vector": Vector, "Matrix": Matrix, "Euler": Euler,
                      "meta": meta, "mat": mat, "part": part, "arrow": arrow, "beat": beat}
    code = compile(source, "kimi_scene.py", "exec")
    if os.environ.get("OPTO_PROFILE"):
        import cProfile
        import pstats
        prof = cProfile.Profile()
        try:
            prof.runctx("exec(code, g)", {"code": code, "g": script_globals}, {})
        finally:
            pstats.Stats(prof, stream=sys.stderr).sort_stats("tottime").print_stats(25)
    else:
        try:
            exec(code, script_globals)
        except SystemExit as exc:  # sys.exit() / exit() at the end of a script: fine if it means success
            if exc.code not in (None, 0):
                raise
    script_globals.clear()
    lap("script")

    objects = _export_objects()
    if os.environ.get("OPTO_DEBUG"):
        names = {o.name for o in objects}
        print("opto-skipped", [(o.name, o.type) for o in bpy.context.view_layer.objects
                               if o.name not in names], file=sys.stderr)
    _cap_modifiers(objects)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    records = _bake(objects, depsgraph)
    lap("evaluate")
    _decimate(records, timings)
    lap("decimate")
    if not records or not sum(r["tris"] for r in records):
        raise ScriptProblem(
            "Your script produced no mesh geometry (0 triangles after modifiers). Every visible object "
            "must be a mesh with faces (or a curve with bevel_depth/extrude) linked into the scene, e.g. "
            "bpy.context.scene.collection.objects.link(obj), and not hidden or deleted.")
    registered = {p["id"] for p in PARTS}
    if PARTS and not any(r["pid"] in registered and r["tris"] for r in records):
        raise ScriptProblem(
            "None of the part(...) registrations has any geometry: pass the mesh objects themselves "
            "(not empties, curves without bevel, or objects you deleted/joined afterwards) to part().")
    _arrays(records)
    centre, scale = _recentre(records, timings)
    lap("numpy")

    cache = {}

    def material_cache(material):
        key = material.as_pointer() if material is not None else 0
        if key not in cache:
            cache[key] = _material_props(material)
        return cache[key]

    glb_path = outdir / "model.glb"
    if USE_BPY_EXPORTER:
        _export_bpy_gltf(glb_path, records)
    else:
        try:
            _write_glb(glb_path, records, material_cache)
        except Exception:  # noqa: BLE001 - never lose a scene to our writer; use Blender's
            traceback.print_exc()
            _export_bpy_gltf(glb_path, records)
    lap("glb")

    known = {p["id"] for p in PARTS}
    for r in records:  # objects parented under a since-deleted part etc.
        if r["pid"] not in known:
            r["pid"] = "_structure"
    groups = {}
    for r in records:
        g = groups.setdefault(r["pid"], {"tris": [], "nrm": [], "low": [], "high": []})
        if len(r["tris"]):
            g["tris"].append(r["tris"])
            g["nrm"].append(r["cn"])
            g["low"].append(r["co"].min(axis=0))
            g["high"].append(r["co"].max(axis=0))

    def bounds(pid):
        g = groups.get(pid)
        if not g or not g["low"]:
            return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
        return ([round(float(v), 5) for v in np.min(g["low"], axis=0)],
                [round(float(v), 5) for v in np.max(g["high"], axis=0)])

    styles = {pid: _style(records, pid, material_cache) for pid in [p["id"] for p in PARTS] + ["_structure"]}
    arrays = {}
    for pid in [p["id"] for p in PARTS] + ["_structure"]:
        g = groups.get(pid)
        if g and g["tris"]:
            arrays[pid + "__tris"] = np.concatenate(g["tris"]).astype(np.float32, copy=False)
            arrays[pid + "__nrm"] = np.concatenate(g["nrm"]).astype(np.float32, copy=False)
        else:
            arrays[pid + "__tris"] = np.zeros((0, 3, 3), np.float32)
            arrays[pid + "__nrm"] = np.zeros((0, 3), np.float32)
        arrays[pid + "__color"] = np.asarray(styles[pid]["rgba"], np.float32)
    np.savez(outdir / "mesh.npz", **arrays)

    mapping = {}
    for entry in PARTS:
        mapping[entry["name"].strip().casefold()] = entry["id"]
        mapping[entry["id"].casefold()] = entry["id"]
    beats = []
    for item in BEATS:
        focus = []
        for value in item["focus"]:
            if isinstance(value, bpy.types.Object):
                try:
                    value = value.get("opto_part", value.name)
                except ReferenceError:
                    continue
            pid = mapping.get(str(value).strip().casefold())
            if pid is not None and pid not in focus:
                focus.append(pid)
        beats.append({"say": item["say"], "focus": focus, "do": item["do"]})
    axis = {"x": "x", "y": "z", "z": "y"}[META["cut_axis"]]
    keep = META["keep"]
    if META["cut_axis"] == "y":  # Blender +y → glTF −z
        keep = "pos" if keep == "neg" else "neg"
    parts, labels = [], []
    for entry in PARTS:
        pid = entry["id"]
        low, high = bounds(pid)
        g = groups.get(pid)
        parts.append({"id": pid, "name": entry["name"], "info": entry["info"],
                      "internal": entry["internal"], "label": entry["label"],
                      "label_color": entry["label_color"], "color": styles[pid]["hex"],
                      "opacity": styles[pid]["rgba"][3], "bbox_min": low, "bbox_max": high,
                      "tris": int(sum(len(t) for t in g["tris"])) if g else 0})
        if entry["label"]:
            labels.append({"part": pid, "text": entry["label"], "color": entry["label_color"]})

    def arrow_point(p):
        v = (np.asarray(p, np.float64) - centre) * scale
        return [round(float(x), 5) for x in (v[0], v[2], -v[1])]

    all_low = [np.min(g["low"], axis=0) for g in groups.values() if g["low"]]
    all_high = [np.max(g["high"], axis=0) for g in groups.values() if g["high"]]
    bbox_min = [round(float(v), 5) for v in np.min(all_low, axis=0)] if all_low else [0.0] * 3
    bbox_max = [round(float(v), 5) for v in np.max(all_high, axis=0)] if all_high else [0.0] * 3
    scene = {"title": META["title"], "subtitle": META["subtitle"],
             "cut": {"axis": axis, "keep": keep}, "parts": parts,
             "arrows": [{"from": arrow_point(a["from"]), "to": arrow_point(a["to"]),
                         "color": a["color"], "label": a["label"]} for a in ARROWS],
             "labels": labels, "beats": beats,
             "stats": {"objects": len(records), "parts": len(PARTS),
                       "tris": int(sum(len(r["tris"]) for r in records)),
                       "bbox_min": bbox_min, "bbox_max": bbox_max,
                       "seconds": round(time.perf_counter() - start, 3)}}
    (outdir / "scene.json").write_text(json.dumps(scene, indent=1), encoding="utf-8")
    lap("write")
    timings["tris"] = scene["stats"]["tris"]
    for r in records:
        r.clear()
    return scene


def run_job(script, outdir):
    """Run one script → outputs in outdir. Never raises; returns {"ok", "error"?, "timings"}."""
    timings = {}
    t0 = time.perf_counter()
    source = ""
    outdir = Path(outdir)
    try:
        _reset()
        timings["leftover"] = _leftovers()
        timings["reset"] = round(time.perf_counter() - t0, 4)
        source = Path(script).read_text(encoding="utf-8")
        outdir.mkdir(parents=True, exist_ok=True)
        build(source, outdir, timings)
        try:
            (outdir / "error.txt").unlink()
        except FileNotFoundError:
            pass
        result = {"ok": True}
    except BaseException as exc:  # noqa: BLE001 - SystemExit from the script must not kill a worker
        if isinstance(exc, KeyboardInterrupt):
            raise
        text = _error_text(exc, source)
        try:
            outdir.mkdir(parents=True, exist_ok=True)
            (outdir / "error.txt").write_text(text, encoding="utf-8")
        except OSError:
            pass
        result = {"ok": False, "error": text[-3000:]}
    timings["total"] = round(time.perf_counter() - t0, 4)
    result["timings"] = timings
    return result


def worker():
    proto_out, proto_in = _PROTO_OUT, _PROTO_IN
    sys.stdout = sys.stderr
    _reset()
    proto_out.write(json.dumps({"ready": True, "pid": os.getpid()}) + "\n")
    for line in proto_in:
        line = line.strip()
        if not line:
            continue
        req = None
        try:
            req = json.loads(line)
            res = run_job(req["script"], req["outdir"])
        except Exception as exc:  # noqa: BLE001
            res = {"ok": False, "error": "worker: %r" % exc, "timings": {}}
        res["id"] = req.get("id") if isinstance(req, dict) else None
        sys.stderr.flush()
        proto_out.write(json.dumps(res) + "\n")


if __name__ == "__main__":
    if sys.argv[1:] == ["--worker"]:
        worker()
    elif len(sys.argv) == 3:
        res = run_job(sys.argv[1], sys.argv[2])
        print("opto-timings " + json.dumps(res["timings"]), file=sys.stderr)
        sys.exit(0 if res["ok"] else 3)
    else:
        print("usage: forge_runtime.py SCRIPT.py OUTDIR | --worker", file=sys.stderr)
        sys.exit(2)
