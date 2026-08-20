"""
Chunk the MedQuAD-derived RAG source files (data/rag_sources/medquad__*.md) into
overlapping, token-bounded chunks ready for embedding.

Scope: MedQuAD files ONLY. The NHS/NICE/AAOS/ICMR/WHO files in the same folder are
left untouched for now, per instruction.

Approach: sentence-aware sliding window.
  - Split each file's body into sentences (header metadata block is parsed separately
    and kept as chunk metadata, not embedded as text).
  - Greedily pack sentences into a chunk until adding the next sentence would exceed
    CHUNK_SIZE_TOKENS.
  - Start the next chunk by carrying back the trailing sentences of the previous chunk
    worth ~OVERLAP_TOKENS, so no sentence is ever cut in half and adjacent chunks share
    real context.
  - Tokens are counted with tiktoken's cl100k_base encoding (matches
    openai/text-embedding-3-small, the embedding model we've been planning to use via
    OpenRouter), so the token budget is accurate, not word-count-approximated.

Output: one JSON object per line in data/rag_chunks/medquad_chunks.jsonl.
Each chunk also gets a `medication_flagged` field (not auto-removed) listing any
medication/drug keywords found, so the medication-content review pass has something
concrete to check before these chunks go anywhere near the embedding step.
"""

import json
import re
from pathlib import Path

import tiktoken

SOURCE_DIR = Path(__file__).resolve().parent.parent / "data" / "rag_sources"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "rag_chunks" / "medquad_chunks.jsonl"

CHUNK_SIZE_TOKENS = 200
OVERLAP_TOKENS = 50

ENCODING = tiktoken.get_encoding("cl100k_base")

MEDICATION_KEYWORDS = [
    "allopurinol", "febuxostat", "probenecid", "colchicine", "pegloticase",
    "nsaid", "nsaids", "corticosteroid", "corticosteroids", "steroid injection",
    "ibuprofen", "naproxen", "acetaminophen", "aspirin", "diuretic", "diuretics",
    "cyclosporine", "levodopa", "niacin", "anti-inflammatory medic", "pain reliever",
    "pain medicine", "medication", "medicine", "drug", "injection", "prescri",
]


def parse_file(path: Path):
    """Split a rag_sources file into its metadata header and its body text."""
    text = path.read_text(encoding="utf-8")
    header_text, _, body = text.partition("\n---\n")
    meta = {"source_file": path.name, "dataset": "MedQuAD", "license": "CC BY 4.0"}
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
    return meta, body.strip()


def split_sentences(body: str):
    """Sentence split that keeps markdown headers as their own units."""
    units = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            units.append(stripped)
            continue
        # Split on sentence-ending punctuation followed by a space + capital/quote,
        # but don't break list bullets apart from their own line.
        pieces = re.split(r"(?<=[.!?])\s+(?=[A-Z\"‘“-])", stripped)
        units.extend(p.strip() for p in pieces if p.strip())
    return units


def token_len(text: str) -> int:
    return len(ENCODING.encode(text))


def chunk_sentences(sentences):
    """Greedy pack sentences into token-bounded chunks with trailing overlap."""
    chunks = []
    current = []
    current_tokens = 0

    i = 0
    while i < len(sentences):
        sentence = sentences[i]
        sentence_tokens = token_len(sentence)

        if current and current_tokens + sentence_tokens > CHUNK_SIZE_TOKENS:
            chunks.append(list(current))
            # Build overlap: walk backwards from the end of the current chunk,
            # collecting whole sentences until we've covered OVERLAP_TOKENS.
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
            continue  # re-evaluate this sentence against the new (overlapped) chunk

        current.append(sentence)
        current_tokens += sentence_tokens
        i += 1

    if current:
        chunks.append(current)

    return [" ".join(c) for c in chunks]


def flag_medications(text: str):
    lowered = text.lower()
    hits = sorted({kw for kw in MEDICATION_KEYWORDS if kw in lowered})
    return hits


def main():
    files = sorted(SOURCE_DIR.glob("medquad__*.md"))
    if not files:
        print("No medquad__*.md files found in", SOURCE_DIR)
        return

    all_chunks = []
    for path in files:
        meta, body = parse_file(path)
        sentences = split_sentences(body)
        chunk_texts = chunk_sentences(sentences)

        for idx, chunk_text in enumerate(chunk_texts):
            hits = flag_medications(chunk_text)
            record = {
                "chunk_id": f"{path.stem}__chunk{idx}",
                **meta,
                "chunk_index": idx,
                "chunk_count": len(chunk_texts),
                "token_count": token_len(chunk_text),
                "medication_flagged": hits,
                "text": chunk_text,
            }
            all_chunks.append(record)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for record in all_chunks:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Chunked {len(files)} MedQuAD files into {len(all_chunks)} chunks -> {OUTPUT_PATH}")
    print()
    by_condition = {}
    flagged_count = 0
    for r in all_chunks:
        by_condition.setdefault(r["condition_code"], 0)
        by_condition[r["condition_code"]] += 1
        if r["medication_flagged"]:
            flagged_count += 1

    for cond, count in sorted(by_condition.items()):
        print(f"  {cond:20s} {count} chunk(s)")
    print()
    print(f"  {flagged_count}/{len(all_chunks)} chunks flagged with medication-related keywords (not removed — needs human review)")
    token_counts = [r["token_count"] for r in all_chunks]
    print(f"  token count range: {min(token_counts)}-{max(token_counts)} (target {CHUNK_SIZE_TOKENS}, overlap {OVERLAP_TOKENS})")


if __name__ == "__main__":
    main()
