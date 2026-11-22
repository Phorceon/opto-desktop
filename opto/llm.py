"""Cerebras client. Kimi K3.1 is the backbone; gpt-oss-120b is the optional fast drafter."""

from __future__ import annotations

import json
import os
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Iterator

import httpx

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.cerebras.ai/v1/chat/completions"


def _load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

KIMI = os.environ.get("OPTO_MODEL", "moonshotai-kimi-k3.1-pro-trial")
FAST = os.environ.get("OPTO_FAST_MODEL", "gpt-oss-120b")
# "openclaw" (default): every call goes through the local OpenClaw gateway's agent harness
#   (POST /v1/chat/completions, model openclaw/default, backend pinned with x-openclaw-model).
# "direct": call Cerebras directly (exposes Cerebras queue/completion timing).
BACKEND = os.environ.get("OPTO_BACKEND", "openclaw")
OPENCLAW_URL = os.environ.get("OPENCLAW_URL", "http://127.0.0.1:18789/v1/chat/completions")


# set by a caller (the server's SSE stream) to hear about queue retries live
ON_RETRY: ContextVar = ContextVar("opto_on_retry", default=None)


def openclaw_token() -> str:
    tok = os.environ.get("OPENCLAW_GATEWAY_TOKEN")
    if tok:
        return tok
    cfg = Path.home() / ".openclaw" / "openclaw.json"
    return json.loads(cfg.read_text())["gateway"]["auth"]["token"]


def _endpoint(model: str) -> tuple[str, dict, dict]:
    """(url, headers, body overrides) for the active backend."""
    if BACKEND == "openclaw":
        return (OPENCLAW_URL,
                {"Authorization": f"Bearer {openclaw_token()}", "x-openclaw-model": f"cerebras/{model}"},
                {"model": "openclaw/default"})
    return API, {"Authorization": f"Bearer {api_key()}"}, {}


def api_key() -> str:
    k = os.environ.get("CEREBRAS_API_KEY")
    if not k:
        raise RuntimeError("CEREBRAS_API_KEY missing (put it in operation-opto/.env)")
    return k


@dataclass
class Stats:
    model: str
    t_start: float = field(default_factory=time.time)
    t_first: float | None = None       # first content token (wall clock)
    t_end: float | None = None
    queue_time: float | None = None    # Cerebras server-side
    completion_time: float | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    prompt_tokens: int | None = None
    error: str | None = None
    backend: str = "direct"

    def as_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["ttft"] = round(self.t_first - self.t_start, 3) if self.t_first else None
        d["total"] = round(self.t_end - self.t_start, 3) if self.t_end else None
        return d

    def _absorb(self, chunk: dict) -> None:
        u = chunk.get("usage")
        if u:
            self.completion_tokens = u.get("completion_tokens")
            self.prompt_tokens = u.get("prompt_tokens")
            self.reasoning_tokens = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
        ti = chunk.get("time_info")
        if ti:
            self.queue_time = ti.get("queue_time")
            self.completion_time = ti.get("completion_time")


def _body(model: str, messages: list[dict], max_tokens: int, stream: bool, effort: str | None) -> dict:
    b = {"model": model, "messages": messages, "max_completion_tokens": max_tokens, "stream": stream}
    if stream:
        b["stream_options"] = {"include_usage": True}
    if effort:
        b["reasoning_effort"] = effort
    return b


def _effort_for(model: str, effort: str | None) -> str | None:
    if effort is not None:
        return effort
    return "low" if model == FAST else "low"


async def astream(messages: list[dict], model: str = KIMI, max_tokens: int = 12000,
                  effort: str | None = None, stats: Stats | None = None,
                  timeout: float = 600) -> AsyncIterator[str]:
    """Yield content deltas. Fills `stats` as it goes."""
    st = stats or Stats(model)
    st.backend = BACKEND
    url, headers, override = _endpoint(model)
    body = _body(model, messages, max_tokens, True, None if BACKEND == "openclaw" else _effort_for(model, effort))
    body.update(override)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=20)) as client:
        max_attempts = 45
        for attempt in range(max_attempts):
            try:
                async with client.stream("POST", url, headers=headers, json=body) as r:
                    if r.status_code == 429 or r.status_code >= 500:
                        st.error = f"HTTP {r.status_code}: {(await r.aread())[:200]!r}"
                        raise httpx.HTTPStatusError(st.error, request=r.request, response=r)
                    if r.status_code != 200:
                        st.error = f"HTTP {r.status_code}: {(await r.aread())[:300]!r}"
                        st.t_end = time.time()
                        return
                    yielded = False
                    async for line in r.aiter_lines():
                        if not line.startswith("data: ") or line == "data: [DONE]":
                            continue
                        chunk = json.loads(line[6:])
                        if chunk.get("error"):
                            st.error = json.dumps(chunk["error"])[:300]
                            continue
                        st._absorb(chunk)
                        for c in chunk.get("choices", []):
                            txt = (c.get("delta") or {}).get("content")
                            if txt:
                                if st.t_first is None:
                                    st.t_first = time.time()
                                yielded = True
                                yield txt
                    if not yielded and (st.error or attempt < max_attempts - 1):
                        st.error = st.error or "empty response (upstream queue/rate-limit)"
                        raise httpx.TransportError(st.error)
                    st.error = None
                    st.t_end = time.time()
                    return
            except (httpx.HTTPStatusError, httpx.TransportError) as e:
                st.error = st.error or repr(e)
                if attempt == max_attempts - 1:
                    st.t_end = time.time()
                    return
                err_l = (st.error or "").lower()
                wait_s = 2.5 if "queue_exceeded" in err_l else (min(10, 3 + attempt) if ("429" in err_l or "empty" in err_l) else min(16, 2 ** min(attempt, 4)))
                if (cb := ON_RETRY.get()) is not None:
                    cb({"attempt": attempt + 1, "wait": wait_s, "error": (st.error or "")[:160]})
                if attempt == 0 or attempt % 3 == 0:
                    import sys
                    print(f"[llm] {model} retry {attempt + 1}/{max_attempts} in {wait_s:.1f}s: {st.error}", file=sys.stderr, flush=True)
                await _asleep(wait_s)


async def _asleep(s: float) -> None:
    import asyncio
    await asyncio.sleep(s)


async def acomplete(messages: list[dict], model: str = KIMI, max_tokens: int = 12000,
                    effort: str | None = None, stats: Stats | None = None) -> str:
    out = []
    async for t in astream(messages, model, max_tokens, effort, stats):
        out.append(t)
    return "".join(out)


def complete(messages: list[dict], model: str = KIMI, max_tokens: int = 12000,
             effort: str | None = None, stats: Stats | None = None) -> str:
    import asyncio
    return asyncio.run(acomplete(messages, model, max_tokens, effort, stats))
