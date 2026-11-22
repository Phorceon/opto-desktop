"""Scene generation: stream Kimi's NDJSON, normalise each line as it lands."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from pathlib import Path
from typing import AsyncIterator

from . import llm, prompts, schema

ROOT = Path(__file__).resolve().parent.parent
SCENES = ROOT / "out" / "scenes"
SCENES.mkdir(parents=True, exist_ok=True)


def slug(query: str, image_id: str | None = None) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", (query or "image").lower()).strip("_")[:44] or "scene"
    key = query.strip().lower() + (f"|img:{image_id}" if image_id else "")
    return f"{base}_{hashlib.sha1(key.encode()).hexdigest()[:6]}"


def cached(scene_id: str) -> dict | None:
    p = SCENES / f"{scene_id}.json"
    if not p.exists():
        return None
    rec = json.loads(p.read_text(encoding="utf-8"))
    raw = SCENES / f"{scene_id}.raw.txt"
    st = rec.get("stats") or {}
    if st.get("completion_tokens") is None and "est_visible_tokens" not in st and raw.exists():
        st["est_visible_tokens"] = len(raw.read_text(encoding="utf-8")) // 4
    return rec


def save(scene_id: str, query: str, scene: schema.Scene, raw: str, stats: dict,
         story: dict | None = None) -> dict:
    rec = {"id": scene_id, "query": query, "scene": scene.to_dict(), "errors": scene.errors,
           "stats": stats, "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (SCENES / f"{scene_id}.json").write_text(json.dumps(rec), encoding="utf-8")
    (SCENES / f"{scene_id}.ndjson").write_text(scene.to_ndjson(), encoding="utf-8")
    (SCENES / f"{scene_id}.raw.txt").write_text(raw, encoding="utf-8")
    if story:  # Kimi's storyboard from the same call: the video needs no second call
        (SCENES / f"{scene_id}.story.json").write_text(json.dumps(story), encoding="utf-8")
    return rec


class LineSplitter:
    """Feed streamed text; get back complete JSON objects as soon as each line closes."""

    def __init__(self) -> None:
        self.buf = ""

    def feed(self, text: str) -> list[dict]:
        self.buf += text
        out = []
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            out += schema.extract_json_objects(line)
        return out

    def flush(self) -> list[dict]:
        rest, self.buf = self.buf, ""
        return schema.extract_json_objects(rest)


async def stream_scene(query: str, model: str = llm.KIMI, context: str | None = None,
                       image_url: str | None = None, max_tokens: int = 16000,
                       reference=None) -> AsyncIterator[dict]:
    """Yields {"t": ...} normalised items, then a final {"t":"final", ...} event."""
    st = llm.Stats(model)
    builder = schema.SceneBuilder()
    splitter = LineSplitter()
    raw: list[str] = []
    story: dict | None = None
    async for chunk in llm.astream(prompts.scene_messages(query, context, image_url=image_url, reference=reference), model=model,
                                   max_tokens=max_tokens, stats=st):
        raw.append(chunk)
        for obj in splitter.feed(chunk):
            if obj.get("t") == "story":
                story = obj
                continue
            for item in builder.add(obj):
                yield item
    for obj in splitter.flush():
        if obj.get("t") == "story":
            story = obj
            continue
        for item in builder.add(obj):
            yield item
    scene = builder.finish()
    stats = st.as_dict()
    if stats.get("completion_tokens") is None:
        # OpenClaw sometimes drops usage; ~4 chars/token estimate of visible output
        stats["est_visible_tokens"] = len("".join(raw)) // 4
    yield {"t": "final", "scene": scene.to_dict(), "errors": scene.errors, "stats": stats, "story": story,
           "raw": "".join(raw), "model": model}


async def generate(query: str, model: str = llm.KIMI, context: str | None = None,
                   image_url: str | None = None) -> dict:
    final = None
    async for item in stream_scene(query, model, context, image_url=image_url):
        if item["t"] == "final":
            final = item
    assert final is not None
    return final


def scene_from_final(final: dict) -> schema.Scene:
    s = schema.Scene()
    for k, v in final["scene"].items():
        setattr(s, k, v)
    s.errors = final.get("errors", [])
    return s


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "how does a jet engine work?"
    f = asyncio.run(generate(q))
    sid = slug(q)
    save(sid, q, scene_from_final(f), f["raw"], f["stats"])
    print(sid, json.dumps(f["stats"]), len(f["scene"]["parts"]), "parts", f["errors"][:5])
