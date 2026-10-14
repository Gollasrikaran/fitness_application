"""OpenRouter chat-completions client that returns parsed JSON."""
from __future__ import annotations

import json
import re

import httpx

from app.config import settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(Exception):
    pass


def complete_json(messages: list[dict]) -> dict:
    if not settings.openrouter_api_key:
        raise LLMError("OPENROUTER_API_KEY is not set")
    try:
        resp = httpx.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}",
                     "X-Title": "VitaInspire medical agent"},
            json={"model": settings.llm_model, "messages": messages, "temperature": 0.2,
                  "max_tokens": 900, "response_format": {"type": "json_object"}},
            timeout=settings.llm_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise LLMError(f"network error: {exc.__class__.__name__}") from exc
    if resp.status_code != 200:
        raise LLMError(f"OpenRouter HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        content = resp.json()["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMError("unexpected response shape") from exc
    return parse_json(content)


def parse_json(content: str) -> dict:
    """Accepts bare JSON or JSON wrapped in a ```json fence."""
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError("model did not return valid JSON") from exc
    if not isinstance(data, dict):
        raise LLMError("model returned JSON that is not an object")
    return data
