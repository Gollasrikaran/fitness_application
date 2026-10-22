"""Chat model on OpenRouter, through LangChain."""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

OPENROUTER_URL = "https://openrouter.ai/api/v1"
MODEL = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")


@lru_cache(maxsize=4)
def chat_model(temperature: float = 0.2, max_tokens: int = 700) -> ChatOpenAI:
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set in backend/.env")
    return ChatOpenAI(model=MODEL, base_url=OPENROUTER_URL, api_key=key, temperature=temperature,
                      max_tokens=max_tokens, timeout=45, max_retries=1,
                      default_headers={"X-Title": "VitaInspire agent testbed"})
