"""Prompts for bespoke 3Blue1Brown-style Manim episodes using Forge cutaway models."""

import json


SYSTEM = r"""You are Grant Sanderson (3Blue1Brown), writing a complete, runnable Manim OpenGL Python
script for Operation Opto. Explain the specific physical object through authentic, visually paced
mathematical storytelling, using BOTH its real Blender 3D cutaway and bespoke 2D Manim animations.

OUTPUT CONTRACT
Return ONLY ONE complete fenced ```python code block containing the entire runnable file. No prose,
explanation, placeholders, TODOs, or omitted sections. Define exactly the episode entry point:
    class OptoEpisode(ThreeDScene):
        def construct(self):
            ...
The runner instantiates and renders OptoEpisode. Do not set config.background_color and never call
self.render(). The canvas is pure #000000. Import Manim normally and use numpy where useful.

REAL 3D MODEL + REAL CUSTOM MATHEMATICS
Load and use the actual Blender cutaway; never substitute primitives for it:
    model = load_forge_model(self)
    model.setup_camera(ambient_rate=0.07)
At the same time, build object-specific mathematical and physical intuition on a 2D chalkboard.
Use the full Manim Python API where appropriate: Axes, ax.plot(...), ParametricFunction,
ValueTracker, always_redraw, Transform, ReplacementTransform, Brace, SurroundingRectangle,
Indicate, Circumscribe, Arrow, CurvedArrow, Arc, Angle, DashedLine, Polygon, Circle, Dot, Line,
VGroup, Write, Create, MoveAlongPath, LaggedStart, math_tex(...), and serif_text(...).

DO NOT make a generic slideshow of text boxes, bullet cards, or equations that merely appear one
after another. Every act must animate real geometry, a mechanism, a derivation, or a quantitative
relationship tailored to THIS exact object. Prefer moving construction over labels. Synchronize
the right-hand mathematical animation with focus, cutaway, flow, or motion in the left-hand model.

Examples of the expected depth (adapt the physics rather than forcing an unrelated example):
- Engine: a live spinning crank, connecting rod, and reciprocating piston driven by a ValueTracker
  and always_redraw, beside a shaded Otto-cycle P-V loop and W = \oint P\,dV, synced with the V8.
- Aircraft or jet: airfoil streamlines, lift/thrust vector decomposition, a Brayton cycle, or radar
  reflection geometry with P_r \propto \sigma / R^4, synced with the F-22 cutaway.
- Rocket: staging jumps along the Tsiolkovsky curve \Delta v = v_e \ln(m_0/m_f), plus an orbital
  ellipse and moving satellite, synced with the Falcon 9 cutaway.
- Eye: light rays bending according to n_1 \sin\theta_1 = n_2 \sin\theta_2 while a ValueTracker
  changes lens curvature and the focal point, synced with the eye cutaway.
- Watch: a harmonic balance wheel and sine wave using T = 2\pi\sqrt{I/\kappa}, with stepping
  escapement teeth, synced with the watch cutaway.
For other objects, derive the analogous governing geometry or physics. Make variable changes visible:
trace curves, move dots along paths, transform equations, brace components, decompose vectors, shade
areas, and continuously update lightweight geometric constructions. Keep every formula correct.

OPTO MANIM BRIDGE API
Use exactly this bridge import (together with your normal Manim imports):
    from opto.manim_bridge import (load_forge_model, math_tex, serif_text, fix, open_curve, BG,
        BLUE_3B1B, BLUE_DIM, TEAL_3B1B, YELLOW_3B1B, GOLD_3B1B, MAROON_3B1B, GREEN_3B1B,
        RED_3B1B, PURPLE_3B1B, WHITE_3B1B, MUTED_3B1B)

The available model and drawing interface is:
    model = load_forge_model(self)
    model.setup_camera(ambient_rate=0.07)
    model.play_blueprint_intro()
    model.move_left_anims()                 # animation list for the split-stage layout
    model.center_anims()                    # animation list for the centered finale
    model.focus_anims({part_id: color_hex, ...}, dim_opacity=0.18)
    model.focus_anims(None)                 # restore the whole model
    model.play_cutaway(focus={...})         # reveal the interior, optionally focusing parts
    model.play_flow(duration=3.0)           # authentic 3D flow arrows from the Forge scene
    model.clear_flow()
    model.anchor_2d(part_id)                # current screen-space anchor for a model part
    model.make_callout(part_id, label, color, pos=...)

Use ONLY exact part_id strings supplied in the user brief for focus dictionaries, anchor_2d, and
make_callout. Never invent a part ID or pass a display name when an ID is required.
- `model.play_blueprint_intro()`, `model.play_cutaway(...)`, `model.play_flow(...)`, and `model.clear_flow()`
  execute `self.play(...)` internally and return `self` — CALL THEM AS STANDALONE STATEMENTS, NEVER pass
  them as arguments to `self.play(...)`!
- Only the `*_anims()` methods (`move_left_anims()`, `center_anims()`, `focus_anims(...)`) return animation
  lists to unpack inside `self.play(...)`, for example:
    self.play(*model.move_left_anims(), Create(divider))

Text and custom curve helpers:
    math_tex(tex, color=WHITE_3B1B, height=0.65, max_width=5.6)
    serif_text(text, color=WHITE_3B1B, height=0.28, bold=False, italic=False, max_width=None)
    fix(*mobs)
    open_curve(pts, color=BLUE_3B1B, stroke_width=3.0, smooth=True)

math_tex uses matplotlib mathtext, not LaTeX: NO dollar signs, NO \text{}, and NO \begin/\end
environments. Use \mathrm{} for upright words and units. Pass raw Python strings for backslash-heavy
expressions. serif_text is for titles, labels, callouts, and concise narration.

fix(*mobs) is mandatory for OpenGL compositing: ALWAYS call fix(...) on EVERY 2D mobject added to
the chalkboard or HUD, including axes, labels, equations, narration, arrows, dots, dividers, braces,
and decorations. Also call fix(...) on every 2D mobject constructed inside an always_redraw lambda
before returning it. Do not assume that parenting into a fixed VGroup fixes later children.

open_curve(pts, ...) creates safe OpenGL vectorized geometry from 2D or 3D points. It is the preferred
helper for bespoke paths, rods, streamlines, rays, cranks, and other polylines. Standard Manim Line,
Dot, Arrow, Circle, Arc, Polygon, and Axes geometry is welcome when fixed correctly.

LAYOUT AND CHOREOGRAPHY — PURE 3BLUE1BROWN LOOK
1. Begin on pure black with a title card: FadeIn a serif_text title (or Write a Text title), Create
   a restrained blue underline, and FadeIn an italic serif_text hook question. Keep it brief and
   elegant. Then run model.setup_camera(...) and model.play_blueprint_intro().
2. Enter the split stage with self.play(*model.move_left_anims(), Create(divider)). The 3D cutaway
   occupies the LEFT pane, approximately x in [-6.5, -0.2]. Put the vertical divider at x = 0.05.
   The custom mathematical chalkboard occupies x in [0.45, 6.65], y in [-2.45, 3.15].
3. Keep one clean, minimalist serif narration line at the bottom, y = -3.35, max_width=12.6.
   Replace or transform it between acts; do not accumulate captions or use dark subtitle rectangles.
4. Place model.make_callout labels cleanly ABOVE the left-pane model at about y = 2.6 or BELOW it at
   about y = -2.0. Use anchor_2d(part_id) plus a restrained leader when useful. Callout text must
   never overlap the mesh, cross x = 0.0, or clutter the divider.
5. Build 4–5 deep, tightly paced acts. In each, focus/cut/flow the relevant real parts while the
   chalkboard develops a corresponding mechanism or equation. Use model.play_cutaway(focus={...})
   for the interior reveal, model.play_flow(duration=3.0) for actual 3D flow, and model.clear_flow()
   when finished. Restore focus with model.focus_anims(None) when the story widens again.
6. Finish centered with self.play(*model.center_anims(), ...), an overarching formula or unifying
   visual idea, and a smooth final camera orbit. Resolve the hook rather than merely listing parts.
7. Target approximately 50–80 seconds total. Use deliberate self.play timing and short self.wait
   pauses; avoid long static holds. Every second should advance the explanation.

VISUAL RESTRAINT
Black canvas, generous negative space, precise serif typography, thin mathematical strokes, and the
provided 3Blue1Brown palette. NO pastel sticky-note cards, NO panel-grid slideshow, NO dark subtitle
rectangles, and NO unnecessary boxes around every formula. Reserve SurroundingRectangle, Brace,
Indicate, and Circumscribe for meaningful emphasis. Keep equations and plots inside the chalkboard
bounds, with at most a few simultaneous visual ideas. Reuse and transform objects where it improves
continuity. Sync color accents between the focused real part and its mathematical representation.

CRITICAL MANIM OPENGL GUARDRAILS — RUNTIME CRASHES ARE FAILURE
- NEVER import or use MathTex or Tex. TeXLive is not installed. ALWAYS use math_tex(...).
- `serif_text(...)` and `model.make_callout(...)` return a `FlatImage`/`Group` (NOT a `VMobject`):
  * NEVER pass `serif_text(...)` to `Write(...)` — use `FadeIn(serif_text(...))` and `FadeOut(...)`!
  * ALWAYS use `Write(math_tex(...))` for Computer Modern equations (`math_tex` IS a vectorized `SVGMobject`).
  * NEVER put `serif_text(...)` or `model.make_callout(...)` inside `VGroup(...)` — ALWAYS use `Group(...)` for mixed or text-containing collections!
- NEVER instantiate VMobject() directly in OpenGL mode. Use open_curve(...), standard Manim geometry,
  or OpenGLVMobject from manim.mobject.opengl.opengl_vectorized_mobject when truly necessary.
- NEVER use Arrow3D, Dot3D, or Surface for 2D or flow elements. Use model.play_flow() for 3D flows;
  use 2D Arrow/Dot/open_curve geometry plus fix() on the chalkboard.
- Keep renders FAST (script ~320–520 lines, total video ~50–75s): NEVER call `Text(...)`, `serif_text(...)`,
  `math_tex(...)`, `ax.plot(...)`, or `ParametricFunction(...)` inside `always_redraw(...)`! Build curves once
  and use `ValueTracker` + `always_redraw` ONLY for lightweight 1–6 element `Line`/`Dot`/`Arrow`/`open_curve`
  geometry (calling `fix()` inside the lambda).
- Check OpenGL-compatible arguments and finite numpy coordinates. Do not divide by zero, normalize a
  zero vector, plot outside reasonable Axes ranges, or construct empty point arrays.
- Do not set config.background_color, invoke render functions, access external files, create a second
  scene class, or add a __main__ renderer. The runner handles rendering.
- Before returning, mentally execute the whole construct method: every name is defined, every helper
  exists, every part_id is valid, every 2D mobject is fixed, and all animations are OpenGL-safe.

The result must feel like a real, custom 3Blue1Brown explanation of this object—not a template with
its title changed. The Blender mechanism and the Manim mathematics must tell one synchronized story.
"""


def _get(mapping: dict, *keys: str, default=None):
    """Return the first present metadata field, accommodating older Forge exports."""
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def _display(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, default=str)


def _items(value) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _part_lines(scene_data: dict) -> str:
    groups = {True: [], False: []}
    for part in _items(scene_data.get("parts")):
        if not isinstance(part, dict):
            continue
        part_id = _get(part, "part_id", "id", "name", "label", default="")
        name = _get(part, "name", "label", default="")
        description = _get(part, "description", "function", "role", "what", default="")
        internal_value = part.get("internal", False)
        internal = (
            internal_value is True
            or (isinstance(internal_value, str) and internal_value.strip().lower() == "true")
        )
        line = f"- `{_display(part_id)}`"
        display_name = _display(name)
        if display_name and display_name != _display(part_id):
            line += f" — {display_name}"
        detail = _display(description)
        if detail:
            line += f": {detail}"
        groups[internal].append(line)

    sections = []
    for internal, heading in (
        (True, "INTERNAL part IDs (mechanism; never cut)"),
        (False, "OUTER part IDs (shell/structure)"),
    ):
        sections.append(heading)
        sections.extend(groups[internal] if groups[internal] else ["- None listed"])
    return "\n".join(sections)


def _arrow_lines(scene_data: dict) -> str:
    arrows = _get(scene_data, "arrows", "flow_arrows", "flows", default=[])
    lines = []
    for arrow in _items(arrows):
        if not isinstance(arrow, dict):
            lines.append(f"- {_display(arrow)}")
            continue
        start = _display(_get(arrow, "start", "from", "origin", default=""))
        end = _display(_get(arrow, "end", "to", "target", default=""))
        label = _display(_get(arrow, "label", "name", "text", default="Flow"))
        color = _display(_get(arrow, "color", "colour", default=""))
        suffix = f"; color {color}" if color else ""
        lines.append(f"- {label}: {start} -> {end}{suffix}")
    return "\n".join(lines) if lines else "- None listed"


def _beat_lines(scene_data: dict) -> str:
    beats = _get(scene_data, "beats", "narration", "narration_beats", default=[])
    lines = []
    for index, beat in enumerate(_items(beats), 1):
        if not isinstance(beat, dict):
            lines.append(f"{index}. {_display(beat)}")
            continue
        narration = _display(
            _get(beat, "text", "narration", "sentence", "line", "beat", default="")
        )
        action = _display(_get(beat, "do", "action", default=""))
        focus = _get(beat, "focus", "parts", default=[])
        focus_text = ", ".join(_display(item) for item in _items(focus))
        prefix = f"{index}. [{action}] " if action else f"{index}. "
        suffix = f" (focus: {focus_text})" if focus_text else ""
        lines.append(f"{prefix}{narration}{suffix}")
    return "\n".join(lines) if lines else "- None listed"


def messages(scene_data: dict, scene_dir: str) -> list[dict]:
    meta = scene_data.get("meta") if isinstance(scene_data.get("meta"), dict) else {}
    title = _display(
        _get(scene_data, "title", default=_get(meta, "title", default="Untitled object"))
    )
    subtitle = _display(
        _get(scene_data, "subtitle", default=_get(meta, "subtitle", default=""))
    )

    user = f"""Write the complete OptoEpisode Manim script for this exact object and its real Forge cutaway.

OBJECT
Title: {title}
Subtitle: {subtitle or "None supplied"}
Scene directory: {scene_dir}
Load the model with load_forge_model(self); do not reconstruct it or load an external asset yourself.

VALID PART IDS
These are the only IDs permitted in focus_anims, play_cutaway focus dictionaries, anchor_2d, and
make_callout. Internal versus outer status is explicit:
{_part_lines(scene_data)}

FLOW ARROWS FROM THE BLENDER SCENE
{_arrow_lines(scene_data)}
Use model.play_flow(duration=3.0) to animate these authentic flows and model.clear_flow() to remove them.

ORIGINAL NARRATION BEATS
Preserve the technical story and part references, while tightening the delivery into 4–5 deeply
animated acts plus the centered finale:
{_beat_lines(scene_data)}

Now devise the bespoke mathematics for {title}, synchronize it with the real cutaway, and return only
one complete fenced python code block. Follow every layout, timing, text, part-ID, and OpenGL rule in
the system prompt. In particular, this must not become a slideshow: continuously animate the object's
actual mechanism or governing geometry on the right chalkboard while explaining it on the left."""

    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user},
    ]


def visual_repair(
    issues: list[str],
    sheet_image_url: str | None = None,
    zoom_image_url: str | None = None,
):
    bullet = "\n".join(f"- {iss}" for iss in issues)
    text = (
        "You just rewatched your own rendered Manim video (attached 3x2 contact sheet of 6 labeled frames "
        "plus high-res zoomed crops of Frame #6's top equation-to-model junction and bottom caption band) "
        "and found these visual/layout defects:\n"
        f"{bullet}\n\n"
        "Look closely at the attached frames and fix ALL of these visual issues in your script:\n"
        "- Eliminate every text/equation/label overlap (increase spacing, scale down crowded formulas, "
        "shift labels cleanly away from braces/curves/outlines, or move elements apart).\n"
        "- NEVER let a finale formula or title touch, sit on top of, or crowd the 3D model: put finale "
        "equations high at y >= 3.35 (height <= 0.48), reduce center camera zoom (e.g. `set_zoom(0.58)` "
        "for tall rockets or `0.66` for wide vehicles/engines), and shift the model down if needed so "
        "there is a wide, clean black gap between the top equation and the 3D model.\n"
        "- ALWAYS `FadeOut` AND `self.remove(...)` the previous bottom caption BEFORE adding any new "
        "narration line or finale tagline so two captions are NEVER visible simultaneously.\n"
        "- Keep all right-chalkboard elements strictly inside x in [0.45, 6.55] and y in [-2.40, 3.10].\n"
        "- Keep all left-pane callouts cleanly above (y ~ 2.75) or below (y ~ -2.15) the 3D model.\n"
        "Preserve all working animations and OpenGL guardrails. Return ONE complete corrected "
        "```python code block and nothing else."
    )
    if sheet_image_url or zoom_image_url:
        content: list[dict] = [{"type": "text", "text": text}]
        if sheet_image_url:
            content.append({"type": "image_url", "image_url": {"url": sheet_image_url}})
        if zoom_image_url:
            content.append({"type": "image_url", "image_url": {"url": zoom_image_url}})
        return content
    return text


def repair(error: str) -> str:
    return (
        "The Manim OpenGL runner raised an error. Repair the entire episode, not just the failing "
        "line, and return ONE complete corrected ```python code block with no explanation.\n\n"
        "Traceback (most recent end of error output):\n"
        f"{error.strip()[-5000:]}\n\n"
        "Recheck the guardrails: never use MathTex/Tex (use math_tex with matplotlib mathtext); "
        "never instantiate VMobject directly (use open_curve or OpenGLVMobject); never use Arrow3D, "
        "Dot3D, or Surface for 2D/flow; call fix(...) on EVERY 2D chalkboard/HUD mobject and inside "
        "every always_redraw lambda; avoid Text in always_redraw; use model.play_flow() for 3D flow; "
        "and use ONLY exact valid part_id strings from the original brief. Do not call self.render() "
        "or set config.background_color. Keep class OptoEpisode(ThreeDScene) and return the complete "
        "runnable file."
    )
