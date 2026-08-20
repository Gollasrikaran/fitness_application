-- RAG chunks + embeddings table, in the Supabase Postgres instance (pgvector),
-- separate from the local app database for now (see PART2 chat log / STRATEGY_AND_OPS
-- §5 for why: no new datastore, no new backup story — this just moves the vector
-- store to where pgvector actually lives).
--
-- Run once via scripts/setup_rag_schema.py (idempotent — safe to re-run).

create extension if not exists vector;

create table if not exists rag_chunks (
    id bigserial primary key,
    chunk_id text not null unique,
    dataset text not null,               -- 'MedQuAD', 'NHS', 'NICE', 'AAOS', 'ICMR', 'WHO'
    source_file text not null,
    source_note text,
    url text,
    license text,
    condition_code text not null,
    condition_display text,
    date_collected text,
    chunk_index int not null,
    chunk_count int not null,
    token_count int not null,
    text text not null,
    embedding vector(1536) not null,
    created_at timestamptz not null default now()
);

create index if not exists rag_chunks_condition_idx on rag_chunks (condition_code);

-- Cosine distance index. Skipped for now on purpose: with ~111 rows an index
-- buys nothing (a full scan is already sub-millisecond) and IVFFlat/HNSW need a
-- representative sample of real data to build well. Add this later if the corpus
-- grows enough for it to matter:
-- create index rag_chunks_embedding_idx on rag_chunks
--   using hnsw (embedding vector_cosine_ops);
