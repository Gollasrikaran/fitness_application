"""The AI model, chosen in backend/.env and built with LangChain's
init_chat_model, so any provider LangChain supports works without code
changes, and every AI call is traced in LangSmith (LANGSMITH_* in .env).
The only place the agent calls the AI: the doctor chat (agent/nodes.py), the
assessment (agent/assess.py) and the plan draft (agent/draft.py).

backend/.env:
- LLM_MODEL               "provider:model", e.g. anthropic:claude-haiku-5-5 or openai:gpt-4o-mini (required)
- the provider's key      ANTHROPIC_API_KEY, OPENAI_API_KEY, ... (the provider's package must be installed:
                          langchain-anthropic, langchain-openai, ...)
- LLM_EFFORT              optional, Anthropic only: low | medium | high | xhigh | max
- ANTHROPIC_WORKSPACE_ID  optional, Anthropic only: for a key that isn't scoped to a workspace

Every failure (no key, no model, network, a refusal, an answer cut off) is
raised as an exception; the callers already fall back to the rules alone.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import TypeVar

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from pydantic import BaseModel

load_dotenv()

MODEL = os.getenv("LLM_MODEL", "").strip()
PROVIDER = MODEL.split(":", 1)[0].strip().lower() if ":" in MODEL else ""
EFFORT = os.getenv("LLM_EFFORT", "").strip().lower()
WORKSPACE_ID = os.getenv("ANTHROPIC_WORKSPACE_ID", "").strip()
MAX_TOKENS = 16000  # room for the model's thinking as well as the answer

# The key each provider needs, for a clear message when it's missing.
_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "google_genai": "GOOGLE_API_KEY",
         "mistralai": "MISTRAL_API_KEY", "groq": "GROQ_API_KEY"}

T = TypeVar("T", bound=BaseModel)


@lru_cache(maxsize=1)
def _model():
    if not PROVIDER:
        raise RuntimeError('LLM_MODEL in backend/.env must be "provider:model", e.g. anthropic:claude-haiku-5-5')
    key = _KEYS.get(PROVIDER)
    if key and not os.getenv(key):
        raise RuntimeError(f"{key} is not set in backend/.env (needed for LLM_MODEL={MODEL})")
    # No temperature: current Claude models reject it.
    options = {"max_tokens": MAX_TOKENS, "timeout": 120, "max_retries": 2}
    if PROVIDER == "anthropic":
        if EFFORT:
            options["effort"] = EFFORT
        if WORKSPACE_ID:
            options["default_headers"] = {"anthropic-workspace-id": WORKSPACE_ID}
    return init_chat_model(MODEL, **options)


def _check(message) -> None:
    """A refused or cut-off answer is a failure (Anthropic says stop_reason,
    OpenAI-style providers finish_reason)."""
    meta = message.response_metadata or {}
    stop = meta.get("stop_reason") or meta.get("finish_reason")
    if stop in ("refusal", "content_filter"):
        raise RuntimeError("the model declined the request")
    if stop in ("max_tokens", "length"):
        raise RuntimeError("the answer was cut off at max_tokens")


def ask(system: str, messages: list[dict]) -> str:
    """A plain text answer. `messages`: [{"role": "user" | "assistant", "content": str}],
    starting with a user message."""
    reply = _model().invoke([{"role": "system", "content": system}, *messages])
    _check(reply)
    return reply.text.strip()


def ask_structured(system: str, user: str, schema: type[T]) -> T:
    """An answer in the shape of `schema` (a Pydantic model), using the
    provider's own structured output (json_schema). Not a forced tool call:
    current Claude models reject that."""
    result = _model().with_structured_output(schema, method="json_schema", include_raw=True).invoke(
        [{"role": "system", "content": system}, {"role": "user", "content": user}])
    _check(result["raw"])
    if result["parsed"] is None:
        raise RuntimeError(f"the model's answer didn't fit the schema: {result.get('parsing_error')}")
    return result["parsed"]
