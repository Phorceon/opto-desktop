"""Kimi K3.1 (via OpenClaw) 3Blue1Brown storyboard director for Forge 3D scenes.

Given a Forge scene directory (out/forge/<id>/scene.json), generates and caches
out/forge/<id>/story_3b1b.json containing:
  - Grant Sanderson–style chapter arc (blueprint intro -> cutaway -> mechanisms -> synthesis)
  - Real governing physics/math LaTeX equations (validated against matplotlib mathtext)
  - Color-coded symbol legends matched to highlighted 3D parts
  - Concrete animated 2D Manim diagram specs (axes curve, thermodynamic/mechanical cycle loop,
    2D force/ray vector diagram, or energy/signal pipeline chain)
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from . import llm

PALETTE = {
    "BLUE": "#58C4DD",
    "BLUE_C": "#58C4DD",
    "TEAL": "#5CD0B3",
    "TEAL_C": "#5CD0B3",
    "YELLOW": "#F9E154",
    "GOLD": "#F0AC5F",
    "GOLD_C": "#F0AC5F",
    "RED": "#FC6255",
    "RED_B": "#FF8080",
    "MAROON": "#EC92AB",
    "MAROON_B": "#EC92AB",
    "GREEN": "#83C167",
    "GREEN_C": "#83C167",
    "PURPLE": "#B189C6",
    "WHITE": "#ECECEC",
}

COLOR_CYCLE = ["BLUE_C", "YELLOW", "TEAL_C", "GOLD_C", "MAROON_B", "GREEN_C"]

SYSTEM_PROMPT = """You are a 3Blue1Brown episode director pairing a real 3D Blender cutaway model (left half of screen)
with an animated Manim mathematical & physical chalkboard (right half of screen).

Return ONLY a single valid JSON object (no markdown fences, no commentary) with this exact schema:
{
  "title": "short crisp title (<= 46 chars)",
  "hook": "one-line 3Blue1Brown intuition question (<= 72 chars)",
  "final_equation": "single overarching matplotlib-mathtext LaTeX string (no $ signs)",
  "chapters": [
    {
      "heading": "01 · Short Chapter Name (<= 30 chars)",
      "action": "blueprint_build" | "cutaway" | "highlight" | "flow" | "synthesis",
      "narration": "concise Grant Sanderson style explanation (12-22 words, <= 125 chars)",
      "focus": [
        {"part": "<exact part id from list>", "label": "<short 1-3 word callout>", "color": "BLUE_C|YELLOW|TEAL_C|GOLD_C|MAROON_B|GREEN_C"}
      ],
      "equation": {
        "tex": "valid matplotlib mathtext LaTeX (NO $ signs, NO \\text{}, use \\mathrm{} instead, NO \\begin/\\end, NO \\color)",
        "box_color": "YELLOW|BLUE_C|TEAL_C|GOLD_C",
        "terms": [
          {"sym": "L", "meaning": "short phrase (<= 22 chars)", "color": "YELLOW"}
        ]
      },
      "diagram": {
        "kind": "curve" | "cycle" | "vectors" | "chain",
        ... (see exact fields below)
      }
    }
  ]
}

Diagram specs by "kind":
1) "curve": 2D Axes with 1 or 2 smooth curves + moving dot on primary curve:
   {"kind": "curve", "title": "short label", "x_label": "x (unit)", "y_label": "y (unit)",
    "x_range": [xmin, xmax, xstep], "y_range": [ymin, ymax, ystep],
    "curves": [{"points": [[x0,y0], [x1,y1], ... (8-16 smooth points)], "color": "BLUE_C", "label": "short", "fill": true}],
    "highlight_point": [x, y, "short annotation"]}
2) "cycle": closed 2D loop (e.g. P-V diagram, thermodynamic cycle, oscillation orbit) with shaded work area + moving tracer:
   {"kind": "cycle", "title": "short label", "x_label": "V", "y_label": "P",
    "x_range": [xmin, xmax, xstep], "y_range": [ymin, ymax, ystep],
    "loop": [[x0,y0], ... (10-20 points closing back toward start)],
    "shade_color": "BLUE_C",
    "stages": [{"pos": [x, y], "label": "1. Intake", "color": "YELLOW"} (2-4 stages)]}
3) "vectors": 2D physics force / optical ray / geometry vector diagram in local coords x in [-2.4, 2.4], y in [-1.3, 1.3]:
   {"kind": "vectors", "title": "short label", "axes_cross": true,
    "dashed": [{"from": [x1,y1], "to": [x2,y2], "label": "optional"}],
    "vectors": [{"from": [x1,y1], "to": [x2,y2], "label": "Lift L", "color": "YELLOW"} (2-5 vectors)]}
4) "chain": 3-4 step energy / signal / mechanical transformation diagram:
   {"kind": "chain", "title": "short label",
    "nodes": [{"label": "Combustor", "sub": "heat in", "color": "GOLD_C"} (3-4 nodes)]}

Rules:
- Exactly 5 or 6 chapters:
  - Chapter 1 MUST have "action": "blueprint_build" (introduces outer form + core physical principle).
  - Exactly ONE chapter (chapter 2 or 3) MUST have "action": "cutaway" if internal parts exist.
  - Include ONE chapter with "action": "flow" if flow arrows exist.
  - Last chapter MUST have "action": "synthesis" (brings subsystems together with the overarching principle).
- Every "focus" part id MUST come verbatim from the provided parts list (1-3 focused parts per chapter, distinct colors).
- Every equation MUST be real, accurate physics/math for this specific object, and strictly valid in matplotlib mathtext:
  - Allowed: \\frac{a}{b}, \\sqrt{x}, \\ln, \\sin, \\cos, \\tan, \\Delta, \\eta, \\rho, \\gamma, \\theta, \\omega, \\pi, \\tau, \\sigma, \\lambda, \\dot{m}, \\vec{F}, \\propto, \\approx, \\cdot, \\times, \\sum, \\int, \\left(, \\right), \\mathrm{...}, subscripts/superscripts.
  - FORBIDDEN: \\text{}, \\textbf{}, \\begin{}, \\end{}, \\color{}, \\boxed{}, \\xrightarrow{}, \\units{}, raw % or # or &, $ signs.
- Keep equations crisp (1 short line, <= 55 chars of LaTeX) and 2-3 terms per legend.
- Vary diagram kinds across chapters (use real curves, cycles, vector diagrams, and chains—not all the same kind!).
"""


def _validate_mathtext(tex: str) -> bool:
    """Check whether matplotlib mathtext can parse `tex` cleanly."""
    if not tex or not isinstance(tex, str):
        return False
    s = tex.strip().strip("$")
    if not s or len(s) > 120:
        return False
    try:
        from matplotlib.mathtext import MathTextParser
        MathTextParser("path").parse(f"${s}$", dpi=100)
        return True
    except Exception:
        return False


def _sanitize_tex(tex: str) -> str:
    s = (tex or "").strip()
    if s.startswith("$") and s.endswith("$"):
        s = s.strip("$").strip()
    s = re.sub(r"\\text\{([^}]*)\}", r"\\mathrm{\1}", s)
    s = re.sub(r"\\textbf\{([^}]*)\}", r"\\mathrm{\1}", s)
    s = s.replace("\\%", r"\%").replace("\\,", " ")
    return s


def _norm_color(c: str | None, idx: int = 0) -> str:
    if c and c.upper() in PALETTE:
        return c.upper()
    if c and isinstance(c, str) and c.startswith("#") and len(c) == 7:
        return c
    return COLOR_CYCLE[idx % len(COLOR_CYCLE)]


def color_hex(c: str | None, idx: int = 0) -> str:
    if not c:
        return PALETTE[COLOR_CYCLE[idx % len(COLOR_CYCLE)]]
    if c.startswith("#") and len(c) == 7:
        return c
    return PALETTE.get(c.upper(), PALETTE[COLOR_CYCLE[idx % len(COLOR_CYCLE)]])


def _extract_json(raw: str) -> dict | None:
    raw = raw.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.S)
    if m:
        raw = m.group(1)
    else:
        i, j = raw.find("{"), raw.rfind("}")
        if i >= 0 and j > i:
            raw = raw[i:j + 1]
    try:
        return json.loads(raw)
    except Exception:
        return None


def _clean_story(raw_obj: dict, scene_data: dict) -> dict:
    parts = [p for p in scene_data.get("parts", []) if p.get("id") and p["id"] != "_structure"]
    part_ids = {p["id"] for p in parts}
    by_id = {p["id"]: p for p in parts}
    has_internal = any(p.get("internal") for p in parts)
    has_arrows = bool(scene_data.get("arrows"))

    title = str(raw_obj.get("title") or scene_data.get("title") or "Untitled")[:56]
    hook = str(raw_obj.get("hook") or scene_data.get("subtitle") or "")[:90]
    final_eq = _sanitize_tex(str(raw_obj.get("final_equation") or ""))
    if not _validate_mathtext(final_eq):
        final_eq = r"E_{\mathrm{in}} = W_{\mathrm{out}} + Q_{\mathrm{loss}}"

    chapters_in = raw_obj.get("chapters") or []
    chapters = []
    used_cut = False
    for ci, ch in enumerate(chapters_in[:6]):
        if not isinstance(ch, dict):
            continue
        act = ch.get("action", "highlight")
        if act not in ("blueprint_build", "cutaway", "highlight", "flow", "explode", "synthesis"):
            act = "highlight"
        if ci == 0:
            act = "blueprint_build"
        if act == "cutaway":
            if used_cut or not has_internal:
                act = "highlight"
            else:
                used_cut = True
        if act == "flow" and not has_arrows:
            act = "highlight"

        focus = []
        seen_p = set()
        for fi, f in enumerate(ch.get("focus") or []):
            if isinstance(f, str):
                pid, lbl, col = f, by_id.get(f, {}).get("name", f), COLOR_CYCLE[fi % len(COLOR_CYCLE)]
            elif isinstance(f, dict):
                pid = f.get("part", "")
                lbl = str(f.get("label") or by_id.get(pid, {}).get("name") or pid)[:24]
                col = _norm_color(f.get("color"), fi)
            else:
                continue
            if pid in part_ids and pid not in seen_p:
                seen_p.add(pid)
                focus.append({"part": pid, "label": lbl, "color": col})
            if len(focus) >= 3:
                break

        eq_in = ch.get("equation") if isinstance(ch.get("equation"), dict) else {}
        tex = _sanitize_tex(str(eq_in.get("tex") or ""))
        if not _validate_mathtext(tex):
            tex = final_eq if _validate_mathtext(final_eq) else ""
        terms = []
        for ti, tm in enumerate((eq_in.get("terms") or [])[:3]):
            if not isinstance(tm, dict):
                continue
            sym = _sanitize_tex(str(tm.get("sym") or ""))
            meaning = str(tm.get("meaning") or "")[:28]
            if sym and meaning and _validate_mathtext(sym):
                terms.append({"sym": sym, "meaning": meaning, "color": _norm_color(tm.get("color"), ti)})

        diag = _clean_diagram(ch.get("diagram"))
        chapters.append({
            "heading": str(ch.get("heading") or f"0{ci+1} · Mechanism")[:38],
            "action": act,
            "narration": str(ch.get("narration") or "")[:145],
            "focus": focus,
            "equation": {
                "tex": tex,
                "box_color": _norm_color(eq_in.get("box_color"), ci),
                "terms": terms,
            } if tex else None,
            "diagram": diag,
        })

    if not chapters:
        return fallback_story(scene_data)

    # Guarantee cutaway when internals exist and synthesis at end
    if has_internal and not any(c["action"] == "cutaway" for c in chapters) and len(chapters) >= 2:
        chapters[1]["action"] = "cutaway"
    if chapters[-1]["action"] != "synthesis":
        chapters[-1]["action"] = "synthesis"

    return {
        "title": title,
        "hook": hook,
        "final_equation": final_eq,
        "chapters": chapters,
    }


def _clean_diagram(d) -> dict | None:
    if not isinstance(d, dict):
        return None
    kind = d.get("kind")
    title = str(d.get("title") or "")[:46]
    if kind == "curve":
        xr = d.get("x_range") or [0, 10, 2]
        yr = d.get("y_range") or [0, 10, 2]
        if len(xr) != 3 or len(yr) != 3 or xr[1] <= xr[0] or yr[1] <= yr[0]:
            return None
        curves = []
        for ci, c in enumerate((d.get("curves") or [])[:2]):
            pts = c.get("points") or []
            pts = [[float(p[0]), float(p[1])] for p in pts if isinstance(p, (list, tuple)) and len(p) >= 2]
            if len(pts) >= 3:
                curves.append({
                    "points": pts,
                    "color": _norm_color(c.get("color"), ci),
                    "label": str(c.get("label") or "")[:20],
                    "fill": bool(c.get("fill", ci == 0)),
                })
        if not curves:
            return None
        hp = d.get("highlight_point")
        hp_clean = None
        if isinstance(hp, (list, tuple)) and len(hp) >= 2:
            hp_clean = [float(hp[0]), float(hp[1]), str(hp[2])[:22] if len(hp) > 2 else ""]
        return {
            "kind": "curve",
            "title": title,
            "x_label": str(d.get("x_label") or "x")[:18],
            "y_label": str(d.get("y_label") or "y")[:18],
            "x_range": [float(xr[0]), float(xr[1]), max(float(xr[2]), (float(xr[1]) - float(xr[0])) / 6.0)],
            "y_range": [float(yr[0]), float(yr[1]), max(float(yr[2]), (float(yr[1]) - float(yr[0])) / 6.0)],
            "curves": curves,
            "highlight_point": hp_clean,
        }
    if kind == "cycle":
        xr = d.get("x_range") or [0, 10, 2]
        yr = d.get("y_range") or [0, 10, 2]
        loop = [[float(p[0]), float(p[1])] for p in (d.get("loop") or []) if isinstance(p, (list, tuple)) and len(p) >= 2]
        if len(xr) != 3 or len(yr) != 3 or xr[1] <= xr[0] or yr[1] <= yr[0] or len(loop) < 4:
            return None
        stages = []
        for si, st in enumerate((d.get("stages") or [])[:4]):
            pos = st.get("pos")
            if isinstance(pos, (list, tuple)) and len(pos) >= 2:
                stages.append({
                    "pos": [float(pos[0]), float(pos[1])],
                    "label": str(st.get("label") or "")[:18],
                    "color": _norm_color(st.get("color"), si),
                })
        return {
            "kind": "cycle",
            "title": title,
            "x_label": str(d.get("x_label") or "V")[:18],
            "y_label": str(d.get("y_label") or "P")[:18],
            "x_range": [float(xr[0]), float(xr[1]), max(float(xr[2]), (float(xr[1]) - float(xr[0])) / 6.0)],
            "y_range": [float(yr[0]), float(yr[1]), max(float(yr[2]), (float(yr[1]) - float(yr[0])) / 6.0)],
            "loop": loop,
            "shade_color": _norm_color(d.get("shade_color"), 0),
            "stages": stages,
        }
    if kind == "vectors":
        vecs = []
        for vi, v in enumerate((d.get("vectors") or [])[:5]):
            fr, to = v.get("from"), v.get("to")
            if isinstance(fr, (list, tuple)) and isinstance(to, (list, tuple)) and len(fr) >= 2 and len(to) >= 2:
                vecs.append({
                    "from": [float(fr[0]), float(fr[1])],
                    "to": [float(to[0]), float(to[1])],
                    "label": str(v.get("label") or "")[:20],
                    "color": _norm_color(v.get("color"), vi),
                })
        if not vecs:
            return None
        dashed = []
        for dl in (d.get("dashed") or [])[:4]:
            fr, to = dl.get("from"), dl.get("to")
            if isinstance(fr, (list, tuple)) and isinstance(to, (list, tuple)) and len(fr) >= 2 and len(to) >= 2:
                dashed.append({
                    "from": [float(fr[0]), float(fr[1])],
                    "to": [float(to[0]), float(to[1])],
                    "label": str(dl.get("label") or "")[:18],
                })
        return {
            "kind": "vectors",
            "title": title,
            "axes_cross": bool(d.get("axes_cross", True)),
            "dashed": dashed,
            "vectors": vecs,
        }
    if kind == "chain":
        nodes = []
        for ni, n in enumerate((d.get("nodes") or [])[:4]):
            if isinstance(n, dict) and n.get("label"):
                nodes.append({
                    "label": str(n["label"])[:16],
                    "sub": str(n.get("sub") or "")[:16],
                    "color": _norm_color(n.get("color"), ni),
                })
        if len(nodes) < 2:
            return None
        return {"kind": "chain", "title": title, "nodes": nodes}
    return None


def fallback_story(scene_data: dict) -> dict:
    """Deterministic fallback if LLM is unavailable."""
    parts = [p for p in scene_data.get("parts", []) if p.get("id") and p["id"] != "_structure"]
    beats = scene_data.get("beats") or []
    chapters = []
    for i, b in enumerate(beats[:6]):
        do = b.get("do", "highlight")
        act = {"build": "blueprint_build", "cut": "cutaway", "orbit": "synthesis"}.get(do, do)
        focus = [
            {"part": pid, "label": next((p["name"] for p in parts if p["id"] == pid), pid)[:22],
             "color": COLOR_CYCLE[j % len(COLOR_CYCLE)]}
            for j, pid in enumerate((b.get("focus") or [])[:3])
            if any(p["id"] == pid for p in parts)
        ]
        chapters.append({
            "heading": f"0{i+1} · {act.replace('_', ' ').title()}",
            "action": act,
            "narration": str(b.get("say") or "")[:140],
            "focus": focus,
            "equation": None,
            "diagram": None,
        })
    return {
        "title": scene_data.get("title") or "Untitled",
        "hook": scene_data.get("subtitle") or "",
        "final_equation": r"E_{\mathrm{in}} = W_{\mathrm{out}} + Q_{\mathrm{loss}}",
        "chapters": chapters,
    }


def _build_user_prompt(scene_data: dict) -> str:
    parts = [p for p in scene_data.get("parts", []) if p.get("id") and p["id"] != "_structure"]
    part_lines = [f"- {p['id']}: {p.get('name', p['id'])} ({'internal' if p.get('internal') else 'outer'}) — {p.get('info', '')[:90]}"
                  for p in parts[:45]]
    arrow_lines = [f"- {a.get('label', 'flow')}" for a in (scene_data.get("arrows") or [])[:6]]
    beat_lines = [f"- [{b.get('do')}] {b.get('say', '')}" for b in (scene_data.get("beats") or [])[:8]]
    return (
        f"Object title: {scene_data.get('title')}\n"
        f"Subtitle: {scene_data.get('subtitle')}\n\n"
        f"Available 3D Blender parts (use ONLY these exact IDs in focus):\n" + "\n".join(part_lines) + "\n\n"
        f"Flow arrows in scene: {', '.join(arrow_lines) or 'none'}\n\n"
        f"Existing narration beats for context:\n" + "\n".join(beat_lines) + "\n\n"
        "Design a 5-6 chapter 3Blue1Brown visual-math episode JSON for this object. "
        "Include real, accurate equations and genuinely illuminating 2D graphs/cycles/vector diagrams for each chapter."
    )


async def generate_story(forge_dir: str | Path, *, force: bool = False) -> dict:
    forge_dir = Path(forge_dir)
    out_file = forge_dir / "story_3b1b.json"
    scene_data = json.loads((forge_dir / "scene.json").read_text())
    if out_file.exists() and not force:
        return json.loads(out_file.read_text())

    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(scene_data)},
    ]
    st = llm.Stats(llm.KIMI)
    try:
        raw = await llm.acomplete(msgs, max_tokens=24000, stats=st)
        parsed = _extract_json(raw)
        if parsed and isinstance(parsed, dict) and parsed.get("chapters"):
            story = _clean_story(parsed, scene_data)
            story["_meta"] = {"model": llm.KIMI, "backend": llm.BACKEND, "wall": round((st.t_end or 0) - st.t_start, 2)}
            out_file.write_text(json.dumps(story, indent=2))
            return story
        print(f"[story3b1b] Kimi returned unparseable JSON (len={len(raw)}, tokens={st.completion_tokens}), using fallback")
    except Exception as e:
        print(f"[story3b1b] Kimi generation failed ({e!r}), using fallback")
    story = fallback_story(scene_data)
    out_file.write_text(json.dumps(story, indent=2))
    return story


def ensure_story_for_scene(scene_data: dict, *, model: str | None = None) -> dict:
    """Generate a 3Blue1Brown storyboard for an in-memory/NDJSON scene using Kimi K3.1."""
    use_model = model or llm.KIMI
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(scene_data)},
    ]
    st = llm.Stats(use_model)
    try:
        raw = asyncio.run(llm.acomplete(msgs, model=use_model, max_tokens=6000, effort="low", stats=st))
        parsed = _extract_json(raw)
        if parsed and isinstance(parsed, dict) and parsed.get("chapters"):
            return _clean_story(parsed, scene_data)
    except Exception:
        pass
    return fallback_story(scene_data)


def ensure_story(forge_dir: str | Path, *, force: bool = False) -> dict:
    forge_dir = Path(forge_dir)
    out_file = forge_dir / "story_3b1b.json"
    if out_file.exists() and not force:
        return json.loads(out_file.read_text())
    return asyncio.run(generate_story(forge_dir, force=force))


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:]:
        s = ensure_story(arg, force="--force" in sys.argv)
        print(arg, "->", len(s["chapters"]), "chapters, final_eq:", s["final_equation"])
        for ch in s["chapters"]:
            print("  ", ch["heading"], f"[{ch['action']}]",
                  "eq=" + (ch["equation"]["tex"] if ch["equation"] else "none"),
                  "diag=" + (ch["diagram"]["kind"] if ch["diagram"] else "none"))
