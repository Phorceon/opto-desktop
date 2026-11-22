"""Web reference lookup before the Kimi call: what does the real thing look like?

Wikipedia gives the subject + a short factual summary; Wikimedia Commons gives
real photos. Both are free, keyless and fast. The photos go to Kimi K3.1 as
image inputs in the same single call, so named products (Tesla Optimus, F-22,
a specific engine...) come out recognisable instead of generic.
"""

from __future__ import annotations

import asyncio
import base64
import io
import re
from dataclasses import dataclass, field

import httpx
from PIL import Image

WIKI = "https://en.wikipedia.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "OptoExplainer/0.1 (local 3D explainer)"}
MAX_IMAGES = 3

_FILLER = re.compile(
    r"\b(how (does|do|is|are|did)|how|what('?s| is| are)|why (does|do|is)|explain|teach me|show me|"
    r"can you|please|works?|working|inside|of|the|a|an|me|about)\b|[?.!,]",
    re.IGNORECASE,
)


@dataclass
class Reference:
    title: str = ""
    url: str = ""
    summary: str = ""
    images: list[str] = field(default_factory=list)  # data: URLs (jpeg, <=768px)


def subject_of(query: str) -> str:
    return re.sub(r"\s+", " ", _FILLER.sub(" ", query)).strip() or query


async def _get(client: httpx.AsyncClient, url: str, params: dict) -> dict:
    r = await client.get(url, params={**params, "format": "json"})
    r.raise_for_status()
    return r.json()


def _to_data_url(raw: bytes) -> str:
    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert("RGB")
        im.thumbnail((768, 768))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


async def lookup(query: str, timeout: float = 6.0) -> Reference:
    """Best effort: any failure just means fewer references, never an error."""
    ref = Reference()
    async with httpx.AsyncClient(headers=HEADERS, timeout=timeout, follow_redirects=True) as client:
        try:
            hits = (await _get(client, WIKI, {
                "action": "query", "list": "search", "srsearch": subject_of(query), "srlimit": 1,
            }))["query"]["search"]
            if not hits:
                return ref
            ref.title = hits[0]["title"]
            ref.url = "https://en.wikipedia.org/wiki/" + ref.title.replace(" ", "_")
            pages = (await _get(client, WIKI, {
                "action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1, "titles": ref.title,
            }))["query"]["pages"]
            ref.summary = next(iter(pages.values())).get("extract", "")[:1200]

            files = (await _get(client, COMMONS, {
                "action": "query", "generator": "search", "gsrnamespace": 6, "gsrsearch": ref.title,
                "gsrlimit": 8, "prop": "imageinfo", "iiprop": "url|mime", "iiurlwidth": 800,
            })).get("query", {}).get("pages", {})
            urls = [
                p["imageinfo"][0].get("thumburl") or p["imageinfo"][0]["url"]
                for p in sorted(files.values(), key=lambda p: p.get("index", 99))
                if p.get("imageinfo") and p["imageinfo"][0].get("mime") in ("image/jpeg", "image/png")
            ][:MAX_IMAGES]

            async def fetch(u: str) -> str | None:
                try:
                    r = await client.get(u)
                    r.raise_for_status()
                    return await asyncio.to_thread(_to_data_url, r.content)
                except Exception:
                    return None

            ref.images = [d for d in await asyncio.gather(*(fetch(u) for u in urls)) if d]
        except Exception:
            pass
    return ref
