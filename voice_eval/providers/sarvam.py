"""Sarvam speech-to-text (https://docs.sarvam.ai/api-reference-docs/speech-to-text/transcribe.md).

REST endpoint, meant for clips under ~30 seconds — longer audio belongs on
Sarvam's Batch API, which this harness doesn't use (every test clip is short).
Billed ₹30 per hour of audio, per second (https://www.sarvam.ai/api-pricing).
"""
from __future__ import annotations

import json
import mimetypes
from pathlib import Path

import requests

URL = "https://api.sarvam.ai/speech-to-text"
INR_PER_AUDIO_HOUR = 30.0


def transcribe(path: Path, *, api_key: str, model: str, mode: str | None = None,
               language_code: str = "unknown", keyterms: list[str] | None = None,
               timeout: float = 60) -> str:
    """Returns the transcript text. Raises RuntimeError with Sarvam's own error
    message on any non-200, so a bad key or unsupported file shows up in the
    results CSV as a readable reason rather than a bare status code."""
    data = {"model": model, "language_code": language_code}
    if mode:
        # `mode` is only accepted by saaras:v3 (transcribe/translit/codemix/...).
        data["mode"] = mode
    if keyterms:
        # saaras:v4 only: up to 50 terms, 64 chars each. Biases recognition
        # toward these words but doesn't force them into the output.
        data["keyterms"] = json.dumps(keyterms[:50])

    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with path.open("rb") as f:
        resp = requests.post(
            URL,
            headers={"api-subscription-key": api_key},
            data=data,
            files={"file": (path.name, f, content_type)},
            timeout=timeout,
        )
    if resp.status_code != 200:
        try:
            message = resp.json().get("error", {}).get("message") or resp.text
        except ValueError:
            message = resp.text
        raise RuntimeError(f"Sarvam HTTP {resp.status_code}: {message[:300]}")
    return resp.json().get("transcript") or ""
