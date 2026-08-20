"""Retrieval correctness: for a representative question per condition, does the
top-K retrieval actually pull chunks tagged with that condition? Pure metadata
check — no LLM judge needed, this just confirms pgvector search + our chunk
tagging are doing their job.
"""
import os

import pytest
from dotenv import dotenv_values

from app.rag.vectorstore import retrieve_chunks

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dotenv_values(os.path.join(ROOT, ".env.dev"))
RAG_DB_URL = ENV["SUPABASE_DIRECT_URL"].replace("postgresql+psycopg://", "postgresql://")
API_KEY = ENV["OPENROUTER_API_KEY"]

# One representative, condition-specific question per condition we have content
# for. Add more per condition if you want a stronger signal.
CASES = [
    ("chronic_back_pain", "should I rest or keep moving with lower back pain"),
    ("gout", "what triggers a gout flare"),
    ("carpal_tunnel", "what helps wrist pain from typing"),
    ("bursitis", "what causes bursitis"),
    ("sprain_strain", "how do I treat a sprained ankle"),
    ("arthritis_hip", "what causes hip osteoarthritis"),
    ("herniated_disk", "what is a slipped disc"),
    ("spinal_stenosis", "what is spinal stenosis"),
    ("degenerative_disc", "what is degenerative disc disease"),
    ("spondylosis", "what is cervical spondylosis"),
]


@pytest.mark.parametrize("condition_code,question", CASES)
def test_retrieval_matches_condition(condition_code, question):
    chunks = retrieve_chunks(
        question, [condition_code], rag_db_url=RAG_DB_URL, api_key=API_KEY, top_k=3
    )
    assert chunks, f"No chunks retrieved at all for {condition_code!r}"
    matched = [c["chunk_id"] for c in chunks if condition_code in c["chunk_id"]]
    assert matched, (
        f"None of the top-3 chunks for {condition_code!r} were tagged with it: "
        f"{[c['chunk_id'] for c in chunks]}"
    )
