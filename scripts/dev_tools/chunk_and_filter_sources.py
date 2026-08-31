"""
Replaces chunk_sources.py + trim_sources_medication.py with a single correct
pipeline for the remaining rag_sources files (everything except medquad__*.md and
the still-excluded spinal_stenosis__nice.md).

The earlier two-stage approach (chunk first, filter after) had a real bug: once
sentences are joined into chunk text with spaces, the newline boundaries that used
to separate bullets/headers are gone. Re-splitting that joined text caused two
failures: (1) bulleted lists collapse into one "sentence" so one medication bullet
deletes the whole list, and (2) any chunk whose text starts with "#" swallows
everything after it as a single unit, skipping sentence-splitting entirely.

Fix: filter medication sentences OUT of the sentence list BEFORE chunking, while
the file's real newlines still give correct sentence/bullet/header boundaries.
Chunks are then built only from the sentences that survived the filter, so every
emitted chunk is clean by construction — no post-hoc re-splitting needed.

Output:
  data/rag_chunks/other_sources_chunks_reviewed.jsonl  (final, clean chunks)
  data/rag_chunks/other_sources_removed_sentences.log  (every dropped sentence, for audit)
"""

import json
import re
from pathlib import Path

import tiktoken

SOURCE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "rag_sources"
OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "rag_chunks" / "other_sources_chunks_reviewed.jsonl"
LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "rag_chunks" / "other_sources_removed_sentences.log"

EXCLUDED_FILES = {"spinal_stenosis__nice.md"}

CHUNK_SIZE_TOKENS = 200
OVERLAP_TOKENS = 50

ENCODING = tiktoken.get_encoding("cl100k_base")

MEDICATION_KEYWORDS = [
    "allopurinol", "febuxostat", "probenecid", "colchicine", "pegloticase",
    "nsaid", "nsaids", "corticosteroid", "corticosteroids", "steroid injection",
    "ibuprofen", "naproxen", "acetaminophen", "aspirin", "diuretic", "diuretics",
    "cyclosporine", "levodopa", "niacin", "anti-inflammatory medic", "pain reliever",
    "pain medicine", "medication", "medications", "medicine", "medicines", "drug",
    "drugs", "injection", "injections", "opioid", "paracetamol",
    "codeine", "tramadol", "gabapentin", "pregabalin", "il-1 inhibitor", "biologic",
    "prescribed medic", "prescription medic", "prescription-strength",
]


def parse_file(path: Path):
    text = path.read_text(encoding="utf-8")
    header_text, _, body = text.partition("\n---\n")
    meta = {"source_file": path.name}
    for line in header_text.splitlines():
        if line.startswith("Source:"):
            meta["source_note"] = line[len("Source:"):].strip()
        elif line.startswith("URL:"):
            meta["url"] = line[len("URL:"):].strip()
        elif line.startswith("Condition:"):
            value = line[len("Condition:"):].strip()
            match = re.match(r"(\S+)\s*\((.+)\)", value)
            if match:
                meta["condition_code"] = match.group(1)
                meta["condition_display"] = match.group(2)
            else:
                meta["condition_code"] = value
        elif line.startswith("Date collected:"):
            meta["date_collected"] = line[len("Date collected:"):].strip()

    stem = path.stem
    if "__" in stem:
        meta.setdefault("source_label", stem.rsplit("__", 1)[1])
    return meta, body.strip()


def split_sentences(body: str):
    """Line-by-line split on the RAW file body — bullets and headers are each
    their own line here, so this correctly isolates them before anything gets
    joined back together."""
    units = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            units.append(stripped)
            continue
        pieces = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'‘“-])", stripped)
        units.extend(p.strip() for p in pieces if p.strip())
    return units


def token_len(text: str) -> int:
    return len(ENCODING.encode(text))


def find_hits(sentence: str):
    lowered = sentence.lower()
    return sorted({kw for kw in MEDICATION_KEYWORDS if kw in lowered})


def chunk_sentences(sentences):
    chunks = []
    current = []
    current_tokens = 0

    i = 0
    # Guards against a real, live infinite loop: if the overlap carried
    # forward from the last flush is itself large (one sizeable sentence,
    # still under CHUNK_SIZE_TOKENS alone so the check below doesn't catch
    # it), adding the SAME next sentence can overflow again, rebuild the
    # IDENTICAL overlap, and repeat forever — `i` never advances. Found live
    # against real MedQuAD content (sibling chunk_medquad.py). At most one
    # overlap-rebuild retry per sentence index; if it still doesn't fit the
    # second time, force-accept the overflow and move on rather than loop.
    retried_at = -1
    while i < len(sentences):
        sentence = sentences[i]
        sentence_tokens = token_len(sentence)

        # A single sentence longer than the whole chunk budget can never fit
        # alongside anything else, overlap or not.
        if sentence_tokens > CHUNK_SIZE_TOKENS:
            if current:
                chunks.append(list(current))
            chunks.append([sentence])
            current = []
            current_tokens = 0
            i += 1
            retried_at = -1
            continue

        if current and current_tokens + sentence_tokens > CHUNK_SIZE_TOKENS:
            if retried_at == i:
                current.append(sentence)
                current_tokens += sentence_tokens
                i += 1
                retried_at = -1
                continue
            chunks.append(list(current))
            overlap_sentences = []
            overlap_tokens = 0
            for s in reversed(current):
                t = token_len(s)
                if overlap_tokens + t > OVERLAP_TOKENS and overlap_sentences:
                    break
                overlap_sentences.insert(0, s)
                overlap_tokens += t
            current = list(overlap_sentences)
            current_tokens = overlap_tokens
            retried_at = i
            continue

        current.append(sentence)
        current_tokens += sentence_tokens
        i += 1

    if current:
        chunks.append(current)

    return [" ".join(c) for c in chunks]


def main():
    files = sorted(
        p for p in SOURCE_DIR.glob("*.md")
        if not p.name.startswith("medquad__") and p.name not in EXCLUDED_FILES
    )
    if not files:
        print("No source files found to chunk.")
        return

    all_chunks = []
    log_lines = []
    dropped_header_only_files = []

    for path in files:
        meta, body = parse_file(path)
        sentences = split_sentences(body)

        kept_sentences = []
        removed_here = []
        for s in sentences:
            hits = find_hits(s)
            if hits:
                removed_here.append((s, hits))
            else:
                kept_sentences.append(s)

        if removed_here:
            log_lines.append(f"=== {path.name} ===")
            for s, hits in removed_here:
                log_lines.append(f"  REMOVED [{', '.join(hits)}]: {s}")
            log_lines.append("")

        if not kept_sentences:
            dropped_header_only_files.append(path.name)
            continue

        chunk_texts = chunk_sentences(kept_sentences)

        for idx, chunk_text in enumerate(chunk_texts):
            record = {
                "chunk_id": f"{path.stem}__chunk{idx}",
                **meta,
                "chunk_index": idx,
                "chunk_count": len(chunk_texts),
                "token_count": token_len(chunk_text),
                "medication_flagged": find_hits(chunk_text),  # should always be []
                "text": chunk_text,
            }
            all_chunks.append(record)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for record in all_chunks:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    LOG_PATH.write_text("\n".join(log_lines), encoding="utf-8")

    print(f"Chunked {len(files)} files ({len(EXCLUDED_FILES)} pre-excluded) into {len(all_chunks)} chunks -> {OUTPUT_PATH}")
    print(f"Removed-sentence audit log -> {LOG_PATH}")
    if dropped_header_only_files:
        print(f"\nFiles that had NO non-medication content left (excluded entirely):")
        for f in dropped_header_only_files:
            print(f"  - {f}")

    print()
    by_file = {}
    for r in all_chunks:
        by_file.setdefault(r["source_file"], 0)
        by_file[r["source_file"]] += 1
    for fname, count in sorted(by_file.items()):
        print(f"  {fname:35s} {count} chunk(s)")

    remaining_flags = sum(1 for r in all_chunks if r["medication_flagged"])
    token_counts = [r["token_count"] for r in all_chunks]
    print()
    print(f"  chunks still carrying a medication-keyword hit: {remaining_flags} (should be 0)")
    print(f"  token count range: {min(token_counts)}-{max(token_counts)} (target {CHUNK_SIZE_TOKENS}, overlap {OVERLAP_TOKENS})")


if __name__ == "__main__":
    main()
