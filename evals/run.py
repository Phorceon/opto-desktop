"""Opto eval: generate every query with Kimi in parallel and score the scenes.

    uv run python evals/run.py                 # all queries
    uv run python evals/run.py jet_engine ...  # a subset
    uv run python evals/run.py --rescore RUN   # re-score saved raw outputs without calling Kimi

Writes out/evals/<run>/report.json and summary.md; scenes also land in out/scenes/ for the app.
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
from opto import generate as gen  # noqa: E402
from opto import llm, schema  # noqa: E402

QUERIES = json.loads((ROOT / "evals" / "queries.json").read_text())


def _names(scene: schema.Scene) -> str:
    bits = [p["id"].replace("_", " ") + " " + p["name"].lower() for p in scene.parts]
    bits += [l["text"].lower() for l in scene.labels]
    return " | ".join(bits).lower()


def _kw_hit(kw: str, hay: str) -> bool:
    kw = kw.lower()
    if kw in hay:
        return True
    alts = {kw.rstrip("s"), kw + "s", kw.replace(" ", "_"), kw.replace(" ", "")}
    return any(a and a in hay for a in alts)


def _inst_spheres(scene: schema.Scene):
    out = []
    for p in scene.parts:
        r = schema.part_radius(p)
        for pos, _ in schema.part_instances(p):
            out.append((p, pos, r))
    return out


def _bond_check(scene: schema.Scene) -> tuple[bool, str] | None:
    atoms = [(p, pos) for p in scene.parts if p["shape"] == "sphere" for pos, _ in schema.part_instances(p)]
    bonds = [p for p in scene.parts if "bond" in (p["id"] + p["name"]).lower() and p["shape"] in ("cylinder", "capsule")]
    if not bonds or len(atoms) < 2:
        return None
    bad = 0
    total = 0
    for b in bonds:
        h = b["size"][2] if b["shape"] == "cylinder" else b["size"][1]
        for pos, R in schema.part_instances(b):
            axis = [R[0][1], R[1][1], R[2][1]]
            for sgn in (1, -1):
                end = [pos[k] + sgn * axis[k] * h / 2 for k in range(3)]
                total += 1
                near = min(math.dist(end, apos) - ap["size"][0] for ap, apos in atoms)
                if near > 0.25:
                    bad += 1
    ok = bad <= max(0, total // 10)
    return ok, f"{total - bad}/{total} bond ends touch an atom"


def score(q: dict, scene: schema.Scene, raw: str) -> dict:
    checks: dict[str, tuple[bool, str]] = {}
    lines = [l for l in raw.splitlines() if l.strip()]
    good = sum(1 for l in lines if l.strip().startswith("{") and schema.extract_json_objects(l))
    fenced = "```" in raw
    checks["format"] = (bool(lines) and good / len(lines) >= 0.95 and not fenced,
                        f"{good}/{len(lines)} JSON lines{' (fenced!)' if fenced else ''}")
    checks["meta"] = (scene.title not in ("", "Untitled"), scene.title)
    n = len(scene.parts)
    checks["parts_range"] = (12 <= n <= 80, f"{n} part lines, "
                             f"{sum(p.get('repeat', {}).get('n', 1) for p in scene.parts)} instances")
    hay = _names(scene)
    hits = [k for k in q["must_have"] if _kw_hit(k, hay)]
    cov = len(hits) / len(q["must_have"])
    checks["coverage"] = (cov >= 0.8, f"{len(hits)}/{len(q['must_have'])} missing={sorted(set(q['must_have']) - set(hits))}")
    ni = sum(1 for p in scene.parts if p["internal"])
    if q.get("needs_internal"):
        checks["internal"] = (ni >= 3, f"{ni} internal parts")
    checks["labels"] = (5 <= len(scene.labels) <= 12, f"{len(scene.labels)} labels")
    checks["arrows"] = (2 <= len(scene.arrows) <= 6, f"{len(scene.arrows)} arrows")
    beats = scene.beats
    dos = [b["do"] for b in beats]
    ncut = dos.count("cut")
    beat_ok = 5 <= len(beats) <= 8 and dos[:1] == ["build"] and dos[-1:] == ["orbit"]
    if q.get("needs_internal"):
        beat_ok = beat_ok and ncut == 1
    focus_err = [e for e in scene.errors if e.startswith("beat focus unknown")]
    checks["beats"] = (beat_ok and not focus_err, f"{len(beats)} beats {dos} focus_err={len(focus_err)}")
    sph = _inst_spheres(scene)
    if len(sph) > 1:
        tol = 0.12 * schema.BOUND
        conn = 0
        for i, (p, pos, r) in enumerate(sph):
            if any(j != i and math.dist(pos, pos2) <= r + r2 + tol for j, (_, pos2, r2) in enumerate(sph)):
                conn += 1
        frac = conn / len(sph)
        checks["connected"] = (frac >= 0.9, f"{conn}/{len(sph)} instances touch a neighbour")
    shell = [(pos, r) for p, pos, r in sph if not p["internal"]]
    inner = [(pos, r) for p, pos, r in sph if p["internal"]]
    if shell and inner:
        lo = [min(pos[k] - r * 0.7 for pos, r in shell) for k in range(3)]
        hi = [max(pos[k] + r * 0.7 for pos, r in shell) for k in range(3)]
        pad = [(hi[k] - lo[k]) * 0.1 for k in range(3)]
        inside = sum(1 for pos, _ in inner if all(lo[k] - pad[k] <= pos[k] <= hi[k] + pad[k] for k in range(3)))
        checks["internals_inside"] = (inside / len(inner) >= 0.8, f"{inside}/{len(inner)} internal centres inside shell box")
    bc = _bond_check(scene)
    if bc:
        checks["bonds"] = bc
    other_err = [e for e in scene.errors if not e.startswith("beat focus unknown")]
    checks["clean"] = (len(other_err) <= 2, "; ".join(other_err[:4]) or "no errors")
    passed = sum(1 for ok, _ in checks.values() if ok)
    return {"id": q["id"], "score": round(passed / len(checks), 3), "pass": passed == len(checks),
            "checks": {k: {"ok": ok, "detail": d} for k, (ok, d) in checks.items()}}


async def one(q: dict, sem: asyncio.Semaphore, run_dir: Path) -> dict:
    async with sem:
        t0 = time.time()
        final = await gen.generate(q["query"])
    scene = gen.scene_from_final(final)
    (run_dir / f"{q['id']}.raw.txt").write_text(final["raw"])
    sid = q["id"]
    if scene.parts:
        gen.save(sid, q["query"], scene, final["raw"], final["stats"])
    res = score(q, scene, final["raw"])
    res["stats"] = final["stats"]
    res["wall"] = round(time.time() - t0, 2)
    st = final["stats"]
    print(f"{q['id']:28s} score={res['score']:.2f} pass={res['pass']!s:5s} queue={st.get('queue_time') or 0:6.1f}s "
          f"gen={st.get('completion_time') or 0:5.1f}s tok={st.get('completion_tokens')} err={st.get('error')}",
          flush=True)
    return res


def summarize(run_dir: Path, results: list[dict], label: str) -> None:
    results.sort(key=lambda r: r["id"])
    rep = {"run": run_dir.name, "label": label, "model": llm.KIMI, "n": len(results),
           "pass_rate": round(sum(r["pass"] for r in results) / max(1, len(results)), 3),
           "mean_score": round(sum(r["score"] for r in results) / max(1, len(results)), 3),
           "results": results}
    qs = [r["stats"].get("queue_time") for r in results if r.get("stats", {}).get("queue_time")]
    gt = [r["stats"].get("completion_time") for r in results if r.get("stats", {}).get("completion_time")]
    tk = [r["stats"].get("completion_tokens") for r in results if r.get("stats", {}).get("completion_tokens")]
    if gt:
        rep["latency"] = {"queue_median": sorted(qs)[len(qs) // 2] if qs else None,
                          "gen_median": sorted(gt)[len(gt) // 2], "tokens_median": sorted(tk)[len(tk) // 2],
                          "tok_per_s_median": sorted(t / g for t, g in zip(tk, gt) if g)[len(gt) // 2]}
    (run_dir / "report.json").write_text(json.dumps(rep, indent=1))
    lines = [f"# Eval {run_dir.name} — {label}", "",
             f"pass rate **{rep['pass_rate']:.0%}**, mean score **{rep['mean_score']:.2f}**, model `{llm.KIMI}`",
             f"latency: {json.dumps(rep.get('latency'))}", "",
             "| id | score | failed checks |", "|---|---|---|"]
    for r in results:
        bad = [f"{k}: {v['detail']}" for k, v in r["checks"].items() if not v["ok"]]
        lines.append(f"| {r['id']} | {r['score']:.2f} | {'<br>'.join(bad) or '—'} |")
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


async def main_async(args) -> None:
    if args.rescore:
        run_dir = ROOT / "out" / "evals" / args.rescore
        old = json.loads((run_dir / "report.json").read_text())
        stats = {r["id"]: r.get("stats", {}) for r in old["results"]}
        results = []
        for q in QUERIES:
            f = run_dir / f"{q['id']}.raw.txt"
            if f.exists():
                raw = f.read_text()
                r = score(q, schema.parse_text(raw), raw)
                r["stats"] = stats.get(q["id"], {})
                results.append(r)
        summarize(run_dir, results, old.get("label", "") + " (rescored)")
        return
    sel = [q for q in QUERIES if (not args.ids or q["id"] in args.ids)
           and (args.split == "all" or q.get("split", "core") == args.split)]
    run_dir = ROOT / "out" / "evals" / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(args.parallel)
    results = await asyncio.gather(*[one(q, sem, run_dir) for q in sel])
    summarize(run_dir, list(results), args.label)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--split", choices=["core", "hard", "all"], default="all")
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--label", default="")
    ap.add_argument("--rescore")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
