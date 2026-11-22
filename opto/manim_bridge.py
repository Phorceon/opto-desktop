"""Fast Manim OpenGL helpers for Operation Opto videos.

The module deliberately keeps geometry in triangle soups and performs material and
motion animations in place.  Importing it installs the small OpenGL renderer
compatibility patches needed by the project; it does not otherwise initialise a
renderer or OpenGL context.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from manim import (
    Animation,
    Create,
    DEGREES,
    Dot,
    Group,
    LaggedStart,
    NumberPlane,
    SVGMobject,
    ThreeDScene,
    ValueTracker,
    config,
)
from manim.mobject.opengl.opengl_surface import OpenGLSurface, OpenGLTexturedSurface
from manim.mobject.opengl.opengl_vectorized_mobject import OpenGLVMobject
from manim.renderer import shader_wrapper
from manim.renderer.opengl_renderer import OpenGLRenderer

try:
    from manim.utils.color import Color
except ImportError:  # pragma: no cover - compatibility with newer Manim releases
    from manim.utils.color import ManimColor as Color


BG = "#000000"
BLUE_3B1B = "#58C4DD"
BLUE_DIM = "#25577A"
TEAL_3B1B = "#5CD0B3"
YELLOW_3B1B = "#F9E154"
GOLD_3B1B = "#F0AC5F"
MAROON_3B1B = "#EC92AB"
GREEN_3B1B = "#83C167"
RED_3B1B = "#FF7A70"
PURPLE_3B1B = "#B189C6"
WHITE_3B1B = "#ECECEC"
MUTED_3B1B = "#9DB4C8"

_GLTF_TO_MANIM = np.array(
    [[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]],
    dtype=float,
)
_SLATE_BLUE = "#2D4963"


__all__ = [
    "BG",
    "BLUE_3B1B",
    "BLUE_DIM",
    "TEAL_3B1B",
    "YELLOW_3B1B",
    "GOLD_3B1B",
    "MAROON_3B1B",
    "GREEN_3B1B",
    "RED_3B1B",
    "PURPLE_3B1B",
    "WHITE_3B1B",
    "MUTED_3B1B",
    "TriMesh",
    "FlatImage",
    "Reveal",
    "Tint",
    "ShiftFade",
    "SlideAlong",
    "make_arrow_mesh",
    "make_sphere_mesh",
    "fix",
    "math_tex",
    "serif_text",
    "open_curve",
    "ForgeModel",
    "load_forge_model",
]


def _patch_opengl_renderer() -> None:
    """Install each renderer patch exactly once."""
    original_get_texture_id = OpenGLRenderer.get_texture_id
    if not getattr(original_get_texture_id, "_opto_intel_texture_patch", False):

        def get_texture_id(self, path):
            import moderngl

            key = str(path)
            textures = getattr(self, "_opto_textures", None)
            if textures is None:
                textures = {}
                self._opto_textures = textures

            texture = textures.get(key)
            if texture is None:
                with Image.open(key) as source:
                    image = source.convert("RGBA")
                    payload = np.ascontiguousarray(
                        np.asarray(image, dtype=np.uint8)
                    ).tobytes()
                    size = image.size
                context = getattr(self, "context", None) or getattr(self, "ctx")
                texture = context.texture(size, 4, payload)
                texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
                texture.swizzle = "RGBA"
                textures[key] = texture

            texture.use(location=0)
            return 0

        get_texture_id._opto_intel_texture_patch = True
        get_texture_id._opto_original = original_get_texture_id
        OpenGLRenderer.get_texture_id = get_texture_id

    current_shader_loader = shader_wrapper.get_shader_code_from_file
    if not getattr(current_shader_loader, "_opto_shader_cache", False):
        original_shader_loader = current_shader_loader

        @functools.lru_cache(maxsize=None)
        def cached_shader_code(path):
            return original_shader_loader(Path(path))

        cached_shader_code._opto_shader_cache = True
        cached_shader_code._opto_original = original_shader_loader
        shader_wrapper.get_shader_code_from_file = cached_shader_code

    from manim.animation.creation import DrawBorderThenFill
    from manim.utils.bezier import integer_interpolate as _int_interp

    if not getattr(DrawBorderThenFill, "_opto_write_fixed", False):
        _orig_dbf = DrawBorderThenFill.interpolate_submobject

        def _safe_dbf(self, submobject, starting_submobject, outline, alpha):
            idx, _ = _int_interp(0, 2, alpha)
            if idx == 1 and len(submobject.points) != len(outline.points):
                submobject.set_points(outline.points.copy())
            return _orig_dbf(self, submobject, starting_submobject, outline, alpha)

        DrawBorderThenFill.interpolate_submobject = _safe_dbf
        DrawBorderThenFill._opto_write_fixed = True


_patch_opengl_renderer()


def _unit(vector: np.ndarray, fallback: Sequence[float] = (0.0, 0.0, 1.0)) -> np.ndarray:
    vector = np.asarray(vector, dtype=float)
    length = float(np.linalg.norm(vector))
    if length < 1e-12:
        return np.asarray(fallback, dtype=float)
    return vector / length


def _rgb(color: Any) -> np.ndarray:
    if isinstance(color, np.ndarray):
        result = np.asarray(color, dtype=float).reshape(-1)[:3]
        if np.max(result, initial=0.0) > 1.0:
            result = result / 255.0
        return result
    try:
        return np.asarray(Color(color).to_rgb(), dtype=float)
    except (AttributeError, TypeError, ValueError):
        text = str(color).lstrip("#")
        if len(text) == 3:
            text = "".join(character * 2 for character in text)
        if len(text) != 6:
            return np.ones(3, dtype=float)
        return np.array(
            [int(text[index : index + 2], 16) / 255.0 for index in (0, 2, 4)],
            dtype=float,
        )


def _rgba_array(mobject) -> np.ndarray:
    rgbas = getattr(mobject, "rgbas", None)
    if rgbas is None:
        mobject.init_colors()
        rgbas = mobject.rgbas
    return np.asarray(rgbas)


def _sync_opacity(mobject, opacity: float) -> None:
    rgbas = _rgba_array(mobject)
    if rgbas.size:
        rgbas[:, 3] = opacity
    stored = getattr(mobject, "opacity", None)
    if isinstance(stored, np.ndarray) and stored.size:
        stored[:] = opacity


class TriMesh(OpenGLSurface):
    """A coloured, smooth-normal triangle soup rendered in one draw call."""

    def __init__(
        self,
        vertices: np.ndarray,
        normals: np.ndarray | None = None,
        color: Any = BLUE_3B1B,
        opacity: float = 1.0,
        gloss: float = 0.25,
        shadow: float = 0.12,
        depth_test: bool = True,
        **kwargs,
    ):
        vertices = np.asarray(vertices, dtype=float)
        if vertices.size == 0:
            raise ValueError("TriMesh requires at least one triangle vertex")
        self.vertices = np.ascontiguousarray(vertices.reshape(-1, 3), dtype=float)
        if self.vertices.shape[0] % 3:
            raise ValueError("TriMesh vertex count must be divisible by three")

        if normals is None:
            triangles = self.vertices.reshape(-1, 3, 3)
            fn = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
            ln = np.linalg.norm(fn, axis=1, keepdims=True)
            fn = np.where(ln > 1e-12, fn / np.maximum(ln, 1e-12), np.array([0.0, 0.0, 1.0]))
            self.normals = np.repeat(fn, 3, axis=0)
        else:
            n = np.asarray(normals, dtype=float).reshape(self.vertices.shape)
            ln = np.linalg.norm(n, axis=1, keepdims=True)
            self.normals = np.where(ln > 1e-12, n / np.maximum(ln, 1e-12), np.array([0.0, 0.0, 1.0]))

        ref = np.where(np.abs(self.normals[:, [2]]) > 0.90,
                       np.array([[0.0, 1.0, 0.0]]), np.array([[0.0, 0.0, 1.0]]))
        t1 = np.cross(self.normals, ref)
        l1 = np.linalg.norm(t1, axis=1, keepdims=True)
        t1 = np.where(l1 > 1e-12, t1 / np.maximum(l1, 1e-12), np.array([1.0, 0.0, 0.0]))
        t2 = np.cross(self.normals, t1)
        l2 = np.linalg.norm(t2, axis=1, keepdims=True)
        t2 = np.where(l2 > 1e-12, t2 / np.maximum(l2, 1e-12), np.array([0.0, 1.0, 0.0]))
        self.tangent_vectors = (t1, t2)

        super().__init__(
            lambda u, v: np.array([u, v, 0.0]),
            u_range=(0.0, 1.0),
            v_range=(0.0, 1.0),
            resolution=(2, 2),
            color=color,
            gloss=gloss,
            shadow=shadow,
            depth_test=depth_test,
            **kwargs,
        )
        self.set_color(color)
        self.set_opacity(opacity)

    def init_points(self):
        points = self.vertices
        self.points = np.vstack(
            [
                points,
                points + 1e-3 * self.tangent_vectors[0],
                points + 1e-3 * self.tangent_vectors[1],
            ]
        )
        self.triangle_indices = np.arange(len(points), dtype=int)
        return self

    def compute_triangle_indices(self):
        self.triangle_indices = np.arange(len(self.points) // 3, dtype=int)
        return self


class FlatImage(OpenGLTexturedSurface):
    """A borderless, fixed-plane RGBA image using Opto's inexpensive shader."""

    shader_folder = str(Path(__file__).resolve().parent / "shaders" / "flat_image")

    def __init__(
        self,
        png_path: str | Path,
        height: float | None = 1.0,
        width: float | None = None,
        opacity: float = 1.0,
        **kwargs,
    ):
        png_path = str(png_path)
        with Image.open(png_path) as image:
            aspect = image.width / max(image.height, 1)
        if width is None and height is None:
            height = 1.0
        if width is None:
            width = float(height) * aspect
        if height is None:
            height = float(width) / aspect
        w, h = float(width), float(height)
        surface = OpenGLSurface(
            lambda u, v: np.array([u, v, 0.0]),
            [-w / 2, w / 2],
            [-h / 2, h / 2],
            resolution=(2, 2),
            gloss=0,
            shadow=0,
            depth_test=False,
        )
        super().__init__(
            surface,
            png_path,
            resolution=(2, 2),
            depth_test=False,
            gloss=0,
            shadow=0,
            **kwargs,
        )
        self.texture_paths.pop("DarkTexture", None)
        self.init_colors()
        self.set_opacity(opacity)

    def init_colors(self):
        self.opacity = np.ones((len(self.im_coords), 1), dtype=np.float32)
        return self

    def get_image_from_file(self, image_file, image_mode):
        return str(image_file)


def _copy_rgbas(mobject) -> np.ndarray:
    return _rgba_array(mobject).copy()


def _set_rgbas(mobject, values: np.ndarray) -> None:
    rgbas = _rgba_array(mobject)
    if rgbas.size:
        rgbas[:] = values


class Reveal(Animation):
    """Fade shader RGBAs in place, without copying a mesh or its family."""

    def __init__(self, mobject, target_opacity: float | None = None, **kwargs):
        self.target_opacity = target_opacity
        super().__init__(mobject, introducer=True, **kwargs)

    def begin(self):
        self.initial_rgbas = _copy_rgbas(self.mobject)
        if self.target_opacity is None:
            self.final_opacity = (
                float(np.max(self.initial_rgbas[:, 3]))
                if self.initial_rgbas.size
                else 1.0
            )
        else:
            self.final_opacity = float(self.target_opacity)
        self.final_rgbas = self.initial_rgbas.copy()
        if self.final_rgbas.size:
            self.final_rgbas[:, 3] = self.final_opacity
        self.interpolate_mobject(0.0)

    def interpolate_mobject(self, alpha: float):
        if not self.initial_rgbas.size:
            return
        values = self.initial_rgbas.copy()
        values[:, 3] = 0.0
        values[:, 3] += alpha * self.final_opacity
        values[:, :3] = self.final_rgbas[:, :3]
        _set_rgbas(self.mobject, values)
        stored = getattr(self.mobject, "opacity", None)
        if isinstance(stored, np.ndarray) and stored.size:
            stored[:] = alpha * self.final_opacity


class Tint(Animation):
    """Interpolate mesh colour and opacity directly in its shader data."""

    def __init__(self, mobject, color: Any, opacity: float, **kwargs):
        self.target_color = _rgb(color)
        self.target_opacity = float(opacity)
        super().__init__(mobject, **kwargs)

    def begin(self):
        self.initial_rgbas = _copy_rgbas(self.mobject)
        self.final_rgbas = self.initial_rgbas.copy()
        if self.final_rgbas.size:
            self.final_rgbas[:, :3] = self.target_color
            self.final_rgbas[:, 3] = self.target_opacity
        self.interpolate_mobject(0.0)

    def interpolate_mobject(self, alpha: float):
        if self.initial_rgbas.size:
            _set_rgbas(
                self.mobject,
                (1.0 - alpha) * self.initial_rgbas + alpha * self.final_rgbas,
            )
        stored = getattr(self.mobject, "opacity", None)
        if isinstance(stored, np.ndarray) and stored.size:
            start = (
                float(np.max(self.initial_rgbas[:, 3]))
                if self.initial_rgbas.size
                else 1.0
            )
            stored[:] = start + alpha * (self.target_opacity - start)


class ShiftFade(Animation):
    """Translate mesh points and fade their RGBAs without a deepcopy."""

    def __init__(
        self,
        mobject,
        shift_vec: Sequence[float],
        target_opacity: float | None = None,
        **kwargs,
    ):
        self.shift_vec = np.asarray(shift_vec, dtype=float)
        self.target_opacity = target_opacity
        super().__init__(mobject, **kwargs)

    def begin(self):
        self.initial_points = np.asarray(self.mobject.points).copy()
        self.initial_rgbas = _copy_rgbas(self.mobject)
        self.initial_opacity = (
            float(np.max(self.initial_rgbas[:, 3]))
            if self.initial_rgbas.size
            else 1.0
        )
        self.final_opacity = (
            self.initial_opacity
            if self.target_opacity is None
            else float(self.target_opacity)
        )
        self.interpolate_mobject(0.0)

    def interpolate_mobject(self, alpha: float):
        self.mobject.points = self.initial_points + alpha * self.shift_vec
        if self.initial_rgbas.size:
            values = self.initial_rgbas.copy()
            values[:, 3] = self.initial_opacity + alpha * (
                self.final_opacity - self.initial_opacity
            )
            _set_rgbas(self.mobject, values)
        stored = getattr(self.mobject, "opacity", None)
        if isinstance(stored, np.ndarray) and stored.size:
            stored[:] = self.initial_opacity + alpha * (
                self.final_opacity - self.initial_opacity
            )


class SlideAlong(Animation):
    """Repeatedly and smoothly slide a mesh between two world-space points."""

    def __init__(
        self,
        mobject,
        start: Sequence[float],
        end: Sequence[float],
        phase: float = 0.0,
        cycles: float = 2.0,
        **kwargs,
    ):
        self.start = np.asarray(start, dtype=float)
        self.end = np.asarray(end, dtype=float)
        self.phase = float(phase)
        self.cycles = float(cycles)
        super().__init__(mobject, **kwargs)

    def begin(self):
        self.initial_points = np.asarray(self.mobject.points).copy()
        self.interpolate_mobject(0.0)

    def interpolate_mobject(self, alpha: float):
        theta = 2.0 * np.pi * (self.phase + self.cycles * alpha)
        amount = 0.5 * (1.0 - np.cos(theta))
        self.mobject.points = self.initial_points + amount * (self.end - self.start)


def make_arrow_mesh(
    s: Sequence[float],
    e: Sequence[float],
    color: Any = BLUE_3B1B,
    radius: float = 0.032,
    head_radius: float = 0.090,
    head_length: float = 0.26,
    sides: int = 12,
    opacity: float = 1.0,
) -> TriMesh:
    """Build a shaft-and-cone 3D arrow as one inexpensive triangle mesh."""
    start = np.asarray(s, dtype=float)
    end = np.asarray(e, dtype=float)
    direction = _unit(end - start)
    length = float(np.linalg.norm(end - start))
    sides = max(6, int(sides))
    head_length = min(max(head_length, 0.03), max(length * 0.65, 0.03))
    shaft_end = end - direction * head_length

    reference = (
        np.array([0.0, 1.0, 0.0])
        if abs(direction[2]) > 0.9
        else np.array([0.0, 0.0, 1.0])
    )
    basis_one = _unit(np.cross(direction, reference), (1.0, 0.0, 0.0))
    basis_two = _unit(np.cross(direction, basis_one), (0.0, 1.0, 0.0))

    vertices: list[np.ndarray] = []
    normals: list[np.ndarray] = []

    def triangle(a, b, c, na, nb, nc):
        vertices.extend((a, b, c))
        normals.extend((_unit(na), _unit(nb), _unit(nc)))

    for index in range(sides):
        angle_a = 2.0 * np.pi * index / sides
        angle_b = 2.0 * np.pi * (index + 1) / sides
        radial_a = math.cos(angle_a) * basis_one + math.sin(angle_a) * basis_two
        radial_b = math.cos(angle_b) * basis_one + math.sin(angle_b) * basis_two
        a = start + radius * radial_a
        b = start + radius * radial_b
        c = shaft_end + radius * radial_b
        d = shaft_end + radius * radial_a
        triangle(a, b, c, radial_a, radial_b, radial_b)
        triangle(a, c, d, radial_a, radial_b, radial_a)

        cone_a = shaft_end + head_radius * radial_a
        cone_b = shaft_end + head_radius * radial_b
        slope = head_radius / max(head_length, 1e-8)
        cone_normal_a = _unit(radial_a + slope * direction)
        cone_normal_b = _unit(radial_b + slope * direction)
        triangle(cone_a, cone_b, end, cone_normal_a, cone_normal_b, direction)

        # End caps prevent distracting holes during close camera moves.
        triangle(start, b, a, -direction, -direction, -direction)
        triangle(shaft_end, cone_a, cone_b, -direction, -direction, -direction)

    return TriMesh(
        np.asarray(vertices),
        np.asarray(normals),
        color=color,
        opacity=opacity,
        gloss=0.35,
        shadow=0.12,
    )


def make_sphere_mesh(
    center: Sequence[float],
    radius: float,
    color: Any = YELLOW_3B1B,
    resolution: int = 12,
    rings: int = 8,
    opacity: float = 1.0,
) -> TriMesh:
    """Build a smooth UV sphere without Dot3D's per-mobject overhead."""
    center = np.asarray(center, dtype=float)
    resolution = max(6, int(resolution))
    rings = max(4, int(rings))
    radius = max(float(radius), 1e-5)

    def point(phi: float, theta: float) -> np.ndarray:
        normal = np.array(
            [
                math.sin(phi) * math.cos(theta),
                math.sin(phi) * math.sin(theta),
                math.cos(phi),
            ]
        )
        return center + radius * normal

    vertices: list[np.ndarray] = []
    normals: list[np.ndarray] = []

    def triangle(a, b, c):
        na, nb, nc = (a - center) / radius, (b - center) / radius, (c - center) / radius
        if np.linalg.norm(np.cross(b - a, c - a)) < 1e-14:
            return
        vertices.extend((a, b, c))
        normals.extend((_unit(na), _unit(nb), _unit(nc)))

    for ring in range(rings):
        phi_a = np.pi * ring / rings
        phi_b = np.pi * (ring + 1) / rings
        for segment in range(resolution):
            theta_a = 2.0 * np.pi * segment / resolution
            theta_b = 2.0 * np.pi * (segment + 1) / resolution
            a = point(phi_a, theta_a)
            b = point(phi_b, theta_a)
            c = point(phi_b, theta_b)
            d = point(phi_a, theta_b)
            triangle(a, b, c)
            triangle(a, c, d)

    return TriMesh(
        np.asarray(vertices),
        np.asarray(normals),
        color=color,
        opacity=opacity,
        gloss=0.55,
        shadow=0.08,
    )


def fix(*mobs):
    """Recursively pin mobjects to the OpenGL camera frame."""
    for mobject in mobs:
        if mobject is None:
            continue
        try:
            family = mobject.get_family()
        except (AttributeError, TypeError):
            family = (mobject,)
        for member in family:
            fix_in_frame = getattr(member, "fix_in_frame", None)
            if callable(fix_in_frame):
                fix_in_frame()
    if len(mobs) == 1:
        return mobs[0]
    return mobs


@functools.lru_cache(maxsize=128)
def _font_path(bold: bool, italic: bool) -> str | None:
    style = "Regular"
    if bold and italic:
        style = "Bold Italic"
    elif bold:
        style = "Bold"
    elif italic:
        style = "Italic"

    for family in ("CMU Serif", "Liberation Serif", "DejaVu Serif"):
        try:
            result = subprocess.run(
                ["fc-match", "-f", "%{file}", f"{family}:style={style}"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            candidate = result.stdout.strip()
            if result.returncode == 0 and candidate and Path(candidate).is_file():
                return candidate
        except (OSError, subprocess.SubprocessError):
            pass

    suffix = {
        "Regular": "DejaVuSerif.ttf",
        "Bold": "DejaVuSerif-Bold.ttf",
        "Italic": "DejaVuSerif-Italic.ttf",
        "Bold Italic": "DejaVuSerif-BoldItalic.ttf",
    }[style]
    candidates: list[Path] = [
        Path("/usr/share/fonts/truetype/dejavu") / suffix,
        Path("/usr/share/fonts/dejavu") / suffix,
    ]
    try:
        import matplotlib

        candidates.append(Path(matplotlib.get_data_path()) / "fonts" / "ttf" / suffix)
    except Exception:
        pass
    if os.name == "nt":
        win_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        win_fallbacks = {
            "Regular": ("georgia.ttf", "times.ttf"),
            "Bold": ("georgiab.ttf", "timesbd.ttf"),
            "Italic": ("georgiai.ttf", "timesi.ttf"),
            "Bold Italic": ("georgiaz.ttf", "timesbi.ttf"),
        }[style]
        candidates.extend(win_fonts / name for name in win_fallbacks)
    elif sys.platform == "darwin":
        mac_fallbacks = {
            "Regular": ("Georgia.ttf", "Times New Roman.ttf"),
            "Bold": ("Georgia Bold.ttf", "Times New Roman Bold.ttf"),
            "Italic": ("Georgia Italic.ttf", "Times New Roman Italic.ttf"),
            "Bold Italic": ("Georgia Bold Italic.ttf", "Times New Roman Bold Italic.ttf"),
        }[style]
        for base in (Path("/System/Library/Fonts/Supplemental"), Path("/Library/Fonts")):
            candidates.extend(base / name for name in mac_fallbacks)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def serif_text(
    text: str,
    color: str = WHITE_3B1B,
    height: float = 0.28,
    bold: bool = False,
    italic: bool = False,
    max_width: float | None = None,
    align: str = "center",
) -> FlatImage:
    """Rasterise crisp, transparent serif text, including multi-line strings."""
    text = str(text)
    align = align.lower()
    if align not in {"left", "center", "right"}:
        align = "center"

    cache_dir = Path(config.media_dir) / "opto_svg"
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = "\0".join((text, color, str(bold), str(italic), align))
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    png_path = cache_dir / f"serif_{digest}.png"

    if not png_path.exists():
        pixel_size = 256
        font_path = _font_path(bold, italic)
        try:
            font = (
                ImageFont.truetype(font_path, pixel_size)
                if font_path
                else ImageFont.truetype("DejaVuSerif.ttf", pixel_size)
            )
        except (OSError, ValueError):
            font = ImageFont.load_default()

        rendered_text = text if text else " "
        probe = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        draw = ImageDraw.Draw(probe)
        spacing = int(pixel_size * 0.20)
        bbox = draw.multiline_textbbox(
            (0, 0),
            rendered_text,
            font=font,
            spacing=spacing,
            align=align,
        )
        padding = 12
        width = max(1, bbox[2] - bbox[0] + 2 * padding)
        image_height = max(1, bbox[3] - bbox[1] + 2 * padding)
        image = Image.new("RGBA", (width, image_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        rgba = tuple(int(round(255.0 * channel)) for channel in _rgb(color)) + (255,)
        draw.multiline_text(
            (padding - bbox[0], padding - bbox[1]),
            rendered_text,
            font=font,
            fill=rgba,
            spacing=spacing,
            align=align,
        )
        image.save(png_path)

    result = FlatImage(png_path, height=height)
    if max_width is not None and result.width > max_width and result.width > 1e-9:
        result.scale(max_width / result.width)
    fix(result)
    return result


def math_tex(
    tex: str,
    color: str = WHITE_3B1B,
    height: float = 0.65,
    max_width: float = 5.6,
):
    """Compile Computer Modern mathtext to a cached, OpenGL-writable SVG."""
    cache_dir = Path(config.media_dir) / "opto_svg"
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(str(tex).encode("utf-8")).hexdigest()[:24]
    svg_path = cache_dir / f"math_{digest}.svg"

    try:
        if not svg_path.exists():
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            plt.rcParams["mathtext.fontset"] = "cm"
            plt.rcParams["svg.fonttype"] = "path"
            figure = plt.figure()
            try:
                figure.patch.set_visible(False)
                source = str(tex)
                if not (source.startswith("$") and source.endswith("$")):
                    source = f"${source}$"
                figure.text(0, 0, source, fontsize=42)
                figure.savefig(
                    svg_path,
                    format="svg",
                    transparent=True,
                    bbox_inches="tight",
                    pad_inches=0.04,
                )
            finally:
                plt.close(figure)

        # Matplotlib's transparent figure patch otherwise becomes a black box.
        source = svg_path.read_text(encoding="utf-8")
        source = re.sub(r'<g id="patch_1">.*?</g>', "", source, flags=re.S)
        svg_path.write_text(source, encoding="utf-8")

        mobject = SVGMobject(str(svg_path))
        if mobject.height > 1e-9:
            mobject.scale(height / mobject.height)
        if mobject.width > max_width and mobject.width > 1e-9:
            mobject.scale(max_width / mobject.width)
        mobject.set_fill(color, opacity=1.0).set_stroke(color, width=0.22)
        fix(mobject)
        return mobject
    except Exception:
        # Malformed TeX should degrade into legible text, never abort a render.
        return serif_text(
            tex,
            color=color,
            height=min(height, 0.36),
            max_width=max_width,
        )


def open_curve(
    pts: Sequence[Sequence[float]],
    color: Any = BLUE_3B1B,
    stroke_width: float = 3.0,
    smooth: bool = True,
) -> OpenGLVMobject:
    arr = np.asarray(pts, dtype=float)
    if arr.ndim == 2 and arr.shape[1] == 2:
        arr = np.column_stack([arr, np.zeros(len(arr), dtype=float)])
    points = arr.reshape(-1, 3)
    curve = OpenGLVMobject()
    if smooth:
        curve.set_points_smoothly(points)
    else:
        curve.set_points_as_corners(points)
    curve.set_stroke(color, width=stroke_width)
    curve.set_fill(opacity=0.0)
    fix(curve)
    return curve


def _part_specs(scene_data: dict[str, Any]) -> list[dict[str, Any]]:
    parts = scene_data.get("parts", scene_data.get("objects", []))
    if isinstance(parts, dict):
        result = []
        for part_id, value in parts.items():
            spec = dict(value) if isinstance(value, dict) else {}
            spec.setdefault("id", str(part_id))
            result.append(spec)
        return result
    result = []
    for index, value in enumerate(parts if isinstance(parts, list) else []):
        spec = dict(value) if isinstance(value, dict) else {"name": str(value)}
        spec.setdefault("id", str(spec.get("part_id", f"part_{index}")))
        result.append(spec)
    return result


def _candidate_mesh_keys(part_id: str, index: int, spec: dict[str, Any]) -> list[str]:
    prefixes = [part_id, str(index), f"part_{index}"]
    sanitised = re.sub(r"[^A-Za-z0-9_]+", "_", part_id).strip("_")
    if sanitised and sanitised not in prefixes:
        prefixes.append(sanitised)
    explicit = spec.get("mesh_key", spec.get("npz_key"))
    if explicit:
        prefixes.insert(0, str(explicit))

    keys = []
    for prefix in prefixes:
        keys.extend(
            [
                f"{prefix}_vertices",
                f"{prefix}__vertices",
                f"{prefix}/vertices",
                f"{prefix}.vertices",
                f"vertices_{prefix}",
                f"vertices__{prefix}",
                f"mesh_{prefix}_vertices",
                f"{prefix}_verts",
            ]
        )
    return list(dict.fromkeys(keys))


def _matching_array(
    arrays,
    vertex_key: str,
    kinds: Sequence[str],
) -> np.ndarray | None:
    for kind in kinds:
        candidates = [
            vertex_key.replace("vertices", kind),
            vertex_key.replace("verts", kind),
        ]
        for candidate in candidates:
            if candidate in arrays:
                return np.asarray(arrays[candidate])
    return None


def _load_part_arrays(
    arrays,
    spec: dict[str, Any],
    index: int,
):
    part_id = str(spec["id"])
    tris_key = f"{part_id}__tris"
    if tris_key in arrays:
        tris = np.asarray(arrays[tris_key], dtype=float).reshape(-1, 3, 3)
        nrm_key = f"{part_id}__nrm"
        normals = np.asarray(arrays[nrm_key], dtype=float).reshape(-1, 3) if nrm_key in arrays else None
        col_key = f"{part_id}__color"
        if col_key in arrays and "color" not in spec:
            rgba = np.asarray(arrays[col_key], dtype=float).reshape(-1)
            if len(rgba) >= 3:
                spec["color"] = "#{:02x}{:02x}{:02x}".format(*(int(round(np.clip(c, 0, 1) * 255)) for c in rgba[:3]))
            if len(rgba) >= 4 and "opacity" not in spec:
                spec["opacity"] = float(np.clip(rgba[3], 0.12, 1.0))
        good = np.isfinite(tris).all(axis=(1, 2))
        if normals is not None and len(normals) == len(tris) * 3:
            good &= np.isfinite(normals).reshape(-1, 3, 3).all(axis=(1, 2))
            normals = normals.reshape(-1, 3, 3)[good].reshape(-1, 3)
        else:
            normals = None
        tris = tris[good]
        if not len(tris):
            return None
        vertices = tris.reshape(-1, 3)
        faces = np.arange(len(vertices), dtype=int).reshape(-1, 3)
        return vertices, faces, normals
    for vertex_key in _candidate_mesh_keys(part_id, index, spec):
        if vertex_key not in arrays:
            continue
        vertices = np.asarray(arrays[vertex_key], dtype=float)
        faces = _matching_array(arrays, vertex_key, ("faces", "triangles", "indices"))
        normals = _matching_array(arrays, vertex_key, ("normals",))
        if vertices.ndim == 3 and vertices.shape[-2:] == (3, 3):
            vertices = vertices.reshape(-1, 3)
            faces = np.arange(len(vertices), dtype=int).reshape(-1, 3)
        if faces is None and len(vertices) % 3 == 0:
            faces = np.arange(len(vertices), dtype=int).reshape(-1, 3)
        if faces is not None:
            return vertices, np.asarray(faces, dtype=int).reshape(-1, 3), normals

    if "vertices" not in arrays:
        return None
    vertices = np.asarray(arrays["vertices"], dtype=float)
    face_key = next(
        (key for key in ("faces", "triangles", "indices") if key in arrays),
        None,
    )
    if face_key is None:
        return None
    faces = np.asarray(arrays[face_key], dtype=int).reshape(-1, 3)
    normals = np.asarray(arrays["normals"], dtype=float) if "normals" in arrays else None

    assignment_key = next(
        (
            key
            for key in (
                "face_parts",
                "face_part_ids",
                "part_ids",
                "part_indices",
                "face_part",
            )
            if key in arrays
        ),
        None,
    )
    if assignment_key is not None:
        assignments = np.asarray(arrays[assignment_key]).reshape(-1)
        if len(assignments) == len(faces):
            if assignments.dtype.kind in {"U", "S", "O"}:
                mask = np.array(
                    [str(value) in {part_id, str(index)} for value in assignments]
                )
            else:
                mask = assignments.astype(int) == index
            faces = faces[mask]
            if normals is not None and len(normals) == len(mask):
                normals = normals[mask]
    elif "face_start" in spec and "face_count" in spec:
        start = int(spec["face_start"])
        faces = faces[start : start + int(spec["face_count"])]
    elif len(_part_specs_cache_hint(arrays)) > 1:
        return None

    return vertices, faces, normals


def _part_specs_cache_hint(arrays) -> list[str]:
    metadata = arrays.get("part_names") if hasattr(arrays, "get") else None
    if metadata is not None:
        return [str(value) for value in np.asarray(metadata).reshape(-1)]
    return [""]


def _world_matrix(spec: dict[str, Any]) -> np.ndarray:
    matrix_value = next(
        (
            spec[key]
            for key in ("world", "matrix", "transform", "world_matrix")
            if key in spec
        ),
        None,
    )
    if matrix_value is None:
        return np.eye(4)
    matrix = np.asarray(matrix_value, dtype=float)
    if matrix.size != 16:
        return np.eye(4)
    return matrix.reshape(4, 4)


def _unit_rows(arr: np.ndarray) -> np.ndarray:
    ln = np.linalg.norm(arr, axis=-1, keepdims=True)
    return np.where(ln > 1e-12, arr / np.maximum(ln, 1e-12), np.array([0.0, 0.0, 1.0]))


def _face_and_vertex_normals(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    triangles = vertices[faces]
    face_normals = np.cross(
        triangles[:, 1] - triangles[:, 0],
        triangles[:, 2] - triangles[:, 0],
    )
    vertex_normals = np.zeros_like(vertices, dtype=float)
    np.add.at(vertex_normals, faces[:, 0], face_normals)
    np.add.at(vertex_normals, faces[:, 1], face_normals)
    np.add.at(vertex_normals, faces[:, 2], face_normals)
    return _unit_rows(vertex_normals)


def _prepare_raw_part(
    vertices: np.ndarray,
    faces: np.ndarray,
    normals: np.ndarray | None,
    spec: dict[str, Any],
):
    vertices = np.asarray(vertices, dtype=float).reshape(-1, 3)
    faces = np.asarray(faces, dtype=int).reshape(-1, 3)
    if not len(vertices) or not len(faces):
        return None
    valid = np.all((faces >= 0) & (faces < len(vertices)), axis=1)
    faces = faces[valid]
    if not len(faces):
        return None

    if normals is None:
        normals = _face_and_vertex_normals(vertices, faces)
    else:
        normals = np.asarray(normals, dtype=float)
        if normals.shape == faces.shape:
            expanded = np.zeros((len(vertices), 3), dtype=float)
            counts = np.zeros((len(vertices), 1), dtype=float)
            for corner in range(3):
                np.add.at(expanded, faces[:, corner], normals[:, corner])
                np.add.at(counts, faces[:, corner], 1)
            normals = expanded / np.maximum(counts, 1)
        elif normals.size == faces.size:
            normals = normals.reshape(faces.shape)
            vertex_normals = _face_and_vertex_normals(vertices, faces)
            normals = vertex_normals
        if normals.shape != vertices.shape:
            normals = _face_and_vertex_normals(vertices, faces)
        normals = _unit_rows(normals)

    matrix = _world_matrix(spec)
    linear = matrix[:3, :3]
    world_vertices = vertices @ linear.T + matrix[:3, 3]
    try:
        normal_linear = np.linalg.inv(linear).T
    except np.linalg.LinAlgError:
        normal_linear = linear
    world_normals = normals @ normal_linear.T

    world_vertices = world_vertices @ _GLTF_TO_MANIM.T
    world_normals = _unit_rows(world_normals @ _GLTF_TO_MANIM.T)

    triangles = world_vertices[faces]
    tri_normals = world_normals[faces]
    lengths = np.cross(
        triangles[:, 1] - triangles[:, 0],
        triangles[:, 2] - triangles[:, 0],
    )
    nondegenerate = np.linalg.norm(lengths, axis=1) > 1e-12
    triangles = triangles[nondegenerate]
    tri_normals = tri_normals[nondegenerate]
    if not len(triangles):
        return None

    # Duplicate faces can occur where exporters repeat shared submeshes.
    keys = np.sort(np.round(triangles, decimals=7), axis=1).reshape(len(triangles), -1)
    _, unique_indices = np.unique(keys, axis=0, return_index=True)
    unique_indices.sort()
    return triangles[unique_indices], tri_normals[unique_indices]


def _decimation_quotas(counts: Sequence[int], budget: int) -> list[int]:
    counts = list(counts)
    total = sum(counts)
    if total <= budget:
        return counts
    quotas = [max(1, min(count, int(round(count * budget / total)))) for count in counts]
    while sum(quotas) > budget:
        candidates = [index for index, quota in enumerate(quotas) if quota > 1]
        if not candidates:
            break
        largest = max(candidates, key=lambda index: quotas[index])
        quotas[largest] -= 1
    while sum(quotas) < budget:
        candidates = [
            index for index, quota in enumerate(quotas) if quota < counts[index]
        ]
        if not candidates:
            break
        index = max(candidates, key=lambda item: counts[item] - quotas[item])
        quotas[index] += 1
    return quotas


def _even_decimation(
    triangles: np.ndarray,
    normals: np.ndarray,
    count: int,
):
    count = max(1, min(len(triangles), int(count)))
    if count == len(triangles):
        return triangles, normals
    indices = np.unique(np.linspace(0, len(triangles) - 1, count).round().astype(int))
    if not len(indices):
        indices = np.array([0])
    return triangles[indices], normals[indices]


def _axis_index(value: Any, default: int = 0) -> int:
    if isinstance(value, str):
        return {"x": 0, "y": 1, "z": 2}.get(value.lower(), default)
    try:
        return int(value) % 3
    except (TypeError, ValueError):
        return default


class ForgeModel:
    """Loaded Forge geometry plus camera staging and high-level animations."""

    def __init__(
        self,
        scene: ThreeDScene,
        forge_dir: str | Path | None = None,
        total_tri_budget: int = 38_000,
    ):
        if forge_dir is None:
            forge_dir = os.environ["OPTO_SCENE_DIR"]
        self.scene = scene
        self.forge_dir = Path(forge_dir).expanduser().resolve()
        self.scene_data = json.loads(
            (self.forge_dir / "scene.json").read_text(encoding="utf-8")
        )
        self.mesh_path = self.forge_dir / "mesh.npz"
        self.title = str(self.scene_data.get("title", self.scene_data.get("name", "")))
        self.subtitle = str(self.scene_data.get("subtitle", ""))
        self.beats = self.scene_data.get("beats", [])
        cut_cfg = self.scene_data.get("cut") if isinstance(self.scene_data.get("cut"), dict) else {}
        gltf_axis = str(cut_cfg.get("axis", self.scene_data.get("cut_axis", "z"))).lower()
        gltf_keep = str(cut_cfg.get("keep", "neg")).lower()
        # glTF (x, y, z) -> Manim (x, -z, y): x->0, y->2, z->1 (flipped sign)
        axis_map = {"x": (0, 1.0), "y": (2, 1.0), "z": (1, -1.0)}
        self.cut_axis, flip = axis_map.get(gltf_axis, (1, -1.0))
        self.cut_side = (1.0 if gltf_keep == "neg" else -1.0) * flip

        specs = _part_specs(self.scene_data)
        raw_parts: list[dict[str, Any]] = []
        with np.load(self.mesh_path, allow_pickle=False) as arrays:
            if not specs:
                specs = self._infer_specs(arrays)
            for index, spec in enumerate(specs):
                loaded = _load_part_arrays(arrays, spec, index)
                if loaded is None:
                    continue
                vertices, faces, normals = loaded
                prepared = _prepare_raw_part(vertices, faces, normals, spec)
                if prepared is None:
                    continue
                triangles, tri_normals = prepared
                if len(triangles) == 0:
                    continue
                raw_parts.append(
                    {
                        "spec": spec,
                        "triangles": triangles,
                        "normals": tri_normals,
                    }
                )

        if not raw_parts:
            raise ValueError(f"No non-empty mesh parts found in {self.mesh_path}")

        all_vertices = np.concatenate(
            [part["triangles"].reshape(-1, 3) for part in raw_parts], axis=0
        )
        raw_lo = all_vertices.min(axis=0)
        raw_hi = all_vertices.max(axis=0)
        self._model_center = 0.5 * (raw_lo + raw_hi)
        half_extent = 0.5 * (raw_hi - raw_lo)
        self._model_scale = 3.8 / max(float(half_extent.max()), 1e-9)

        quotas = _decimation_quotas(
            [len(part["triangles"]) for part in raw_parts],
            max(1, int(total_tri_budget)),
        )
        palette = [BLUE_3B1B, TEAL_3B1B, GOLD_3B1B, MAROON_3B1B, GREEN_3B1B, PURPLE_3B1B]
        self.parts: dict[str, dict[str, Any]] = {}
        self.part_ids: list[str] = []
        self.part_names: dict[str, str] = {}
        self.internal_ids: list[str] = []
        prepared_parts = []

        cut_position_value = self.scene_data.get(
            "cut_position", self.scene_data.get("split_position")
        )
        if cut_position_value is None:
            cut_position = float(self._model_center[self.cut_axis])
        elif isinstance(cut_position_value, (int, float)):
            numeric = float(cut_position_value)
            if 0.0 <= numeric <= 1.0 and "cut_fraction" not in self.scene_data:
                # Absolute zero is common; fractional values are accepted too.
                if numeric == 0.0:
                    cut_position = float(self._model_center[self.cut_axis])
                else:
                    cut_position = float(
                        raw_lo[self.cut_axis]
                        + numeric * (raw_hi[self.cut_axis] - raw_lo[self.cut_axis])
                    )
            else:
                raw_point = self._model_center.copy()
                raw_point[self.cut_axis] = numeric
                cut_position = self._scale_point(raw_point)[self.cut_axis]
        else:
            cut_position = float(self._model_center[self.cut_axis])
        if not isinstance(cut_position_value, (int, float)) or (
            isinstance(cut_position_value, (int, float))
            and not (0.0 < cut_position_value <= 1.0)
            and cut_position_value != 0.0
        ):
            # Absolute raw coordinates need the same centre and scale as vertices.
            if isinstance(cut_position_value, (int, float)) and cut_position_value != 0.0:
                cut_position = float(
                    (cut_position_value - self._model_center[self.cut_axis])
                    * self._model_scale
                )
        elif cut_position_value == 0.0:
            cut_position = float(self._model_center[self.cut_axis])
        else:
            cut_position = float(
                (
                    raw_lo[self.cut_axis]
                    + float(cut_position_value)
                    * (raw_hi[self.cut_axis] - raw_lo[self.cut_axis])
                    - self._model_center[self.cut_axis]
                )
                * self._model_scale
            )
        self.cut_position = cut_position

        for index, (raw_part, quota) in enumerate(zip(raw_parts, quotas)):
            spec = raw_part["spec"]
            part_id = str(spec["id"])
            triangles, normals = _even_decimation(
                raw_part["triangles"], raw_part["normals"], quota
            )
            triangles = (triangles - self._model_center) * self._model_scale
            name = str(spec.get("name", spec.get("label", part_id)))
            internal = bool(
                spec.get("internal", False)
                or str(spec.get("kind", "")).lower() in {"internal", "inside", "inner"}
            )
            color = spec.get("color", palette[index % len(palette)])
            opacity = float(spec.get("opacity", 0.96))

            centroids = triangles.mean(axis=1)
            cut_mask = self.cut_side * centroids[:, self.cut_axis] > self.cut_side * cut_position
            keep_mask = ~cut_mask
            keep = self._make_mesh(
                part_id,
                triangles[keep_mask],
                normals[keep_mask],
                color,
                opacity,
            )
            cut = self._make_mesh(
                part_id,
                triangles[cut_mask],
                normals[cut_mask],
                color,
                opacity,
            )

            raw_anchor = spec.get("anchor", spec.get("surface_anchor"))
            if raw_anchor is not None:
                gltf_anchor = np.asarray(raw_anchor, dtype=float).reshape(3)
                anchor = self._scale_point(gltf_anchor @ _GLTF_TO_MANIM.T)
            else:
                surface = triangles.reshape(-1, 3)
                centre = surface.mean(axis=0)
                anchor = surface[np.argmin(np.linalg.norm(surface - centre, axis=1))].copy()

            entry = {
                "id": part_id,
                "name": name,
                "internal": internal,
                "spec": spec,
                "keep": keep,
                "cut": cut,
                "meshes": [mesh for mesh in (keep, cut) if mesh is not None],
                "triangles": triangles,
                "normals": normals,
                "color": color,
                "opacity": opacity,
                "anchor": anchor,
            }
            self.parts[part_id] = entry
            self.part_ids.append(part_id)
            self.part_names[part_id] = name
            if internal:
                self.internal_ids.append(part_id)
            prepared_parts.append(entry)

        scaled_vertices = np.concatenate(
            [entry["triangles"].reshape(-1, 3) for entry in prepared_parts], axis=0
        )
        self.lo = scaled_vertices.min(axis=0)
        self.hi = scaled_vertices.max(axis=0)
        self.center = 0.5 * (self.lo + self.hi)
        self.wireframe = self._make_wireframe(prepared_parts)
        self.grid = self._make_grid()
        self.arrows = self._convert_arrows(self.scene_data.get("arrows", []))
        self.labels = self._convert_labels(self.scene_data.get("labels", []))

        self.split_x = ValueTracker(0.0)
        self.split_y = ValueTracker(0.18)
        self._center_zoom = float(self.scene_data.get("center_zoom", 0.82))
        self._split_zoom = float(self.scene_data.get("split_zoom", 0.56))
        self._flow_objects: list[TriMesh] = []
        self._flow_group: Group | None = None
        self._cut_done: bool = False
        self._install_camera_pin()

    @staticmethod
    def _infer_specs(arrays) -> list[dict[str, Any]]:
        specs = []
        for key in arrays.files:
            match = re.match(r"(.+?)(?:__|[_/\.])vertices$", key)
            if match and match.group(1) not in {"mesh", "all"}:
                part_id = match.group(1)
                specs.append({"id": part_id, "name": part_id.replace("_", " ").title()})
        if not specs and "vertices" in arrays:
            specs.append({"id": "model", "name": "Model"})
        return specs

    def _scale_point(self, point: Sequence[float]) -> np.ndarray:
        return (np.asarray(point, dtype=float).reshape(3) - self._model_center) * self._model_scale

    def _make_mesh(self, part_id, triangles, normals, color, opacity):
        if triangles is None or len(triangles) == 0:
            return None
        mesh = TriMesh(
            triangles.reshape(-1, 3),
            normals.reshape(-1, 3),
            color=color,
            opacity=opacity,
            gloss=0.24,
            shadow=0.14,
        )
        mesh._opto_part_id = part_id
        mesh._opto_base_color = _rgb(color)
        mesh._opto_base_opacity = opacity
        return mesh

    @property
    def meshes(self) -> list[TriMesh]:
        return [mesh for part in self.parts.values() for mesh in part["meshes"]]

    def _make_wireframe(self, entries: list[dict[str, Any]]) -> OpenGLVMobject:
        all_tris = np.concatenate([e["triangles"] for e in entries if len(e["triangles"])], axis=0)
        if not len(all_tris):
            wf = OpenGLVMobject()
            wf.set_fill(opacity=0.0).set_stroke(BLUE_3B1B, width=1.05, opacity=0.78)
            return wf
        fn = np.cross(all_tris[:, 1] - all_tris[:, 0], all_tris[:, 2] - all_tris[:, 0])
        ln = np.linalg.norm(fn, axis=1, keepdims=True)
        ok = ln[:, 0] > 1e-10
        all_tris, fn = all_tris[ok], fn[ok] / ln[ok]
        pts = all_tris.reshape(-1, 3)
        q = np.round(pts * 1000.0).astype(np.int64)
        _, vid = np.unique(q, axis=0, return_inverse=True)
        vid = vid.reshape(-1, 3)
        ea = np.concatenate([vid[:, 0], vid[:, 1], vid[:, 2]])
        eb = np.concatenate([vid[:, 1], vid[:, 2], vid[:, 0]])
        pa = np.concatenate([all_tris[:, 0], all_tris[:, 1], all_tris[:, 2]], axis=0)
        pb = np.concatenate([all_tris[:, 1], all_tris[:, 2], all_tris[:, 0]], axis=0)
        fi = np.tile(np.arange(len(all_tris)), 3)
        lo_v, hi_v = np.minimum(ea, eb), np.maximum(ea, eb)
        ekey = lo_v * (int(vid.max()) + 2) + hi_v
        order = np.argsort(ekey)
        ek_s, f_s = ekey[order], fi[order]
        # Vectorized run-length check: boundary (count==1) or sharp dihedral crease
        diff = np.empty(len(ek_s) + 1, dtype=bool)
        diff[0] = True
        diff[-1] = True
        diff[1:-1] = ek_s[1:] != ek_s[:-1]
        starts = np.flatnonzero(diff[:-1])
        counts = np.diff(np.flatnonzero(diff))
        cos_t = math.cos(math.radians(38.0))
        keep_mask = counts != 2
        pair_idx = np.flatnonzero(counts == 2)
        if len(pair_idx):
            s2 = starts[pair_idx]
            dots = np.abs(np.sum(fn[f_s[s2]] * fn[f_s[s2 + 1]], axis=1))
            keep_mask[pair_idx] = dots < cos_t
        chosen = order[starts[keep_mask]]
        segs = np.stack([pa[chosen], pb[chosen]], axis=1)
        lens = np.linalg.norm(segs[:, 1] - segs[:, 0], axis=1)
        segs = segs[lens > 1e-3]
        lens = lens[lens > 1e-3]
        if len(segs) > 1100:
            top = np.argpartition(lens, -1100)[-1100:]
            segs = segs[top]
        wf = OpenGLVMobject()
        if len(segs):
            p0, p1 = segs[:, 0, :], segs[:, 1, :]
            bpts = np.empty((len(segs) * 3, 3), dtype=float)
            bpts[0::3] = p0
            bpts[1::3] = 0.5 * (p0 + p1)
            bpts[2::3] = p1
            wf.set_points(bpts)
        wf.set_fill(opacity=0.0)
        wf.set_stroke(BLUE_3B1B, width=1.05, opacity=0.78)
        return wf

    def _make_grid(self) -> NumberPlane:
        grid = NumberPlane(
            x_range=(-6.0, 6.0, 0.75),
            y_range=(-6.0, 6.0, 0.75),
            background_line_style={
                "stroke_color": "#1e4566",
                "stroke_width": 1.15,
                "stroke_opacity": 0.58,
            },
            faded_line_ratio=2,
            axis_config={"stroke_color": "#3d8cc4", "stroke_width": 1.8, "stroke_opacity": 0.8},
        )
        grid.shift(np.array([0.0, 0.0, self.lo[2] - 0.25]))
        return grid

    def _convert_arrows(self, arrows: Any) -> list[dict[str, Any]]:
        if isinstance(arrows, dict):
            arrows = list(arrows.values())
        result = []
        for item in arrows if isinstance(arrows, list) else []:
            if isinstance(item, dict):
                start = item.get("start", item.get("from", item.get("s")))
                end = item.get("end", item.get("to", item.get("e")))
                if start is None or end is None:
                    continue
                converted = dict(item)
                color = item.get("color", BLUE_3B1B)
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                start, end = item[:2]
                converted = {}
                color = BLUE_3B1B
            else:
                continue
            try:
                start = np.asarray(start, dtype=float).reshape(3) @ _GLTF_TO_MANIM.T
                end = np.asarray(end, dtype=float).reshape(3) @ _GLTF_TO_MANIM.T
            except (TypeError, ValueError):
                continue
            converted.update(
                start=self._scale_point(start),
                end=self._scale_point(end),
                color=color,
            )
            result.append(converted)
        return result

    def _convert_labels(self, labels: Any) -> list[dict[str, Any]]:
        if isinstance(labels, dict):
            iterable = []
            for key, value in labels.items():
                if isinstance(value, dict):
                    item = dict(value)
                    item.setdefault("part_id", key)
                else:
                    item = {"part_id": key, "text": str(value)}
                iterable.append(item)
        else:
            iterable = labels if isinstance(labels, list) else []
        result = []
        for value in iterable:
            item = dict(value) if isinstance(value, dict) else {"text": str(value)}
            for key in ("position", "anchor", "point"):
                if key in item:
                    try:
                        point = np.asarray(item[key], dtype=float).reshape(3)
                        item[key] = self._scale_point(point @ _GLTF_TO_MANIM.T)
                    except (TypeError, ValueError):
                        pass
            result.append(item)
        return result

    def _install_camera_pin(self) -> None:
        camera = self.scene.camera

        def pin_camera(mobject, dt=0.0):
            rotation = np.asarray(camera.inverse_rotation_matrix)
            width, height = camera.get_shape()
            x = float(self.split_x.get_value())
            y = float(self.split_y.get_value())
            camera.move_to(
                rotation[0] * (x * width / config.frame_width)
                - rotation[1] * (y * height / config.frame_height)
            )

        self._camera_pin_updater = pin_camera
        self.scene.add_updater(lambda dt: pin_camera(camera, dt))

    def setup_camera(self, ambient_rate: float = 0.07):
        self.scene.set_camera_orientation(
            phi=68 * DEGREES,
            theta=-42 * DEGREES,
            zoom=self._center_zoom,
        )
        if ambient_rate:
            self.scene.begin_ambient_camera_rotation(rate=ambient_rate)
        self._camera_pin_updater(self.scene.camera, 0.0)
        return self

    def play_blueprint_intro(self, run_time: float = 3.4):
        initial_time = max(0.4, run_time * 0.43)
        reveal_time = max(0.4, run_time * 0.43)
        remaining = max(0.15, run_time - initial_time - reveal_time)
        self.scene.play(
            Create(self.grid),
            Create(self.wireframe),
            run_time=initial_time,
        )
        reveals = [Reveal(mesh) for mesh in self.meshes]
        if reveals:
            self.scene.play(
                LaggedStart(*reveals, lag_ratio=0.075),
                run_time=reveal_time,
            )
        self.scene.play(
            self.wireframe.animate.set_opacity(0.20),
            run_time=remaining,
        )
        return self

    def move_left_anims(self, split_x: float = 3.25):
        return [
            self.split_x.animate.set_value(split_x),
            self.split_y.animate.set_value(0.25),
            self.scene.camera.animate.set_zoom(self._split_zoom),
        ]

    def center_anims(self):
        return [
            self.split_x.animate.set_value(0.0),
            self.split_y.animate.set_value(0.18),
            self.scene.camera.animate.set_zoom(self._center_zoom),
        ]

    def focus_anims(self, highlight=None, dim_opacity: float = 0.18):
        if highlight is None:
            colours = {part_id: part["color"] for part_id, part in self.parts.items()}
            focused = set(self.part_ids)
            resetting = True
        elif isinstance(highlight, dict):
            colours = {str(key): value for key, value in highlight.items()}
            focused = set(colours)
            resetting = False
        else:
            focused = {str(value) for value in highlight}
            colours = {part_id: YELLOW_3B1B for part_id in focused}
            resetting = False

        animations = []
        for part_id, part in self.parts.items():
            for mesh in part["meshes"]:
                if self._cut_done and mesh is part.get("cut"):
                    continue
                if part_id in focused:
                    target_color = getattr(mesh, "_opto_base_color", _rgb(part["color"])) if resetting else colours.get(part_id, YELLOW_3B1B)
                    target_opacity = getattr(mesh, "_opto_base_opacity", part["opacity"])
                else:
                    target_color = _SLATE_BLUE
                    target_opacity = float(dim_opacity)
                animations.append(Tint(mesh, target_color, target_opacity))
        return animations

    def _cut_plane(self) -> tuple[TriMesh, np.ndarray]:
        axes = [index for index in range(3) if index != self.cut_axis]
        centre = self.center.copy()
        centre[self.cut_axis] = self.lo[self.cut_axis] - 0.45
        sizes = [max(1.0, self.hi[index] - self.lo[index] + 1.2) for index in axes]
        basis_a = np.zeros(3)
        basis_b = np.zeros(3)
        basis_a[axes[0]] = 0.5 * sizes[0]
        basis_b[axes[1]] = 0.5 * sizes[1]
        corners = np.array(
            [
                centre - basis_a - basis_b,
                centre + basis_a - basis_b,
                centre + basis_a + basis_b,
                centre - basis_a + basis_b,
            ]
        )
        triangles = np.array(
            [[corners[0], corners[1], corners[2]], [corners[0], corners[2], corners[3]]]
        )
        normal = np.zeros(3)
        normal[self.cut_axis] = 1.0
        normals = np.tile(normal, (2, 3, 1))
        plane = TriMesh(
            triangles.reshape(-1, 3),
            normals.reshape(-1, 3),
            color=BLUE_3B1B,
            opacity=0.0,
            gloss=0.1,
            shadow=0.0,
            depth_test=False,
        )
        sweep = np.zeros(3)
        sweep[self.cut_axis] = self.hi[self.cut_axis] - self.lo[self.cut_axis] + 0.9
        return plane, sweep

    def play_cutaway(self, focus=None):
        plane, sweep = self._cut_plane()
        self.scene.play(Reveal(plane, target_opacity=0.26), run_time=0.25)
        self.scene.play(plane.animate.shift(sweep), run_time=1.45)
        self.scene.play(ShiftFade(plane, np.zeros(3), target_opacity=0.0), run_time=0.22)
        self.scene.remove(plane)

        lift = np.zeros(3)
        lift[self.cut_axis] = self.cut_side * 1.65
        lift[2] += 0.38
        cut_meshes = [part["cut"] for part in self.parts.values() if part["cut"] is not None]
        lifts = [ShiftFade(mesh, lift, target_opacity=0.0) for mesh in cut_meshes]
        if lifts:
            self.scene.play(LaggedStart(*lifts, lag_ratio=0.08), run_time=1.15)
            self.scene.remove(*cut_meshes)
        self._cut_done = True
        if focus is not None:
            animations = self.focus_anims(focus)
            if animations:
                self.scene.play(*animations, run_time=0.65)
        return self

    def play_flow(self, duration: float = 3.0):
        self.clear_flow()
        arrows = []
        spheres = []
        starts = []
        ends = []
        for item in self.arrows:
            start = np.asarray(item["start"], dtype=float)
            end = np.asarray(item["end"], dtype=float)
            if np.linalg.norm(end - start) < 1e-6:
                continue
            color = item.get("color", BLUE_3B1B)
            arrows.append(make_arrow_mesh(start, end, color=color, opacity=0.92))
            spheres.append(
                make_sphere_mesh(
                    start,
                    radius=float(item.get("sphere_radius", 0.075)),
                    color=item.get("sphere_color", YELLOW_3B1B),
                    opacity=0.98,
                )
            )
            starts.append(start)
            ends.append(end)

        self._flow_objects = arrows + spheres
        if self._flow_objects:
            self._flow_group = Group(*self._flow_objects)
            self.scene.play(
                LaggedStart(
                    *[Reveal(mesh) for mesh in self._flow_objects],
                    lag_ratio=0.06,
                ),
                run_time=0.4,
            )
            self.scene.play(
                *[
                    SlideAlong(
                        sphere,
                        start,
                        end,
                        phase=index / max(len(spheres), 1),
                        cycles=2.0,
                    )
                    for index, (sphere, start, end) in enumerate(
                        zip(spheres, starts, ends)
                    )
                ],
                run_time=max(0.0, duration),
            )
        return self

    def clear_flow(self):
        if self._flow_objects:
            self.scene.remove(*self._flow_objects)
        self._flow_objects = []
        self._flow_group = None
        return self

    def anchor_2d(self, part_id: str) -> np.ndarray:
        camera = self.scene.camera
        rotation = np.asarray(camera.inverse_rotation_matrix)
        width, height = camera.get_shape()
        relative = self.parts[str(part_id)]["anchor"] - np.asarray(camera.get_center())
        x = float(np.dot(relative, rotation[0])) * config.frame_width / max(width, 1e-9)
        y = float(np.dot(relative, rotation[1])) * config.frame_height / max(height, 1e-9)
        return np.array([x, y, 0.0])

    def make_callout(
        self,
        part_id: str,
        label: str | None = None,
        color: str = YELLOW_3B1B,
        pos: Sequence[float] | None = None,
    ) -> Group:
        part_id = str(part_id)
        if label is None:
            label = self.part_names.get(part_id, part_id)
        anchor = self.anchor_2d(part_id)
        if pos is None:
            direction = 1.0 if anchor[0] < 0.0 else -1.0
            position = anchor + np.array([direction * 1.55, 0.72, 0.0])
            position[0] = float(np.clip(position[0], -5.8, 5.8))
            position[1] = float(np.clip(position[1], -2.9, 2.9))
        else:
            position = np.asarray(pos, dtype=float).reshape(3)

        text = serif_text(label, color=color, height=0.29, max_width=3.0)
        text.move_to(position)
        leader = open_curve([anchor, position], color=color, stroke_width=1.15, smooth=False)
        halo = Dot(anchor, radius=0.080, color=color).set_fill(color, opacity=0.18)
        halo.set_stroke(width=0.0)
        dot = Dot(anchor, radius=0.037, color=color).set_fill(color, opacity=1.0)
        dot.set_stroke(width=0.0)
        group = Group(leader, halo, dot, text)
        fix(group)

        def update_callout(mobject, dt=0.0):
            current_anchor = self.anchor_2d(part_id)
            delta = position - current_anchor
            if np.linalg.norm(delta) > 1e-8:
                try:
                    endpoint = np.asarray(text.get_boundary_point(-delta))
                except (AttributeError, ValueError):
                    endpoint = position.copy()
            else:
                endpoint = position.copy()
            leader.set_points_as_corners(
                np.asarray([current_anchor, endpoint], dtype=float)
            )
            halo.move_to(current_anchor)
            dot.move_to(current_anchor)

        group.add_updater(update_callout)
        update_callout(group, 0.0)
        return group


def load_forge_model(
    scene: ThreeDScene,
    forge_dir: str | Path | None = None,
    total_tri_budget: int = 38_000,
) -> ForgeModel:
    return ForgeModel(scene, forge_dir=forge_dir, total_tri_budget=total_tri_budget)
