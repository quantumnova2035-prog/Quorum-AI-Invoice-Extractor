"""Multi-provider LLM router with fallback and retries.

Free tiers rate-limit constantly, so a single provider is not enough - not even
a single model on a single provider, since each ":free" model on OpenRouter sits
behind its own upstream with its own shared rate-limit pool. This tries every
model in OPENROUTER_MODELS in sequence, then Groq, then Google AI Studio, and
returns the first success. Written once here, reused across every project in
the plan.
"""
from __future__ import annotations
import asyncio, json, re, time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from . import config


class AllProvidersFailed(RuntimeError):
    pass


@dataclass
class LLMCall:
    """One successful completion, plus what it took to get there.

    `latency_ms` is the successful request alone. `wasted_ms` is everything
    spent before it on providers that refused - failed requests plus the
    backoff sleeps between them. They are kept apart on purpose: a document
    that took 6s because the model is slow and a document that took 6s
    because it was rate-limited twice first are different problems, and
    collapsing them into one number hides the one you can actually fix.
    """
    data: dict[str, Any]
    provider: str
    model: str
    latency_ms: float = 0.0
    wasted_ms: float = 0.0
    attempts: int = 1              # total HTTP requests made, including failures
    # None means "not known", which is different from 0.0 meaning "free". A
    # provider that reports tokens but not price leaves cost_usd None rather
    # than implying the request was free.
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    cost_is_estimated: bool = False   # True = derived from a price table, not billed


_SECRET_IN_URL = re.compile(r"([?&](?:key|api_key|access_token)=)[^&\s'\"]+", re.I)


@dataclass(frozen=True)
class ByoKey:
    """A key the caller supplied for this one request.

    It lives for the lifetime of a single HTTP request and nothing else: never
    written to disk, never stored with the document, never logged, and redacted
    out of error text exactly like the server's own keys. It is threaded
    explicitly down the call chain rather than parked in a module global or a
    context variable, so every function that can see it says so in its
    signature - the property you want when the value is a credential belonging
    to somebody else.
    """
    api_key: str
    model: str


def _redact(text: str, byo: Optional["ByoKey"] = None) -> str:
    """Strip credentials out of anything that might be logged or surfaced.

    Gemini takes its key as a URL query parameter, so an httpx error message
    contains the full key verbatim. That message ends up in logs, in API error
    responses, and in terminal scrollback - so it must never carry the secret.
    """
    text = _SECRET_IN_URL.sub(r"\1***REDACTED***", text)
    # A caller-supplied key travels the same path. It is somebody else's
    # credential passing through our process, which makes leaking it into a log
    # worse than leaking our own, not better.
    secrets = [config.OPENROUTER_API_KEY, config.GROQ_API_KEY, config.GOOGLE_API_KEY]
    if byo:
        secrets.append(byo.api_key)
    for secret in secrets:
        if secret and len(secret) > 8:
            text = text.replace(secret, "***REDACTED***")
    return text


@dataclass
class Provider:
    name: str
    url: str
    model: str
    api_key: str
    style: str = "openai"      # openai | gemini

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def supports_vision(self) -> bool:
        """Sending images to a text-only model wastes a call and 404s or silently
        drops the image, so scans skip these providers entirely."""
        return self.model not in config.TEXT_ONLY_MODELS


def _providers(byo: Optional[ByoKey] = None) -> list[Provider]:
    """The chain to try, in order.

    With a caller-supplied key this returns exactly one provider and no
    fallback. That is deliberate: silently falling back to the server's own
    keys would spend our quota on their request and, worse, would record the
    model and cost of a call the user did not choose. A wrong key or a retired
    model needs to be reported, not quietly rescued.
    """
    if byo:
        short = byo.model.split("/", 1)[-1].removesuffix(":free")
        return [Provider(f"openrouter:{short}",
                         "https://openrouter.ai/api/v1/chat/completions",
                         byo.model, byo.api_key)]

    providers = []
    for model in config.OPENROUTER_MODELS:
        # Each free ":free" model on OpenRouter is usually served by a different
        # upstream (visible as "provider_name" in a 429 body) with its own
        # separate shared rate-limit pool. Trying several in sequence survives
        # one pool being saturated - the failure mode a 60-invoice batch hits
        # in practice - without paying for anything.
        short = model.split("/", 1)[-1].removesuffix(":free")
        providers.append(Provider(f"openrouter:{short}",
                                  "https://openrouter.ai/api/v1/chat/completions",
                                  model, config.OPENROUTER_API_KEY))
    providers.append(Provider("groq", "https://api.groq.com/openai/v1/chat/completions",
                              config.GROQ_MODEL, config.GROQ_API_KEY))
    providers.append(Provider(
        "google",
        f"https://generativelanguage.googleapis.com/v1beta/models/{config.GOOGLE_MODEL}:generateContent",
        config.GOOGLE_MODEL, config.GOOGLE_API_KEY, style="gemini"))
    return providers


def available_providers() -> list[str]:
    return [p.name for p in _providers() if p.available]


def _build_request(p: Provider, system: str, user: str, temperature: float,
                   images: Optional[list[str]] = None):
    images = images or []
    if p.style == "gemini":
        parts: list[dict] = [{"text": user}]
        parts += [{"inline_data": {"mime_type": "image/png", "data": b}} for b in images]
        return (
            f"{p.url}?key={p.api_key}",
            {"Content-Type": "application/json"},
            {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"temperature": temperature,
                                     "responseMimeType": "application/json"},
            },
        )
    headers = {"Authorization": f"Bearer {p.api_key}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "model": p.model,
        "temperature": temperature,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": _user_content(user, images)}],
        "response_format": {"type": "json_object"},
    }
    if p.name.startswith("openrouter"):
        headers["HTTP-Referer"] = "http://localhost"
        headers["X-Title"] = "Quorum AI"
        # Ask for the real charged cost rather than estimating it. This is the
        # check that would have caught `openai/gpt-oss-20b` quietly billing for
        # a model assumed to be free.
        payload["usage"] = {"include": True}
    return p.url, headers, payload


def _user_content(user: str, images: list[str]):
    """OpenAI-style multimodal content; plain string when there are no images."""
    if not images:
        return user
    content: list[dict] = [{"type": "text", "text": user}]
    for b in images:
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b}"}})
    return content


def _read_text(p: Provider, data: dict) -> str:
    if p.style == "gemini":
        return data["candidates"][0]["content"]["parts"][0]["text"]
    return data["choices"][0]["message"]["content"]


def _read_usage(p: Provider, data: dict) -> tuple[Optional[int], Optional[int],
                                                  Optional[float], bool]:
    """Pull (prompt_tokens, completion_tokens, cost_usd, cost_is_estimated).

    Any part can be None - "we don't know" is a legitimate answer here and is
    reported as such rather than being rounded down to a confident zero.
    """
    prompt = completion = None
    cost: Optional[float] = None
    estimated = False

    if p.style == "gemini":
        u = data.get("usageMetadata") or {}
        prompt = u.get("promptTokenCount")
        # Reasoning ("thoughts") tokens are billed as output but are NOT
        # included in candidatesTokenCount, so leaving them out understates the
        # cost badly - on a short reply they can be 10x the visible answer.
        completion = (u.get("candidatesTokenCount") or 0) + (u.get("thoughtsTokenCount") or 0)
        completion = completion or None
    else:
        u = data.get("usage") or {}
        prompt = u.get("prompt_tokens")
        completion = u.get("completion_tokens")
        # OpenRouter returns what it actually charged, given `usage.include`.
        # This is the only genuinely authoritative cost we get anywhere.
        if isinstance(u.get("cost"), (int, float)):
            return prompt, completion, float(u["cost"]), False

    price = config.MODEL_PRICING.get(p.model)
    if price and prompt is not None and completion is not None:
        cost = (prompt * price[0] + completion * price[1]) / 1_000_000
        estimated = True
    return prompt, completion, cost, estimated


async def complete_json(system: str, user: str, temperature: float = 0.3,
                        images: Optional[list[str]] = None,
                        attempts_per_provider: int = 2,
                        byo: Optional[ByoKey] = None) -> LLMCall:
    """Return an LLMCall (parsed JSON + timing). Raises AllProvidersFailed."""
    errors: list[str] = []
    attempts = 0
    # Accumulated from failed attempts only. Deriving it as "total elapsed minus
    # the successful call" instead would fold in client setup and quietly report
    # it as retry waste on a request that never actually retried.
    wasted_ms = 0.0
    candidates = [p for p in _providers(byo) if p.available]
    if images:
        vision = [p for p in candidates if p.supports_vision]
        if not vision:
            raise AllProvidersFailed(
                f"This document is a scan or photo and needs a vision-capable model, "
                f"but {byo.model} is text-only. Pick a vision-capable model, or turn "
                f"your own key off to use the server's chain."
                if byo else
                "This document is a scan or photo and needs a vision-capable model, "
                "but every configured provider is text-only. Set GOOGLE_API_KEY, or "
                "add a vision-capable model to OPENROUTER_MODELS.")
        candidates = vision

    async with httpx.AsyncClient(timeout=120.0) as client:
        for p in candidates:
            for attempt in range(attempts_per_provider):
                attempts += 1
                call_started = time.perf_counter()
                try:
                    url, headers, payload = _build_request(p, system, user, temperature, images)
                    r = await client.post(url, headers=headers, json=payload)
                    if r.status_code in (429, 500, 502, 503, 529):
                        # rate limited or transient — back off, then move on
                        await asyncio.sleep(1.5 * (attempt + 1))
                        wasted_ms += (time.perf_counter() - call_started) * 1000
                        errors.append(f"{p.name}: HTTP {r.status_code}")
                        continue
                    r.raise_for_status()
                    body = r.json()
                    prompt_tok, completion_tok, cost, estimated = _read_usage(p, body)
                    return LLMCall(
                        data=_extract_json(_read_text(p, body)),
                        provider=p.name, model=p.model,
                        latency_ms=round((time.perf_counter() - call_started) * 1000, 1),
                        wasted_ms=round(wasted_ms, 1),
                        attempts=attempts,
                        prompt_tokens=prompt_tok,
                        completion_tokens=completion_tok,
                        cost_usd=cost,
                        cost_is_estimated=estimated,
                    )
                except Exception as e:  # noqa: BLE001 - we want to try the next provider
                    errors.append(f"{p.name}: {type(e).__name__}: {_redact(str(e), byo)}")
                    await asyncio.sleep(0.5)
                    wasted_ms += (time.perf_counter() - call_started) * 1000
    raise AllProvidersFailed("; ".join(errors) or "no provider configured — set a key in .env")


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _extract_json(text: str) -> dict[str, Any]:
    """Models wrap JSON in prose or fences more often than they should."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _FENCE.search(text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError(f"no JSON found in model output: {text[:200]!r}")
