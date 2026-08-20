"""
RAGAS-based faithfulness + answer-relevancy evaluation.

One of three parallel eval scripts (see also deepeval_eval.py, trulens_eval.py),
all scoring the SAME dataset (built once, identically, by eval_common.py) with a
different framework — cross-checking each other rather than trusting one alone.

Unlike tests/test_rag_safety.py (keyword checks, free), this uses an LLM as a
JUDGE to score whether each answer is actually grounded in its retrieved
context (faithfulness) and actually addresses the question (relevancy) — a
semantic judgment plain string matching can't make. Deliberately uses a
DIFFERENT, stronger model as judge than the free model that generates the
actual answers, since a model judging its own free-tier output isn't a very
trustworthy signal.

You install and run this yourself:
    pip install ragas langchain-openai datasets

Requires JUDGE_OPENROUTER_API_KEY in .env.dev — a SEPARATE, credit-loaded
OpenRouter key from OPENROUTER_API_KEY. Add it to .env.dev yourself, the same
way as every other key in this project — never paste a real key into a chat
message.

Usage (PowerShell) — one judge for both metrics:
    $env:JUDGE_MODEL = "anthropic/claude-sonnet-5"
    python scripts/ragas_eval.py

Usage — different judge per metric (optional; RELEVANCY_JUDGE_MODEL defaults to
JUDGE_MODEL if unset, so this is purely additive, not a required change):
    $env:JUDGE_MODEL = "anthropic/claude-sonnet-5"       # used for faithfulness
    $env:RELEVANCY_JUDGE_MODEL = "openai/gpt-5-mini"      # used for answer relevancy
    python scripts/ragas_eval.py

Why split them: RAGAS's answer_relevancy metric asks the judge to generate 3
variant questions in one call. Claude models (via the OpenAI-compatible bridge)
have been observed returning only 1 of the 3 requested, making that specific
score noisier than it should be — an actual OpenAI model handles this multi-
generation request natively. Faithfulness has no such requirement and isn't
known to have this issue, so it can stay on whichever judge you prefer.

Bigger golden set: drop a CSV at eval_data/eval_golden_set.csv with at least
`condition_code` and `question` columns (e.g. what Gemini Pro generates from
the prompt in RAG_EVALUATION.md) and it's used automatically — see
eval_common.py.

Cost note for a 100-row set: each row costs ~1 free-model call (build) plus
~2-3 paid judge-model calls. At a mid-priced judge like anthropic/claude-sonnet-5
($2/$10 per M tokens), 100 rows is a reasoned estimate of roughly $1-2 total —
that's math, not a measurement. Test first with a small pilot:

    $env:EVAL_LIMIT = "5"; $env:JUDGE_MODEL = "anthropic/claude-sonnet-5"
    python scripts/ragas_eval.py

Check the real cost on your OpenRouter usage dashboard, multiply by 20 for a
100-row estimate, then unset EVAL_LIMIT to run the full set.

Note on RAGAS's exact API surface: this was written against the current docs
as of when it was written, but RAGAS has renamed metrics/classes across
versions before (e.g. answer_relevancy -> response_relevancy). If an import
below fails, check `python -c "import ragas; print(ragas.__version__)"` and
the current docs at https://docs.ragas.io — the fix is almost always a renamed
import, not a structural change to this script.
"""
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

# Windows console's default encoding can't display characters LLMs commonly
# produce (non-breaking hyphens, curly quotes, em-dashes) — without this, any
# print() that touches real model output (an error detail, a library's own log
# line) can crash the whole run with UnicodeEncodeError instead of the actual
# result being shown.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from eval_common import ENV_PATH, REPORT_DIR, build_dataset, load_golden_set  # noqa: E402

REPORT_PATH = REPORT_DIR / "ragas_eval_report.csv"


def main():
    judge_model = os.environ.get("JUDGE_MODEL")
    if not judge_model:
        print("Set JUDGE_MODEL to an OpenRouter model id you have paid credit for, e.g.:")
        print('  PowerShell:  $env:JUDGE_MODEL = "anthropic/claude-sonnet-5"; python scripts/ragas_eval.py')
        print("  bash:        JUDGE_MODEL=anthropic/claude-sonnet-5 python scripts/ragas_eval.py")
        sys.exit(1)
    # Optional: a different judge just for answer_relevancy (see docstring for
    # why). Falls back to the same judge as faithfulness if unset — existing
    # single-judge usage is unaffected.
    relevancy_judge_model = os.environ.get("RELEVANCY_JUDGE_MODEL", judge_model)

    env = dotenv_values(ENV_PATH)
    api_key = env["OPENROUTER_API_KEY"]  # builds the dataset (retrieval + answers)
    judge_api_key = env.get("JUDGE_OPENROUTER_API_KEY")  # separate, credit-loaded key: judges only
    if not judge_api_key:
        print("Set JUDGE_OPENROUTER_API_KEY in .env.dev to your paid OpenRouter key.")
        sys.exit(1)
    rag_db_url = env["SUPABASE_DIRECT_URL"].replace("postgresql+psycopg://", "postgresql://")

    golden_set = load_golden_set()
    limit = os.environ.get("EVAL_LIMIT")
    if limit:
        golden_set = golden_set[:int(limit)]
        print(f"EVAL_LIMIT set — using only the first {len(golden_set)} rows "
              f"(a cheap pilot run to see real cost before running the full set).")

    same_judge = relevancy_judge_model == judge_model
    print(f"Faithfulness judge: {judge_model}")
    print(f"Relevancy judge:    {relevancy_judge_model}"
          + (" (same as faithfulness)" if same_judge else " (different — see docstring for why)"))
    print("(billed to the paid OpenRouter key, not the free one)")
    print(f"Building dataset: retrieving + answering {len(golden_set)} golden questions "
          f"with the app's own free model...")
    rows = build_dataset(golden_set, rag_db_url, api_key)
    if not rows:
        print("No rows were built successfully — nothing to evaluate.")
        sys.exit(1)

    from datasets import Dataset
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import evaluate
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.metrics import faithfulness
    try:
        from ragas.metrics import answer_relevancy as relevancy_metric
    except ImportError:
        from ragas.metrics import response_relevancy as relevancy_metric

    def make_judge(model_name: str):
        llm = LangchainLLMWrapper(ChatOpenAI(
            model=model_name, api_key=judge_api_key, base_url="https://openrouter.ai/api/v1",
        ))
        embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(
            model="text-embedding-3-small", api_key=judge_api_key, base_url="https://openrouter.ai/api/v1",
        ))
        return llm, embeddings

    dataset = Dataset.from_list(rows)

    if same_judge:
        # One judge for both metrics — one evaluate() call, exactly as before.
        # No reason to double the overhead when there's only one judge anyway.
        llm, embeddings = make_judge(judge_model)
        print(f"Scoring faithfulness + relevancy with {judge_model}...")
        result = evaluate(dataset, metrics=[faithfulness, relevancy_metric], llm=llm, embeddings=embeddings)
        combined_df = result.to_pandas()
        print()
        print(result)
    else:
        # Different judges per metric — two evaluate() passes, merged by row
        # position (both score the exact same rows, in the exact same order,
        # since they share one `dataset` built once).
        faithfulness_llm, faithfulness_embeddings = make_judge(judge_model)
        print(f"Scoring faithfulness with {judge_model}...")
        faithfulness_df = evaluate(
            dataset, metrics=[faithfulness], llm=faithfulness_llm, embeddings=faithfulness_embeddings,
        ).to_pandas()

        relevancy_llm, relevancy_embeddings = make_judge(relevancy_judge_model)
        print(f"Scoring answer relevancy with {relevancy_judge_model}...")
        relevancy_df = evaluate(
            dataset, metrics=[relevancy_metric], llm=relevancy_llm, embeddings=relevancy_embeddings,
        ).to_pandas()

        relevancy_score_cols = [c for c in relevancy_df.columns if c not in faithfulness_df.columns]
        combined_df = faithfulness_df.copy()
        for col in relevancy_score_cols:
            combined_df[col] = relevancy_df[col].values

        print()
        print("Faithfulness average:", faithfulness_df.filter(like="faithfulness").mean(numeric_only=True).to_dict())
        print("Relevancy average:", relevancy_df[relevancy_score_cols].mean(numeric_only=True).to_dict())

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    combined_df.to_csv(REPORT_PATH, index=False)
    print(f"\nFull per-question report (both metrics combined) saved to {REPORT_PATH}")


if __name__ == "__main__":
    main()
