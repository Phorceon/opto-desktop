import contextlib
import io
import json
import logging
import math
import re
import sys
import time
import traceback
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Euler, Matrix, Vector


META = {"title": "", "subtitle": "", "cut_axis": "y", "keep": "neg"}
PARTS = []
ARROWS = []
BEATS = []
MATERIALS = {}
SLUGS = set()
PALETTE = ("yellow", "pink", "green", "blue", "orange", "purple")
DO_VALUES = {"build", "highlight", "cut", "explode", "flow", "orbit"}
TRIANGLE_BUDGET = 120000
START = time.perf_counter()


def _rgb(value, default="#ffffff"):
    try:
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
    while candidate in SLUGS:
        number += 1
        suffix = "_%d" % number
        candidate = base[:40 - len(suffix)].rstrip("_") + suffix
    SLUGS.add(candidate)
    return candidate


def meta(title, subtitle, cut_axis="y", keep="neg"):
    META.update(title=str(title), subtitle=str(subtitle))
    META["cut_axis"] = str(cut_axis).lower() if str(cut_axis).lower() in "xyz" else "y"
    META["keep"] = str(keep).lower() if str(keep).lower() in ("neg", "pos") else "neg"


def mat(name, color, metallic=0.0, roughness=0.5, alpha=1.0, emission=None):
    name = str(name)
    if name in MATERIALS:
        return MATERIALS[name]
    alpha = float(alpha)
    rgba = (*_rgb(color), alpha)
    material = bpy.data.materials.new(name)
    node_tree = getattr(material, "node_tree", None)
    if hasattr(material, "use_nodes") and node_tree is None:
        material.use_nodes = True
        node_tree = getattr(material, "node_tree", None)
    material.diffuse_color = rgba
    bsdf = next((n for n in node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) \
        if node_tree is not None else None
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
        obj["opto_internal"] = bool(internal)
    PARTS.append({"id": pid, "name": str(name), "info": str(info),
                  "internal": bool(internal), "label": label,
                  "label_color": color, "objects": objects})
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


def _delete(obj):
    try:
        parent = obj.parent
        for child in list(obj.children):
            world = child.matrix_world.copy()
            child.parent = parent
            child.matrix_world = world
        bpy.data.objects.remove(obj, do_unlink=True)
    except (ReferenceError, RuntimeError):
        pass


def _world_vertices(obj):
    mesh = obj.data
    count = len(mesh.vertices)
    if not count:
        return np.empty((0, 3), dtype=np.float64)
    coordinates = np.empty(count * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", coordinates)
    coordinates = coordinates.reshape(-1, 3)
    world = np.asarray(obj.matrix_world, dtype=np.float64)
    return coordinates @ world[:3, :3].T + world[:3, 3]


def _gltf_array(values):
    signs = np.asarray((1.0, 1.0, -1.0), dtype=values.dtype)
    return values[:, (0, 2, 1)] * signs


def _mesh_geometry(obj):
    vertices = _gltf_array(_world_vertices(obj))
    mesh = obj.data
    mesh.calc_loop_triangles()
    triangle_count = len(mesh.loop_triangles)
    if not triangle_count:
        return (vertices, np.empty((0, 3, 3), dtype=np.float64),
                np.empty((0, 3), dtype=np.float64))

    triangle_vertices = np.empty(triangle_count * 3, dtype=np.int32)
    triangle_loops = np.empty(triangle_count * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", triangle_vertices)
    mesh.loop_triangles.foreach_get("loops", triangle_loops)
    triangles = vertices[triangle_vertices].reshape(-1, 3, 3)

    normal_values = np.zeros(len(mesh.loops) * 3, dtype=np.float32)
    try:
        mesh.corner_normals.foreach_get("vector", normal_values)
    except (AttributeError, RuntimeError, ValueError):
        try:
            mesh.loops.foreach_get("normal", normal_values)
        except (AttributeError, RuntimeError, ValueError):
            normal_values.fill(0.0)
    corner_normals = normal_values.reshape(-1, 3)[triangle_loops]

    world = obj.matrix_world
    try:
        normal_matrix = np.asarray(world.to_3x3().inverted().transposed(),
                                   dtype=np.float64)
    except ValueError:
        normal_matrix = np.eye(3, dtype=np.float64)
    normals = _gltf_array(corner_normals @ normal_matrix.T)

    lengths = np.linalg.norm(normals, axis=1)
    valid = (np.isfinite(normals).all(axis=1) & np.isfinite(lengths)
             & (lengths > 1e-12))
    normals[valid] /= lengths[valid, None]
    invalid = ~valid
    if invalid.any():
        face_normals = np.cross(triangles[:, 1] - triangles[:, 0],
                                triangles[:, 2] - triangles[:, 0])
        face_lengths = np.linalg.norm(face_normals, axis=1)
        face_valid = (np.isfinite(face_normals).all(axis=1)
                      & np.isfinite(face_lengths) & (face_lengths > 1e-12))
        face_normals[face_valid] /= face_lengths[face_valid, None]
        face_normals[~face_valid] = (0.0, 1.0, 0.0)
        normals[invalid] = np.repeat(face_normals, 3, axis=0)[invalid]

    return vertices, triangles, normals


def _baked_mesh(evaluated, depsgraph, original_materials):
    mesh = bpy.data.meshes.new_from_object(
        evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
    if mesh is None:
        return None
    materials = list(mesh.materials) or list(original_materials)
    mesh.materials.clear()
    for material in materials:
        mesh.materials.append(material)
    return mesh


def _install_baked_mesh(obj, mesh):
    old_mesh = obj.data
    obj.data = mesh
    obj.modifiers.clear()
    try:
        if old_mesh != mesh and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
    except (AttributeError, ReferenceError, RuntimeError):
        pass


def _decimate_to_budget(meshes):
    counts = []
    total = 0
    for obj in meshes:
        try:
            obj.data.calc_loop_triangles()
            count = len(obj.data.loop_triangles)
        except (AttributeError, ReferenceError, RuntimeError):
            count = 0
        counts.append((obj, count))
        total += count
    if total <= TRIANGLE_BUDGET:
        return

    ratio = max(0.15, min(1.0, TRIANGLE_BUDGET / float(total)))
    targets = []
    for obj, count in counts:
        if count <= 2000:
            continue
        try:
            modifier = obj.modifiers.new("Opto triangle budget", "DECIMATE")
            modifier.decimate_type = "COLLAPSE"
            modifier.ratio = ratio
            if hasattr(modifier, "use_collapse_triangulate"):
                modifier.use_collapse_triangulate = True
            targets.append(obj)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    if not targets:
        return

    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    for obj in targets:
        try:
            original_materials = list(obj.data.materials)
            evaluated = obj.evaluated_get(depsgraph)
            mesh = _baked_mesh(evaluated, depsgraph, original_materials)
            if mesh is not None:
                _install_baked_mesh(obj, mesh)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        finally:
            try:
                obj.modifiers.clear()
            except (AttributeError, ReferenceError, RuntimeError):
                pass


def _prepare_geometry():
    for obj in list(bpy.data.objects):
        try:
            obj.hide_viewport = False
            obj.hide_render = False
            obj.hide_set(False)
        except (AttributeError, ReferenceError, RuntimeError):
            pass

    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    replacements = {}

    for obj in list(bpy.data.objects):
        if obj.type not in {"MESH", "CURVE", "FONT", "SURFACE", "META"}:
            continue
        try:
            world = obj.matrix_world.copy()
            original_materials = list(getattr(obj.data, "materials", ()))
            evaluated = obj.evaluated_get(depsgraph)
            mesh = _baked_mesh(evaluated, depsgraph, original_materials)
            if mesh is None:
                continue
            if obj.type == "MESH":
                _install_baked_mesh(obj, mesh)
                continue

            new_obj = bpy.data.objects.new(obj.name + ".evaluated", mesh)
            for collection in obj.users_collection:
                collection.objects.link(new_obj)
            if not new_obj.users_collection:
                bpy.context.scene.collection.objects.link(new_obj)
            for key in obj.keys():
                try:
                    new_obj[key] = obj[key]
                except (TypeError, ValueError):
                    pass
            new_obj.parent = obj.parent
            new_obj.matrix_world = world
            replacements[obj] = new_obj
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue

    for obj in list(bpy.data.objects):
        if obj.parent in replacements:
            world = obj.matrix_world.copy()
            obj.parent = replacements[obj.parent]
            obj.matrix_world = world

    names = {new: old.name for old, new in replacements.items()}
    for entry in PARTS:
        entry["objects"] = [replacements.get(obj, obj) for obj in entry["objects"]]
    for old in replacements:
        _delete(old)
    for new, name in names.items():
        try:
            new.name = name
        except ReferenceError:
            pass

    for obj in list(bpy.data.objects):
        if obj.type != "MESH" or "opto_part" in obj:
            continue
        parent = obj.parent
        while parent is not None:
            if "opto_part" in parent:
                obj["opto_part"] = str(parent["opto_part"])
                obj["opto_internal"] = bool(parent.get("opto_internal", False))
                break
            parent = parent.parent

    keep = set()
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            parent = obj.parent
            while parent is not None:
                if parent.type == "EMPTY":
                    keep.add(parent)
                parent = parent.parent

    for obj in list(bpy.data.objects):
        if obj.type == "MESH" and not obj.data.polygons:
            _delete(obj)
        elif obj.type != "MESH" and obj not in keep:
            _delete(obj)

    meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    for obj in meshes:
        if "opto_part" not in obj:
            obj["opto_part"] = "_structure"
        if "opto_internal" not in obj:
            obj["opto_internal"] = False

    _decimate_to_budget(meshes)
    bpy.context.view_layer.update()

    low = None
    high = None
    for obj in meshes:
        try:
            vertices = _world_vertices(obj)
            if not len(vertices):
                continue
            vertices = vertices[np.isfinite(vertices).all(axis=1)]
            if not len(vertices):
                continue
            mesh_low = vertices.min(axis=0)
            mesh_high = vertices.max(axis=0)
            low = mesh_low if low is None else np.minimum(low, mesh_low)
            high = mesh_high if high is None else np.maximum(high, mesh_high)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue

    if low is not None and high is not None:
        centre_values = (low + high) * 0.5
        centre = Vector(tuple(float(value) for value in centre_values))
        extent = float(np.max((high - low) * 0.5))
        scale = 4.0 / extent if extent > 1e-12 and math.isfinite(extent) else 1.0
    else:
        centre = Vector((0.0, 0.0, 0.0))
        scale = 1.0

    transform = Matrix.Scale(scale, 4) @ Matrix.Translation(-centre)
    for obj in list(bpy.data.objects):
        if obj.parent is None:
            try:
                obj.matrix_world = transform @ obj.matrix_world
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
    bpy.context.view_layer.update()

    for item in ARROWS:
        for key in ("from", "to"):
            homogeneous = Vector((*item[key], 1.0))
            item[key] = _point(transform @ homogeneous)
    return meshes


def _gltf(value):
    return Vector((float(value[0]), float(value[2]), float(-value[1])))


def _style(objects):
    material = None
    for obj in objects:
        try:
            if obj.data.materials:
                material = obj.data.materials[0]
                break
        except (AttributeError, ReferenceError):
            pass
    rgba = (1.0, 1.0, 1.0, 1.0)
    if material is not None:
        try:
            rgba = tuple(float(v) for v in material.diffuse_color)
        except (AttributeError, TypeError):
            pass
        node_tree = getattr(material, "node_tree", None)
        if node_tree is not None:
            bsdf = next((n for n in node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if bsdf:
                try:
                    base = bsdf.inputs["Base Color"].default_value
                    rgba = (*[float(base[i]) for i in range(3)],
                            float(bsdf.inputs["Alpha"].default_value))
                except (KeyError, TypeError, ValueError):
                    pass
        rgba = tuple(max(0.0, min(1.0, float(v))) for v in rgba)
    return {"rgba": rgba, "hex": "#%02x%02x%02x" % tuple(round(v * 255) for v in rgba[:3])}


def _geometry(meshes):
    meshes = [obj for obj in meshes if obj.name in bpy.data.objects]
    live = {obj.as_pointer(): obj for obj in meshes}
    style_objects = {"_structure": [obj for obj in meshes
                                    if obj.get("opto_part") == "_structure"]}
    groups = {"_structure": {"tris": [], "normals": [], "low": None, "high": None}}

    def _ptr(obj):
        try:
            return obj.as_pointer()
        except ReferenceError:
            return None

    for entry in PARTS:
        pid = entry["id"]
        groups[pid] = {"tris": [], "normals": [], "low": None, "high": None}
        style_objects[pid] = [live[_ptr(obj)] for obj in entry["objects"]
                              if _ptr(obj) in live]
    styles = {pid: _style(objects) for pid, objects in style_objects.items()}

    all_low = None
    all_high = None
    for obj in meshes:
        pid = str(obj.get("opto_part", "_structure"))
        if pid not in groups:
            pid = "_structure"
            obj["opto_part"] = pid
        group = groups[pid]
        try:
            vertices, triangles, normals = _mesh_geometry(obj)
            if len(vertices):
                low = vertices.min(axis=0)
                high = vertices.max(axis=0)
                group["low"] = low if group["low"] is None else np.minimum(group["low"], low)
                group["high"] = high if group["high"] is None else np.maximum(group["high"], high)
                all_low = low if all_low is None else np.minimum(all_low, low)
                all_high = high if all_high is None else np.maximum(all_high, high)
            if len(triangles):
                group["tris"].append(triangles)
                group["normals"].append(normals)
        except (AttributeError, IndexError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            pass

    for group in groups.values():
        if group["tris"]:
            group["tris"] = np.concatenate(group["tris"], axis=0)
            group["normals"] = np.concatenate(group["normals"], axis=0)
        else:
            group["tris"] = np.empty((0, 3, 3), dtype=np.float32)
            group["normals"] = np.empty((0, 3), dtype=np.float32)
    return groups, styles, all_low, all_high


def _bounds(group):
    if group["low"] is None:
        return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    return ([float(value) for value in group["low"]],
            [float(value) for value in group["high"]])


def _export_glb(outdir):
    loggers = (logging.getLogger(), logging.getLogger("glTFImporter"),
               logging.getLogger("io_scene_gltf2"))
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.WARNING)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            bpy.ops.export_scene.gltf(
                filepath=str(outdir / "model.glb"), export_format="GLB",
                export_yup=True, export_apply=False, export_extras=True,
                use_selection=False, export_materials="EXPORT",
                export_cameras=False, export_lights=False, export_animations=False)
    finally:
        for logger, level in zip(loggers, levels):
            logger.setLevel(level)


def _write_outputs(outdir, groups, styles, all_low, all_high):
    _export_glb(outdir)
    mapping = {}
    for entry in PARTS:
        mapping[entry["name"].strip().casefold()] = entry["id"]
        mapping[entry["id"].casefold()] = entry["id"]
    beats = []
    for item in BEATS:
        focus = []
        for value in item["focus"]:
            pid = mapping.get(str(value).strip().casefold())
            if pid is not None and pid not in focus:
                focus.append(pid)
        beats.append({"say": item["say"], "focus": focus, "do": item["do"]})

    axis = {"x": "x", "y": "z", "z": "y"}[META["cut_axis"]]
    keep = META["keep"]
    if META["cut_axis"] == "y":
        keep = "pos" if keep == "neg" else "neg"

    parts = []
    labels = []
    arrays = {}
    for entry in PARTS:
        pid = entry["id"]
        low, high = _bounds(groups[pid])
        style = styles[pid]
        parts.append({"id": pid, "name": entry["name"], "info": entry["info"],
                      "internal": entry["internal"], "label": entry["label"],
                      "label_color": entry["label_color"], "color": style["hex"],
                      "opacity": style["rgba"][3], "bbox_min": low, "bbox_max": high,
                      "tris": len(groups[pid]["tris"])})
        if entry["label"]:
            labels.append({"part": pid, "text": str(entry["label"]),
                           "color": entry["label_color"]})

    for pid, group in groups.items():
        arrays[pid + "__tris"] = np.asarray(group["tris"], dtype=np.float32).reshape(-1, 3, 3)
        arrays[pid + "__nrm"] = np.asarray(group["normals"], dtype=np.float32).reshape(-1, 3)
        arrays[pid + "__color"] = np.asarray(styles[pid]["rgba"], dtype=np.float32)

    scene_parts_tris = sum(len(groups[entry["id"]]["tris"]) for entry in PARTS)
    total_tris = scene_parts_tris + len(groups["_structure"]["tris"])
    if all_low is None:
        bbox_min = bbox_max = [0.0, 0.0, 0.0]
    else:
        bbox_min = [float(value) for value in all_low]
        bbox_max = [float(value) for value in all_high]

    scene = {
        "title": META["title"],
        "subtitle": META["subtitle"],
        "cut": {"axis": axis, "keep": keep},
        "parts": parts,
        "arrows": [{"from": _point(_gltf(item["from"])),
                    "to": _point(_gltf(item["to"])),
                    "color": item["color"], "label": item["label"]}
                   for item in ARROWS],
        "labels": labels,
        "beats": beats,
        "stats": {"objects": len([obj for obj in bpy.data.objects if obj.type == "MESH"]),
                  "parts": len(PARTS), "tris": total_tris,
                  "bbox_min": bbox_min, "bbox_max": bbox_max,
                  "seconds": time.perf_counter() - START}
    }
    (outdir / "scene.json").write_text(json.dumps(scene, indent=2), encoding="utf-8")
    np.savez(outdir / "mesh.npz", **arrays)


def _error_text(exc, source):
    lines = ["Traceback (most recent call last):"]
    for frame, lineno in traceback.walk_tb(exc.__traceback__):
        if frame.f_code.co_filename == "kimi_scene.py":
            lines.append('  File "kimi_scene.py", line %d, in %s'
                         % (lineno, frame.f_code.co_name))
            source_lines = source.splitlines()
            if 0 < lineno <= len(source_lines):
                lines.append("    " + source_lines[lineno - 1].strip())
    if isinstance(exc, SyntaxError) and exc.filename == "kimi_scene.py":
        lines.append('  File "kimi_scene.py", line %s' % exc.lineno)
        if exc.text:
            lines.append("    " + exc.text.strip())
    if len(lines) == 1 and not isinstance(exc, SyntaxError):
        return "".join(traceback.format_exception(exc))
    lines.append("%s: %s" % (type(exc).__name__, exc))
    return "\n".join(lines) + "\n"


def main():
    if len(sys.argv) != 3:
        raise ValueError("usage: python forge_runtime.py SCRIPT.py OUTDIR")
    source = Path(sys.argv[1]).read_text(encoding="utf-8")
    outdir = Path(sys.argv[2])
    outdir.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    globals_for_script = {"bpy": bpy, "bmesh": bmesh, "math": math,
                          "Vector": Vector, "Matrix": Matrix, "Euler": Euler,
                          "meta": meta, "mat": mat, "part": part,
                          "arrow": arrow, "beat": beat}
    exec(compile(source, "kimi_scene.py", "exec"), globals_for_script)
    meshes = _prepare_geometry()
    bpy.context.view_layer.update()
    groups, styles, low, high = _geometry(meshes)
    _write_outputs(outdir, groups, styles, low, high)
    try:
        (outdir / "error.txt").unlink()
    except FileNotFoundError:
        pass
    return source, outdir


if __name__ == "__main__":
    source, outdir = "", None
    try:
        if len(sys.argv) == 3:
            outdir = Path(sys.argv[2])
            source = Path(sys.argv[1]).read_text(encoding="utf-8")
        source, outdir = main()
    except Exception as exc:
        if outdir is not None:
            try:
                outdir.mkdir(parents=True, exist_ok=True)
                (outdir / "error.txt").write_text(_error_text(exc, source), encoding="utf-8")
            except OSError:
                pass
        sys.exit(3)
