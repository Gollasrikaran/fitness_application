"""
Shared by all three eval scripts (ragas_eval.py, deepeval_eval.py, trulens_eval.py):
loading the golden set and building the {question, contexts, answer} dataset by
running the app's actual pipeline (real retrieval, real free-model answers). Each
framework only differs in how it SCORES this same dataset — the dataset itself
should never drift between them, or a disagreement between frameworks could just
mean they scored different data, not that they actually disagree.
"""
import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))  # so `import app...` resolves when run as a script

from app.rag.service import SYSTEM_PROMPT  # noqa: E402
from app.rag.vectorstore import (  # noqa: E402
    ResponseTruncated, UpstreamUnavailable, chat_complete, retrieve_chunks,
)

ENV_PATH = ROOT / ".env.dev"
GOLDEN_SET_CSV = ROOT / "eval_data" / "eval_golden_set.csv"
REPORT_DIR = ROOT / "eval_data"
DATASET_CHECKPOINT = ROOT / "eval_data" / "dataset_checkpoint.jsonl"

# Fallback used only if GOLDEN_SET_CSV doesn't exist. Real patient-style
# questions pulled from MedQuAD (NIH's Medical Question Answering Dataset, CC
# BY 4.0) — the same dataset already used to build 9 of our content chunks
# (data/rag_sources/medquad__*.md), verified via the HuggingFace
# dataset-server search API, NOT hand-invented. Exception: spondylosis has no
# MedQuAD entry (only "ankylosing spondylitis," a different disease), so that
# one row is hand-written and marked as such.
DEFAULT_GOLDEN_SET = [
    ("chronic_back_pain", "What are the treatments for Back Pain ?"),
    ("gout", "Who is at risk for Gout ?"),
    ("carpal_tunnel", "What is the outlook for Carpal Tunnel Syndrome ?"),
    ("bursitis", "What is (are) Bursitis ?"),
    ("sprain_strain", "What is (are) Sprains and Strains ?"),
    ("arthritis_hip", "What causes Osteoarthritis ?"),
    ("herniated_disk", "What is (are) Herniated Disk ?"),
    ("spinal_stenosis", "What is (are) Spinal Stenosis ?"),
    ("degenerative_disc", "What causes Intervertebral Disc Disease ?"),
    ("spondylosis", "what is cervical spondylosis"),  # hand-written — not in MedQuAD
]


def load_golden_set() -> list[tuple[str, str]]:
    """Reads eval_data/eval_golden_set.csv if present (needs at least
    condition_code and question columns — extra columns like question_type,
    e.g. from a Gemini-generated set, are ignored). Falls back to the small
    built-in set otherwise."""
    if GOLDEN_SET_CSV.exists():
        with GOLDEN_SET_CSV.open(encoding="utf-8-sig", newline="") as f:
            rows = [(r["condition_code"].strip(), r["question"].strip()) for r in csv.DictReader(f)]
        print(f"Loaded {len(rows)} questions from {GOLDEN_SET_CSV}")
        return rows
    print(f"No {GOLDEN_SET_CSV} found — using the built-in {len(DEFAULT_GOLDEN_SET)}-question set.")
    print("(Generate a bigger one via the Gemini Pro prompt in RAG_EVALUATION.md and save it there.)")
    return DEFAULT_GOLDEN_SET


def _load_checkpoint() -> dict[tuple[str, str], dict]:
    """Successfully-built rows saved by a previous, possibly-interrupted run —
    keyed by (condition_code, question) so a re-run can skip work already done
    instead of rebuilding all 100 rows from scratch. Delete
    eval_data/dataset_checkpoint.jsonl yourself if you ever want a guaranteed
    fully-fresh rebuild (e.g. after changing the system prompt)."""
    if not DATASET_CHECKPOINT.exists():
        return {}
    done = {}
    with DATASET_CHECKPOINT.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            done[(rec["condition_code"], rec["question"])] = rec
    return done


def build_dataset(golden_set: list[tuple[str, str]], rag_db_url: str, api_key: str) -> list[dict]:
    """Runs the REAL pipeline for each (condition_code, question) pair: real
    pgvector retrieval, real free-model answer generation, same system prompt
    the live app uses. Returns [{question, answer, contexts}, ...].

    Every successful row is written to DATASET_CHECKPOINT immediately (flushed
    to disk, not just buffered) — if this run gets interrupted, the next run
    picks up from here instead of starting over at row 1. Skipped rows
    (rate-limited or truncated) are NOT checkpointed, so they're retried on the
    next run rather than being permanently given up on.
    """
    rows = []
    skipped_rate_limited = []
    skipped_truncated = []
    total = len(golden_set)

    checkpoint = _load_checkpoint()
    if checkpoint:
        print(f"Resuming: {len(checkpoint)} rows already done in {DATASET_CHECKPOINT.name} — "
              f"only building what's left.")

    DATASET_CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    with DATASET_CHECKPOINT.open("a", encoding="utf-8") as checkpoint_file:
        for i, (condition_code, question) in enumerate(golden_set, 1):
            key = (condition_code, question)
            if key in checkpoint:
                rec = checkpoint[key]
                rows.append({"question": rec["question"], "answer": rec["answer"], "contexts": rec["contexts"]})
                print(f"  [{i}/{total}] {condition_code:20s} -> (resumed from checkpoint)")
                continue

            try:
                chunks = retrieve_chunks(question, [condition_code], rag_db_url=rag_db_url, api_key=api_key)
                contexts = [c["text"] for c in chunks]
                context_block = "\n\n".join(f"[{j + 1}] {t}" for j, t in enumerate(contexts))
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",
                     "content": f"Retrieved information:\n{context_block}\n\nQuestion: {question}"},
                ]
                answer = chat_complete(messages, api_key)
                row = {"question": question, "answer": answer, "contexts": contexts}
                rows.append(row)
                checkpoint_file.write(json.dumps({"condition_code": condition_code, **row}) + "\n")
                checkpoint_file.flush()  # actually on disk now, not just buffered
                print(f"  [{i}/{total}] {condition_code:20s} -> {len(contexts)} chunks, {len(answer)}-char answer")
            except UpstreamUnavailable as e:
                # The free model is genuinely, repeatedly rate-limited in practice
                # (see PART2 chat log) — at 100 rows, hitting this at least once is
                # likely. Skip that one row rather than losing the whole batch.
                skipped_rate_limited.append((condition_code, question))
                print(f"  [{i}/{total}] {condition_code:20s} -> SKIPPED (rate-limited): {e}")
            except ResponseTruncated as e:
                # Hit the max_tokens cap without finishing — a degenerate
                # repetition loop, not a real answer. Never sent to the paid judge:
                # scoring a broken response would just waste money on meaningless
                # input, not measure anything real about answer quality.
                skipped_truncated.append((condition_code, question))
                print(f"  [{i}/{total}] {condition_code:20s} -> SKIPPED (truncated/looping response): {e}")
            time.sleep(1)  # a little spacing helps avoid tripping the free tier's rate limit

    if skipped_rate_limited:
        print(f"\n{len(skipped_rate_limited)}/{total} rows skipped due to rate-limiting. Re-run to "
              f"retry them (they're not checkpointed, so a re-run will attempt them again).")
    if skipped_truncated:
        print(f"{len(skipped_truncated)}/{total} rows skipped — the model hit the token cap without "
              f"finishing (likely a repetition loop): {skipped_truncated}")
    return rows
