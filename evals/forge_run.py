"""Forge eval: Kimi writes Blender code for every query (through OpenClaw), Blender builds it, we score it.

    uv run python evals/forge_run.py [--split core|hard|all] [--parallel 3] [ids...]
    uv run python evals/forge_run.py --rerun [--split all]   # re-run saved scene.py, no Kimi call

Scores what can be checked mechanically. Visual quality is judged separately from screenshots
(evals/render.py --forge) — passing these checks is necessary, not sufficient.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from opto import forge, llm  # noqa: E402

QUERIES = json.loads((ROOT / "evals" / "queries.json").read_text())


def _kw_hit(kw: str, hay: str) -> bool:
    kw = kw.lower()
    alts = {kw, kw.rstrip("s"), kw + "s", kw.replace(" ", "_"), kw.replace(" ", ""), kw.replace("-", " "),
            kw.replace("-", "")}
    return any(a and a in hay for a in alts)


def _box_gap(a, b) -> float:
    return max(0.0, *(max(a["bbox_min"][k] - b["bbox_max"][k], b["bbox_min"][k] - a["bbox_max"][k]) for k in range(3)))


def score(q: dict, rec: dict) -> dict:
    checks: dict[str, tuple[bool, str]] = {}
    sc = rec.get("scene")
    att = rec.get("attempts", [])
    checks["runs"] = (sc is not None, f"{len(att)} attempt(s); last error: {(att[-1]['error'][-160:] if att and not att[-1]['ok'] else 'none')!r}")
    if sc is None:
        return {"id": q["id"], "score": 0.0, "pass": False, "checks": {k: {"ok": v[0], "detail": v[1]} for k, v in checks.items()}}
    parts = [p for p in sc["parts"] if p["id"] != "_structure"]
    hay = " | ".join((p["id"].replace("_", " ") + " " + p["name"]).lower() for p in parts)
    hay += " | " + " | ".join(l["text"].lower() for l in sc.get("labels", []))
    hits = [k for k in q["must_have"] if _kw_hit(k, hay)]
    checks["coverage"] = (len(hits) / len(q["must_have"]) >= 0.8,
                          f"{len(hits)}/{len(q['must_have'])} missing={sorted(set(q['must_have']) - set(hits))}")
    # molecules legitimately have a handful of parts (atoms + bonds); everything else needs real detail
    lo = 3 if q.get("category") == "chemistry" else 10
    checks["parts"] = (lo <= len(parts) <= 70, f"{len(parts)} parts (min {lo}), {sc['stats'].get('tris')} tris")
    ni = sum(1 for p in parts if p["internal"])
    if q.get("needs_internal"):
        checks["internal"] = (ni >= 3, f"{ni} internal parts")
    checks["labels"] = (5 <= len(sc.get("labels", [])) <= 12, f"{len(sc.get('labels', []))} labels")
    checks["arrows"] = (2 <= len(sc.get("arrows", [])) <= 6, f"{len(sc.get('arrows', []))} arrows")
    dos = [b["do"] for b in sc.get("beats", [])]
    ok = 5 <= len(dos) <= 9 and dos[:1] == ["build"] and dos[-1:] == ["orbit"] and all(b["focus"] or b["do"] in ("build", "orbit") for b in sc["beats"])
    if q.get("needs_internal"):
        ok = ok and dos.count("cut") == 1
    checks["beats"] = (ok, f"{dos}")
    boxed = [p for p in sc["parts"] if "bbox_min" in p]
    if len(boxed) > 1:
        tol = 0.25
        conn = sum(1 for a in boxed if any(b is not a and _box_gap(a, b) <= tol for b in boxed))
        checks["connected"] = (conn / len(boxed) >= 0.9, f"{conn}/{len(boxed)} parts touch a neighbour")
    tris = sc["stats"].get("tris") or 0
    checks["detail"] = (1500 <= tris <= 600000, f"{tris} triangles")
    passed = sum(1 for v in checks.values() if v[0])
    return {"id": q["id"], "score": round(passed / len(checks), 3), "pass": passed == len(checks),
            "checks": {k: {"ok": v[0], "detail": v[1]} for k, v in checks.items()}}


def _att_rows(rec: dict) -> list[dict]:
    rows = []
    for a in rec["attempts"]:
        st = a.get("stats") or {}
        rows.append({k: a.get(k) for k in ("ok", "blender_s", "lines")} |
                    {"ttft": st.get("ttft"), "tokens": st.get("completion_tokens"), "err": st.get("error")})
    return rows


async def one(q, sem, run_dir):
    async with sem:
        t0 = time.time()
        rec = await forge.forge(q["query"], sid=q["id"])
    r = score(q, rec)
    r["wall"] = round(time.time() - t0, 1)
    r["attempts"] = _att_rows(rec)
    print(f"{q['id']:26s} score={r['score']:.2f} pass={r['pass']!s:5s} attempts={len(rec['attempts'])} wall={r['wall']}s "
          f"fails={[k for k, v in r['checks'].items() if not v['ok']]}", flush=True)
    return r


async def one_rerun(q, sem):
    """Re-execute the saved out/forge/<id>/scene.py on the current runtime; no Kimi call."""
    sid = q["id"]
    outdir = forge.FORGE / sid
    script = outdir / "scene.py"
    if not script.exists():
        return None
    code = script.read_text()
    rec_path = outdir / "record.json"
    old = json.loads(rec_path.read_text()) if rec_path.exists() else {}
    # run_script rmtree's the outdir: stash the record and attempt files first
    old_attempt_files = {p.name: p.read_text() for p in outdir.glob("attempt*.py")}
    old_bl = (old.get("attempts") or [{}])[-1].get("blender_s")
    async with sem:
        t0 = time.time()
        res = await forge.run_script(code, outdir)
    for name, text in old_attempt_files.items():
        (outdir / name).write_text(text)
    rec = dict(old)
    rec["scene"] = res.get("scene")
    if res["ok"]:
        rec.pop("error", None)
    else:
        rec["error"] = res.get("error", "")
    attempts = list(old.get("attempts") or [{"stats": {}}])
    attempts[-1] = dict(attempts[-1], ok=res["ok"], blender_s=res["seconds"],
                        error=res.get("error", "")[-600:])
    rec["attempts"] = attempts
    rec_path.write_text(json.dumps(rec, indent=1))
    r = score(q, rec)
    r["wall"] = round(time.time() - t0, 1)
    r["attempts"] = _att_rows(rec)
    r["blender_old"], r["blender_new"] = old_bl, res["seconds"]
    print(f"{sid:26s} score={r['score']:.2f} pass={r['pass']!s:5s} attempts={len(rec['attempts'])} wall={r['wall']}s "
          f"blender={old_bl}->{res['seconds']}s fails={[k for k, v in r['checks'].items() if not v['ok']]}",
          flush=True)
    return r


def summarize(run_dir, results, label):
    results.sort(key=lambda r: r["id"])
    rep = {"run": run_dir.name, "label": label, "backend": llm.BACKEND, "model": llm.KIMI, "n": len(results),
           "pass_rate": round(sum(r["pass"] for r in results) / max(1, len(results)), 3),
           "mean_score": round(sum(r["score"] for r in results) / max(1, len(results)), 3),
           "first_try_runs": sum(1 for r in results if r["attempts"] and r["attempts"][0]["ok"]),
           "results": results}
    (run_dir / "report.json").write_text(json.dumps(rep, indent=1))
    has_bl = any("blender_new" in r for r in results)
    lines = [f"# Forge eval {run_dir.name} — {label}", "",
             f"backend `{llm.BACKEND}`, model `{llm.KIMI}`; pass **{rep['pass_rate']:.0%}**, mean score "
             f"**{rep['mean_score']:.2f}**, scripts that ran first try: {rep['first_try_runs']}/{len(results)}", "",
             "| id | score | attempts | wall s |" + (" blender s old→new |" if has_bl else "") + " failed checks |",
             "|---|---|---|---|" + ("---|" if has_bl else "") + "---|"]
    for r in results:
        bad = [f"{k}: {v['detail']}" for k, v in r["checks"].items() if not v["ok"]]
        row = f"| {r['id']} | {r['score']:.2f} | {len(r['attempts'])} | {r['wall']} |"
        if has_bl:
            row += f" {r.get('blender_old')}→{r.get('blender_new')} |"
        lines.append(row + f" {'<br>'.join(bad) or '—'} |")
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


async def main_async(a):
    sel = [q for q in QUERIES if (not a.ids or q["id"] in a.ids) and (a.split == "all" or q.get("split", "core") == a.split)]
    run_dir = ROOT / "out" / "evals" / ("forge-" + time.strftime("%Y%m%d-%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(a.parallel)
    if a.rerun:
        skipped = [q["id"] for q in sel if not (forge.FORGE / q["id"] / "scene.py").exists()]
        results = [r for r in await asyncio.gather(*[one_rerun(q, sem) for q in sel]) if r]
        if skipped:
            print("skipped (no saved scene.py):", ", ".join(skipped))
    else:
        results = await asyncio.gather(*[one(q, sem, run_dir) for q in sel])
    summarize(run_dir, list(results), a.label)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--split", choices=["core", "hard", "all"], default="all")
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--rerun", action="store_true",
                    help="re-run saved out/forge/<id>/scene.py scripts (no Kimi call)")
    ap.add_argument("--label", default="")
    asyncio.run(main_async(ap.parse_args()))
