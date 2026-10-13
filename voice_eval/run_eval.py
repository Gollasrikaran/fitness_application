"""Send every test clip to every chosen model, score it, write the results.

    python -m voice_eval.run_eval                          # all providers
    python -m voice_eval.run_eval --providers sarvam-v4    # just one
    python -m voice_eval.run_eval --limit 3                # first 3 clips (cheap smoke test)

Reads voice_eval/references.csv + voice_eval/recordings/, writes
voice_eval/results/<timestamp>_clips.csv (one row per clip x provider) and
<timestamp>_summary.csv, and prints the summary.
"""
from __future__ import annotations

import argparse
import csv
import shutil
import statistics
import subprocess
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from voice_eval.providers import api_key_for, build_providers
from voice_eval.scoring import key_term_hits, wer

ROOT = Path(__file__).resolve().parent
RECORDINGS = ROOT / "recordings"
REFERENCES = ROOT / "references.csv"
RESULTS = ROOT / "results"

# The group whose misses rule a model out (decision rule in the evaluation plan).
WARNING_GROUP = "warning"


def audio_seconds(path: Path) -> float | None:
    """Clip length, for cost. WAV needs nothing extra; other formats (phone
    .m4a etc.) need ffprobe on PATH — without it cost is just left blank."""
    if path.suffix.lower() == ".wav":
        with wave.open(str(path)) as w:
            return w.getnframes() / w.getframerate()
    if shutil.which("ffprobe"):
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True,
        )
        try:
            return float(out.stdout.strip())
        except ValueError:
            return None
    return None


def load_references() -> list[dict]:
    if not REFERENCES.exists():
        sys.exit("No voice_eval/references.csv yet - copy references.example.csv and fill it in.")
    with REFERENCES.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("clip", "").strip()]
    missing = [r["clip"] for r in rows if not (RECORDINGS / r["clip"]).exists()]
    if missing:
        sys.exit(f"Listed in references.csv but not in recordings/: {', '.join(missing)}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--providers", help="comma-separated; default = all")
    parser.add_argument("--limit", type=int, help="only the first N clips")
    parser.add_argument("--language", default="unknown",
                        help="language hint passed to providers that take one (e.g. hi-IN)")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    available = build_providers(language_code=args.language)
    names = args.providers.split(",") if args.providers else list(available)
    unknown = [n for n in names if n not in available]
    if unknown:
        sys.exit(f"Unknown provider(s): {', '.join(unknown)}. Available: {', '.join(available)}")
    providers = [available[n] for n in names]
    keys = {p.name: api_key_for(p) for p in providers}  # fail before spending anything

    refs = load_references()[: args.limit]
    rows = []
    for provider in providers:
        for ref in refs:
            path = RECORDINGS / ref["clip"]
            seconds = audio_seconds(path)
            start = time.perf_counter()
            transcript, error = "", ""
            try:
                transcript = provider.transcribe(path, keys[provider.name])
            except Exception as exc:  # one bad clip shouldn't end the run
                error = str(exc)
            latency = time.perf_counter() - start
            hits, total, missed = key_term_hits(transcript, ref.get("key_terms", ""))
            rows.append({
                "provider": provider.name,
                "clip": ref["clip"],
                "group": ref.get("group", ""),
                "reference": ref["reference"],
                "transcript": transcript,
                "wer": "" if error else round(wer(ref["reference"], transcript), 3),
                "key_hits": hits,
                "key_total": total,
                "missed_terms": "|".join(missed),
                "latency_s": round(latency, 2),
                "audio_s": "" if seconds is None else round(seconds, 2),
                "cost_usd": "" if seconds is None else round(seconds / 3600 * provider.usd_per_audio_hour, 6),
                "error": error,
            })
            status = f"ERROR {error[:80]}" if error else f"{hits}/{total} key terms"
            print(f"[{provider.name}] {ref['clip']}: {status}")

    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _write_csv(RESULTS / f"{stamp}_clips.csv", rows)
    summary = summarize(rows, [p.name for p in providers])
    _write_csv(RESULTS / f"{stamp}_summary.csv", summary)
    _print_table(summary)
    print(f"\nWrote {RESULTS / f'{stamp}_clips.csv'} and _summary.csv")


def summarize(rows: list[dict], provider_names: list[str]) -> list[dict]:
    out = []
    for name in provider_names:
        mine = [r for r in rows if r["provider"] == name]
        ok = [r for r in mine if not r["error"]]
        hits = sum(r["key_hits"] for r in ok)
        total = sum(r["key_total"] for r in ok)
        costs = [r["cost_usd"] for r in ok if r["cost_usd"] != ""]
        warning_misses = sum(1 for r in mine if r["group"] == WARNING_GROUP
                             and (r["error"] or r["key_hits"] < r["key_total"]))
        out.append({
            "provider": name,
            "clips_ok": len(ok),
            "errors": len(mine) - len(ok),
            "key_term_accuracy": f"{hits / total:.1%}" if total else "",
            "mean_wer": f"{statistics.mean(r['wer'] for r in ok):.1%}" if ok else "",
            "median_latency_s": round(statistics.median(r["latency_s"] for r in ok), 2) if ok else "",
            "usd_per_1000_clips": round(statistics.mean(costs) * 1000, 2) if costs else "",
            "warning_misses": warning_misses,
        })
    return out


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _print_table(rows: list[dict]) -> None:
    if not rows:
        return
    cols = list(rows[0])
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    print("\n" + "  ".join(c.ljust(widths[c]) for c in cols))
    for r in rows:
        print("  ".join(str(r[c]).ljust(widths[c]) for c in cols))


if __name__ == "__main__":
    main()
