"""Talks to the Supabase/pgvector database holding rag_chunks — a separate physical
database from the app's own Postgres (STRATEGY §5: keep the vector store out of the
primary datastore's blast radius). Plain psycopg, not the app's SQLAlchemy engine,
since this is a different database entirely.

This is the single canonical place these OpenRouter calls are made — scripts/
embed_chunks.py and scripts/rag_query.py both import from here rather than keeping
their own copies, so there is exactly one place the embedding/chat request shapes
can drift.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

import psycopg

EMBEDDING_MODEL = "openai/text-embedding-3-small"
EMBEDDING_URL = "https://openrouter.ai/api/v1/embeddings"
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
CHAT_MODEL = "openai/gpt-oss-20b:free"
TOP_K = 5


class UpstreamUnavailable(RuntimeError):
    """The LLM/embedding provider is rate-limited or down after retries.

    Distinct from a generic RuntimeError so callers (app/rag/service.py) can turn
    this into a proper 429 the client can act on, instead of it falling through to
    the generic 500 "Something went wrong" handler — free-tier OpenRouter models
    share capacity across everyone using them, so this is expected to happen
    occasionally, not a sign the app is broken.
    """


class ResponseTruncated(RuntimeError):
    """The model hit the max_tokens cap before naturally finishing its answer —
    a real, occasionally-observed free-model failure mode (a degenerate
    repetition loop that never reaches a natural stopping point). The response
    is cut off mid-thought, not a complete, valid answer — never usable as-is,
    whether that's for a real user or for evaluation."""


def embed_text(text: str, api_key: str, retries: int = 3) -> list[float]:
    body = json.dumps({"model": EMBEDDING_MODEL, "input": text}).encode()
    req = urllib.request.Request(
        EMBEDDING_URL,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                items = data.get("data")
                if not items or not items[0].get("embedding"):
                    detail = json.dumps(data)[:500]
                    if attempt < retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    raise UpstreamUnavailable(f"embedding provider returned no embedding: {detail}")
                return items[0]["embedding"]
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            if e.code == 429:
                raise UpstreamUnavailable("embedding provider rate-limited") from e
            raise
        except (TimeoutError, urllib.error.URLError) as e:
            # A genuine timeout/connection failure — not an HTTP error response at
            # all, so it was never caught by the except above. Previously this
            # propagated straight past every caller's UpstreamUnavailable handler
            # and crashed the whole run instead of skipping one row.
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise UpstreamUnavailable(f"embedding provider unreachable: {e}") from e
    raise UpstreamUnavailable("embed_text: exhausted retries")


def chat_complete(messages: list[dict], api_key: str, model: str = CHAT_MODEL,
                   retries: int = 5, temperature: float = 0.2, max_tokens: int = 2000) -> str:
    """CHAT_MODEL (gpt-oss-20b) is a reasoning model — it spends tokens on an
    internal "reasoning" field before writing the final answer, and both count
    against max_tokens. 600 was tuned only for the final "short, plain-
    language" answer (system prompt rule 4) and left no room for reasoning,
    causing legitimate answers to get cut off before any content was written
    at all. 2000 leaves real headroom for both, while still being a hard
    ceiling nowhere near the ~8,000+ tokens the degenerate-repetition failure
    mode produced (a 32,768-character answer)."""
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        CHAT_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "ViTAinspire",
        },
        method="POST",
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                choices = data.get("choices")
                if not choices:
                    # A 200 response with no "choices" — OpenRouter proxies many
                    # different backend providers, and some return an embedded
                    # error, an empty/moderated completion, or a differently-
                    # shaped body instead of raising an HTTP error status for it.
                    # Surface the actual body instead of a bare KeyError so the
                    # real cause (rate limit, moderation, provider outage) is
                    # visible, and treat it as retryable like a 429.
                    detail = json.dumps(data)[:500]
                    if attempt < retries - 1:
                        time.sleep(5 * (attempt + 1))
                        continue
                    raise UpstreamUnavailable(f"chat model returned no choices: {detail}")
                choice = choices[0]
                message = choice.get("message") or {}
                content = message.get("content")
                if choice.get("finish_reason") == "length":
                    # Hit the max_tokens cap before naturally finishing. Some
                    # models (this one included — "reasoning" models like
                    # gpt-oss) spend tokens on an internal "reasoning" field
                    # before writing the final answer — if the cap is hit
                    # during that phase, content is null/empty, which is NOT
                    # the same thing as the provider returning a broken empty
                    # response (checked further below); it means the model was
                    # still working (very likely a repetition loop) when cut
                    # off. One retry in case it was a one-off; a second
                    # truncation means give up on this row rather than accept
                    # an incomplete, unusable answer.
                    if attempt < retries - 1:
                        time.sleep(2)
                        continue
                    raise ResponseTruncated(
                        f"chat model hit max_tokens ({max_tokens}) without finishing — "
                        f"likely a repetition loop, not a valid answer"
                    )
                if not content:
                    detail = json.dumps(data)[:500]
                    raise UpstreamUnavailable(f"chat model returned empty content: {detail}")
                return content
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            detail = e.read().decode(errors="replace")
            if e.code == 429:
                raise UpstreamUnavailable(f"chat model rate-limited: {detail[:300]}") from e
            raise RuntimeError(f"chat_complete failed: {e.code} {detail[:300]}") from e
        except (TimeoutError, urllib.error.URLError) as e:
            # A genuine timeout/connection failure, not an HTTP error response —
            # previously uncaught here, so it propagated straight past
            # ragas_eval.py's per-row UpstreamUnavailable handler and would have
            # crashed the whole run on the first slow/dropped request instead of
            # skipping just that one row.
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise UpstreamUnavailable(f"chat model unreachable: {e}") from e
    raise UpstreamUnavailable("chat_complete: exhausted retries")


def vector_literal(values: list[float]) -> str:
    # pgvector's text input format: '[0.1,0.2,...]'
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def retrieve_chunks(question: str, condition_codes: list[str], *, rag_db_url: str,
                     api_key: str, top_k: int = TOP_K) -> list[dict]:
    """Nearest chunks scoped to whichever of the user's selected conditions we have
    RAG content for, plus the general WHO physical-activity content as a baseline
    (5.2 — "the user's selected conditions", so this never searches conditions the
    user didn't report)."""
    vec_str = vector_literal(embed_text(question, api_key))
    scoped_codes = list(dict.fromkeys([*condition_codes, "general"]))

    with psycopg.connect(rag_db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select chunk_id, source_note, url, text,
                       1 - (embedding <=> %s::vector) as similarity
                from rag_chunks
                where condition_code = any(%s)
                order by embedding <=> %s::vector
                limit %s;
                """,
                (vec_str, scoped_codes, vec_str, top_k),
            )
            rows = cur.fetchall()

    return [
        {"chunk_id": r[0], "source_note": r[1], "url": r[2], "text": r[3], "similarity": float(r[4])}
        for r in rows
    ]
