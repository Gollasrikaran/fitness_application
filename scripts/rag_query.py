"""
End-to-end RAG query: embed the user's question, retrieve the closest chunks for
their condition from rag_chunks (Supabase/pgvector), and have the LLM explain an
answer grounded only in that retrieved text.

Usage:
    python scripts/rag_query.py <condition_code> "<question>"

Example:
    python scripts/rag_query.py gout "what exercises can help with gout pain"

This is a standalone CLI for testing the pipeline outside the Flask app — no auth,
no quota, no referred-bucket gate. It calls the exact same retrieval/prompt code
the real app/rag/ module uses (imported from there, not duplicated), so this stays
useful for quickly checking retrieval quality or prompt changes without needing a
running server. The real, gated path is app/rag/service.py's answer_query().
"""

import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # so `import app.rag...` resolves when run as a script

from app.platform.db import init_engine, session_scope  # noqa: E402
from app.rag.service import (  # noqa: E402
    SYSTEM_PROMPT, _approved_activities, _enforce_no_medication_or_surgery,
)
from app.rag.vectorstore import chat_complete, retrieve_chunks  # noqa: E402

ENV_PATH = ROOT / ".env.dev"


def answer_question(condition_code: str, question: str):
    env = dotenv_values(ENV_PATH)
    api_key = env["OPENROUTER_API_KEY"]
    db_url = env["SUPABASE_DIRECT_URL"].replace("postgresql+psycopg://", "postgresql://")

    chunks = retrieve_chunks(question, [condition_code], rag_db_url=db_url, api_key=api_key)
    if not chunks:
        return "No retrieved information found for this condition.", []

    init_engine(env["DATABASE_URL"])
    with session_scope() as session:
        approved = _approved_activities(session, [condition_code])
    approved_block = (
        "Approved exercises for this condition: " + ", ".join(approved)
        if approved else
        "Approved exercises for this condition: none listed."
    )

    context_block = "\n\n".join(f"[{i + 1}] {c['text']}" for i, c in enumerate(chunks))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",
         "content": f"Retrieved information:\n{context_block}\n\n{approved_block}\n\n"
                    f"Question: {question}"},
    ]

    answer = _enforce_no_medication_or_surgery(chat_complete(messages, api_key))
    return answer, chunks


def main():
    if len(sys.argv) < 3:
        print('Usage: python scripts/rag_query.py <condition_code> "<question>"')
        sys.exit(1)

    condition_code = sys.argv[1]
    question = sys.argv[2]

    answer, chunks = answer_question(condition_code, question)

    print(f"Condition: {condition_code}")
    print(f"Question: {question}")
    print()
    print("Retrieved chunks used:")
    for c in chunks:
        print(f"  - {c['chunk_id']} (similarity {c['similarity']:.3f})")
    print()
    print("Answer:")
    print(answer)


if __name__ == "__main__":
    main()
