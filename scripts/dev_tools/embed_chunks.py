"""
Reads the two reviewed chunk files (data/rag_chunks/medquad_chunks_reviewed.jsonl and
other_sources_chunks_reviewed.jsonl), embeds each chunk's text via OpenRouter
(openai/text-embedding-3-small), and upserts into the rag_chunks table on Supabase.

Idempotent: re-running updates existing rows (matched by chunk_id) rather than
duplicating them, so this is safe to re-run after fixing a chunk's content.
"""

import json
import sys
from pathlib import Path

import psycopg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))  # so `import app.rag...` resolves when run as a script

from app.rag.vectorstore import embed_text, vector_literal  # noqa: E402

ENV_PATH = ROOT / ".env.dev"
CHUNK_FILES = [
    ROOT / "data" / "rag_chunks" / "medquad_chunks_reviewed.jsonl",
    ROOT / "data" / "rag_chunks" / "other_sources_chunks_reviewed.jsonl",
]

DATASET_BY_SUFFIX = {
    "medquad": "MedQuAD", "nhs": "NHS", "nice": "NICE",
    "aaos": "AAOS", "icmr": "ICMR", "who": "WHO",
}


def load_chunks():
    records = []
    for path in CHUNK_FILES:
        if not path.exists():
            print(f"Missing {path}, skipping.")
            continue
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records


def dataset_for(record):
    if record.get("source_file", "").startswith("medquad__"):
        return "MedQuAD"
    label = record.get("source_label", "")
    return DATASET_BY_SUFFIX.get(label, label or "unknown")


def main():
    env = dotenv_values(ENV_PATH)
    api_key = env["OPENROUTER_API_KEY"]
    db_url = env["SUPABASE_DIRECT_URL"].replace("postgresql+psycopg://", "postgresql://")

    records = load_chunks()
    print(f"Loaded {len(records)} chunks to embed.")

    upsert_sql = """
        insert into rag_chunks (
            chunk_id, dataset, source_file, source_note, url, license,
            condition_code, condition_display, date_collected,
            chunk_index, chunk_count, token_count, text, embedding
        ) values (
            %(chunk_id)s, %(dataset)s, %(source_file)s, %(source_note)s, %(url)s, %(license)s,
            %(condition_code)s, %(condition_display)s, %(date_collected)s,
            %(chunk_index)s, %(chunk_count)s, %(token_count)s, %(text)s, %(embedding)s
        )
        on conflict (chunk_id) do update set
            dataset = excluded.dataset,
            source_file = excluded.source_file,
            source_note = excluded.source_note,
            url = excluded.url,
            license = excluded.license,
            condition_code = excluded.condition_code,
            condition_display = excluded.condition_display,
            date_collected = excluded.date_collected,
            chunk_index = excluded.chunk_index,
            chunk_count = excluded.chunk_count,
            token_count = excluded.token_count,
            text = excluded.text,
            embedding = excluded.embedding;
    """

    # Found live (code audit): this used to embed and upsert every record
    # inside ONE transaction, committed once at the very end. embed_text is a
    # real, rate-limited, paid API call — if it failed partway through a
    # large batch (a realistic outcome, not a rare one), the whole
    # transaction rolled back on exit, losing every already-embedded row in
    # that run, and a re-run had to re-call (and re-pay for) the embedding
    # API for chunks that had already succeeded. Now: commit after every row
    # (Postgres itself is the checkpoint — already-upserted rows survive a
    # later crash), and skip re-embedding a chunk_id that's already present
    # with a real embedding, so a re-run only pays for what's actually left.
    already_done = set()
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("select chunk_id from rag_chunks where embedding is not null")
            already_done = {row[0] for row in cur.fetchall()}
    if already_done:
        print(f"Resuming: {len(already_done)} chunk(s) already embedded — skipping those.")

    done = skipped = 0
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            for record in records:
                if record["chunk_id"] in already_done:
                    skipped += 1
                    continue
                embedding = embed_text(record["text"], api_key)
                cur.execute(upsert_sql, {
                    "chunk_id": record["chunk_id"],
                    "dataset": dataset_for(record),
                    "source_file": record.get("source_file"),
                    "source_note": record.get("source_note"),
                    "url": record.get("url"),
                    "license": record.get("license"),
                    "condition_code": record.get("condition_code"),
                    "condition_display": record.get("condition_display"),
                    "date_collected": record.get("date_collected"),
                    "chunk_index": record.get("chunk_index"),
                    "chunk_count": record.get("chunk_count"),
                    "token_count": record.get("token_count"),
                    "text": record["text"],
                    "embedding": vector_literal(embedding),
                })
                conn.commit()  # durable immediately — a later failure never loses this row
                done += 1
                if done % 20 == 0 or done + skipped == len(records):
                    print(f"  {done + skipped}/{len(records)} done ({done} embedded, {skipped} skipped)")

    print(f"Done. {done} chunk(s) newly embedded, {skipped} already up to date.")


if __name__ == "__main__":
    main()
