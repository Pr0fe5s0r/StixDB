"""
LongMemEval benchmark runner for StixDB.

Usage
-----
# Retrieval-only evaluation (fast, no LLM for answers):
  python run_benchmark.py --data longmemeval_s_cleaned.json --mode hybrid

# Full QA evaluation (retrieval + LLM answer generation + judge):
  python run_benchmark.py --data longmemeval_s_cleaned.json --qa --judge-model gpt-4o

# Turn-level granularity (each user turn is a separate node):
  python run_benchmark.py --data longmemeval_s_cleaned.json --granularity turn

# Larger top-k:
  python run_benchmark.py --data longmemeval_s_cleaned.json --top-k 20

Download dataset from HuggingFace first:
  pip install huggingface_hub
  python -c "
  from huggingface_hub import snapshot_download
  snapshot_download('xiaowu0162/longmemeval-cleaned', repo_type='dataset', local_dir='./data')
  "
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import sys
import time
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger("longmemeval")


# ── Corpus builders ──────────────────────────────────────────────────────── #

def build_session_corpus(entry: dict) -> tuple[list[str], list[str]]:
    """One document per session — full conversation text."""
    corpus, corpus_ids = [], []
    for sid, session in zip(entry["haystack_session_ids"], entry["haystack_sessions"]):
        turns = "\n".join(
            f"{t['role'].upper()}: {t['content']}" for t in session
        )
        corpus.append(turns)
        corpus_ids.append(sid)
    return corpus, corpus_ids


def build_turn_corpus(entry: dict) -> tuple[list[str], list[str]]:
    """One document per user turn — finer granularity."""
    corpus, corpus_ids = [], []
    for sid, session in zip(entry["haystack_session_ids"], entry["haystack_sessions"]):
        user_turn_idx = 0
        for turn in session:
            if turn["role"] != "user":
                continue
            corpus.append(turn["content"])
            corpus_ids.append(f"{sid}_{user_turn_idx}")
            user_turn_idx += 1
    return corpus, corpus_ids


def answer_session_ids_to_doc_ids(
    answer_session_ids: list[str],
    corpus_ids: list[str],
    granularity: str,
) -> set[str]:
    """
    Map ground-truth answer session IDs to the corpus_ids used for retrieval.
    At turn-level, any turn from an answer session is a correct document.
    """
    if granularity == "session":
        return set(answer_session_ids)
    # turn-level: match all turn IDs that start with an answer session ID
    answer_set = set(answer_session_ids)
    return {cid for cid in corpus_ids if cid.rsplit("_", 1)[0] in answer_set}


# ── Metrics ──────────────────────────────────────────────────────────────── #

def recall_at_k(ranked_indices: list[int], correct_ids: set[str], corpus_ids: list[str], k: int) -> tuple[bool, bool]:
    """Returns (recall_any, recall_all)."""
    retrieved = {corpus_ids[i] for i in ranked_indices[:k]}
    recall_any = bool(retrieved & correct_ids)
    recall_all = correct_ids.issubset(retrieved)
    return recall_any, recall_all


def ndcg_at_k(ranked_indices: list[int], correct_ids: set[str], corpus_ids: list[str], k: int) -> float:
    """NDCG@k."""
    dcg = 0.0
    for rank, idx in enumerate(ranked_indices[:k], start=1):
        if corpus_ids[idx] in correct_ids:
            dcg += 1.0 / math.log2(rank + 1)

    ideal_hits = min(len(correct_ids), k)
    idcg = sum(1.0 / math.log2(r + 1) for r in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


# ── QA judge ─────────────────────────────────────────────────────────────── #

async def judge_answer(
    question: str,
    reference: str,
    hypothesis: str,
    question_type: str,
    model: str,
) -> bool:
    """Use an LLM to judge whether hypothesis matches reference."""
    import openai
    client = openai.AsyncOpenAI()

    # Abstention questions: correct answer is to refuse
    if question_type.endswith("_abs"):
        prompt = (
            f"The question is unanswerable. The model should abstain or say it doesn't know.\n"
            f"Model answer: {hypothesis}\n\n"
            "Did the model correctly abstain? Reply YES or NO only."
        )
    else:
        prompt = (
            f"Question: {question}\n"
            f"Reference answer: {reference}\n"
            f"Model answer: {hypothesis}\n\n"
            "Is the model answer correct (semantically equivalent to the reference)? "
            "Reply YES or NO only."
        )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=5,
        )
        verdict = resp.choices[0].message.content.strip().upper()
        return verdict.startswith("YES")
    except Exception as e:
        logger.warning("Judge error: %s", e)
        return False


# ── Main eval loop ───────────────────────────────────────────────────────── #

async def run_eval(args: argparse.Namespace) -> None:
    from stixdb_adapter import StixDBRetriever

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    logger.warning("Loaded %d questions from %s", len(data), args.data)

    retriever = StixDBRetriever(
        url=args.url,
        api_key=args.api_key,
        collection_prefix="lme_bench",
        keep_collections=args.keep_collections,
        mode=args.mode,
        granularity=args.granularity,
    )

    build_corpus = build_turn_corpus if args.granularity == "turn" else build_session_corpus

    # Per-type accumulators
    results_by_type: dict[str, dict] = {}
    all_results: list[dict] = []

    t_start = time.perf_counter()
    for i, entry in enumerate(data):
        qid = entry["question_id"]
        qtype = entry["question_type"]
        question = entry["question"]
        reference = entry["answer"]
        answer_sids = entry.get("answer_session_ids", [])
        question_date = entry.get("question_date")

        corpus, corpus_ids = build_corpus(entry)
        if not corpus:
            logger.warning("q%d (%s): empty corpus — skipping", i, qid)
            continue

        correct_ids = answer_session_ids_to_doc_ids(answer_sids, corpus_ids, args.granularity)

        # Retrieval
        if args.qa:
            ranked, hypothesis = retriever.retrieve_and_answer(
                question, corpus, corpus_ids, k=args.top_k, question_date=question_date
            )
        else:
            ranked = retriever.retrieve(question, corpus, corpus_ids, k=args.top_k)
            hypothesis = ""

        r_any, r_all = recall_at_k(ranked, correct_ids, corpus_ids, args.top_k)
        ndcg = ndcg_at_k(ranked, correct_ids, corpus_ids, args.top_k)

        # QA judge
        qa_correct: Optional[bool] = None
        if args.qa and hypothesis:
            qa_correct = await judge_answer(
                question, reference, hypothesis, qtype, args.judge_model
            )

        result = {
            "question_id": qid,
            "question_type": qtype,
            "recall_any": r_any,
            "recall_all": r_all,
            "ndcg": ndcg,
            "qa_correct": qa_correct,
            "retrieved_doc_ids": [corpus_ids[j] for j in ranked],
        }
        if args.qa:
            result["hypothesis"] = hypothesis
            result["reference"] = reference

        all_results.append(result)

        # Accumulate per-type
        if qtype not in results_by_type:
            results_by_type[qtype] = {"recall_any": [], "recall_all": [], "ndcg": [], "qa_correct": []}
        results_by_type[qtype]["recall_any"].append(r_any)
        results_by_type[qtype]["recall_all"].append(r_all)
        results_by_type[qtype]["ndcg"].append(ndcg)
        if qa_correct is not None:
            results_by_type[qtype]["qa_correct"].append(qa_correct)

        # Live progress
        elapsed = time.perf_counter() - t_start
        avg = elapsed / (i + 1)
        eta = avg * (len(data) - i - 1)
        print(
            f"\r  [{i+1:>4}/{len(data)}]  "
            f"recall@{args.top_k}={r_any!s:<5}  ndcg={ndcg:.3f}  "
            f"elapsed={elapsed:.0f}s  eta={eta:.0f}s  {qtype[:30]}",
            end="", flush=True,
        )

    print()  # newline after progress

    # ── Summary ─────────────────────────────────────────────────────── #
    print("\n" + "=" * 72)
    print(f"  StixDB LongMemEval Results  |  mode={args.mode}  gran={args.granularity}  k={args.top_k}")
    print("=" * 72)

    all_ra = [r["recall_any"] for r in all_results]
    all_rl = [r["recall_all"] for r in all_results]
    all_nd = [r["ndcg"] for r in all_results]
    all_qa = [r["qa_correct"] for r in all_results if r["qa_correct"] is not None]

    def pct(lst): return f"{100*sum(lst)/len(lst):.1f}%" if lst else "—"

    print(f"\n  Overall ({len(all_results)} questions)")
    print(f"    Recall-Any@{args.top_k}:  {pct(all_ra)}")
    print(f"    Recall-All@{args.top_k}:  {pct(all_rl)}")
    print(f"    NDCG@{args.top_k}:        {sum(all_nd)/len(all_nd):.4f}" if all_nd else "")
    if all_qa:
        print(f"    QA Accuracy:       {pct(all_qa)}")

    print(f"\n  Per question type:")
    col_w = max(len(t) for t in results_by_type) + 2
    header = f"  {'Type':<{col_w}}  {'N':>4}  {'R-Any':>7}  {'R-All':>7}  {'NDCG':>7}"
    if args.qa:
        header += f"  {'QA-Acc':>7}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    for qtype, acc in sorted(results_by_type.items()):
        n = len(acc["recall_any"])
        ra = pct(acc["recall_any"])
        rl = pct(acc["recall_all"])
        nd = f"{sum(acc['ndcg'])/n:.4f}" if acc["ndcg"] else "—"
        row = f"  {qtype:<{col_w}}  {n:>4}  {ra:>7}  {rl:>7}  {nd:>7}"
        if args.qa:
            qa_acc = pct(acc["qa_correct"]) if acc["qa_correct"] else "—"
            row += f"  {qa_acc:>7}"
        print(row)

    print("=" * 72)

    # ── Write output ─────────────────────────────────────────────────── #
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(all_results, indent=2), encoding="utf-8")
    print(f"\n  Full results written to: {out_path}")


# ── CLI ──────────────────────────────────────────────────────────────────── #

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run StixDB against the LongMemEval benchmark.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--data", required=True,
                   help="Path to LongMemEval JSON file (e.g. longmemeval_s_cleaned.json).")
    p.add_argument("--output", default="results/stixdb_results.json",
                   help="Where to write the full per-question results JSON.")
    p.add_argument("--url", default=os.getenv("STIXDB_URL", "http://localhost:4020"),
                   help="StixDB server URL.")
    p.add_argument("--api-key", default=os.getenv("STIXDB_API_KEY"),
                   help="StixDB API key.")
    p.add_argument("--mode", default="hybrid", choices=["hybrid", "keyword", "semantic"],
                   help="Retrieval mode (default: hybrid).")
    p.add_argument("--granularity", default="session", choices=["session", "turn"],
                   help="Index at session or turn level (default: session).")
    p.add_argument("--top-k", type=int, default=10,
                   help="Number of documents to retrieve (default: 10).")
    p.add_argument("--limit", type=int, default=None,
                   help="Only evaluate the first N questions (for quick smoke tests).")
    p.add_argument("--qa", action="store_true",
                   help="Enable end-to-end QA evaluation (retrieval + LLM answer + judge).")
    p.add_argument("--judge-model", default="gpt-4o",
                   help="LLM model to use as QA judge (default: gpt-4o). Requires OPENAI_API_KEY.")
    p.add_argument("--keep-collections", action="store_true",
                   help="Do not delete temporary collections after each question.")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.verbose:
        logging.getLogger("longmemeval").setLevel(logging.DEBUG)
    if args.limit:
        # Patch data loading to slice
        original_json_loads = json.loads
        def patched_loads(s, **kw):
            data = original_json_loads(s, **kw)
            return data[:args.limit] if isinstance(data, list) else data
        json.loads = patched_loads

    # Add current dir to path so stixdb_adapter imports cleanly
    sys.path.insert(0, str(Path(__file__).parent))

    asyncio.run(run_eval(args))
