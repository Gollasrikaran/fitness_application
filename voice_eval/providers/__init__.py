"""Every model under test, behind one shape: audio file in, transcript out.

Adding a vendor = one module in this folder + one entry in `build_providers`.
Each entry is a separate *configuration* (same vendor, different settings
count as different rows in the results), so "v4 with keyterms" can be
compared head-to-head against plain v4.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from voice_eval.keyterms import build_keyterms
from voice_eval.providers import sarvam

# Only used to put rupee-priced vendors on the same scale as dollar-priced
# ones in the summary. Not a live rate — update it if it drifts.
INR_PER_USD = 88.0


@dataclass(frozen=True)
class Provider:
    name: str
    env_key: str                       # the API key this provider needs in voice_eval/.env
    usd_per_audio_hour: float
    transcribe: Callable[[Path, str], str]   # (audio path, api key) -> transcript


def build_providers(language_code: str = "unknown") -> dict[str, Provider]:
    keyterms = build_keyterms()
    sarvam_usd = sarvam.INR_PER_AUDIO_HOUR / INR_PER_USD

    return {
        "sarvam-v4": Provider(
            "sarvam-v4", "SARVAM_API_KEY", sarvam_usd,
            lambda p, k: sarvam.transcribe(p, api_key=k, model="saaras:v4",
                                           language_code=language_code),
        ),
        "sarvam-v4-keyterms": Provider(
            "sarvam-v4-keyterms", "SARVAM_API_KEY", sarvam_usd,
            lambda p, k: sarvam.transcribe(p, api_key=k, model="saaras:v4",
                                           language_code=language_code,
                                           keyterms=keyterms),
        ),
        "sarvam-v3-codemix": Provider(
            "sarvam-v3-codemix", "SARVAM_API_KEY", sarvam_usd,
            lambda p, k: sarvam.transcribe(p, api_key=k, model="saaras:v3", mode="codemix",
                                           language_code=language_code),
        ),
    }


def api_key_for(provider: Provider) -> str:
    key = os.environ.get(provider.env_key, "").strip()
    if not key:
        raise SystemExit(
            f"{provider.name} needs {provider.env_key} in voice_eval/.env "
            f"(copy voice_eval/.env.example to voice_eval/.env and fill it in)."
        )
    return key
