# LongMemEval Benchmark — StixDB

Evaluates StixDB retrieval quality against [LongMemEval](https://github.com/xiaowu0162/LongMemEval), a benchmark for long-term memory in conversational AI covering five memory abilities:

| Ability | Description |
|---|---|
| Information Extraction | Find facts mentioned in conversation history |
| Multi-Session Reasoning | Combine info across multiple sessions |
| Knowledge Updates | Handle contradictory / updated information |
| Temporal Reasoning | Understand when events occurred |
| Abstention | Know when to refuse an unanswerable question |

**Metrics:** Recall-Any@k, Recall-All@k, NDCG@k, QA Accuracy (with LLM judge)

---

## Setup

### 1. Start StixDB
```bash
stixdb daemon start
stixdb daemon status   # confirm it's running
```

### 2. Install dependencies
```bash
pip install huggingface_hub openai
```

### 3. Download the dataset
```bash
cd benchmarks/longmemeval
python -c "
from huggingface_hub import snapshot_download
snapshot_download(
    'xiaowu0162/longmemeval-cleaned',
    repo_type='dataset',
    local_dir='./data',
)
"
```

Files downloaded:
- `data/longmemeval_s_cleaned.json` — ~115k token haystacks, 500 questions (recommended starting point)
- `data/longmemeval_m_cleaned.json` — ~500 sessions per history (larger scale)
- `data/longmemeval_oracle.json` — evidence-only sessions (retrieval ceiling)

---

## Running the Benchmark

### Retrieval-only (no LLM answer generation)

```bash
# Quick smoke test — first 10 questions
python run_benchmark.py --data data/longmemeval_s_cleaned.json --limit 10

# Full eval, hybrid retrieval (default)
python run_benchmark.py --data data/longmemeval_s_cleaned.json

# Compare retrieval modes
python run_benchmark.py --data data/longmemeval_s_cleaned.json --mode keyword --output results/keyword.json
python run_benchmark.py --data data/longmemeval_s_cleaned.json --mode semantic --output results/semantic.json
python run_benchmark.py --data data/longmemeval_s_cleaned.json --mode hybrid  --output results/hybrid.json

# Turn-level granularity (finer nodes, better for temporal questions)
python run_benchmark.py --data data/longmemeval_s_cleaned.json --granularity turn

# Larger retrieval window
python run_benchmark.py --data data/longmemeval_s_cleaned.json --top-k 20
```

### End-to-end QA evaluation (retrieval + answer + LLM judge)

Requires `OPENAI_API_KEY` for the answer judge.

```bash
python run_benchmark.py \
  --data data/longmemeval_s_cleaned.json \
  --qa \
  --judge-model gpt-4o \
  --output results/stixdb_qa.json
```

### Oracle comparison (retrieval ceiling)

```bash
# Oracle dataset — only evidence sessions included, easiest possible retrieval task
python run_benchmark.py --data data/longmemeval_oracle.json --output results/oracle.json
```

---

## Options

| Flag | Default | Description |
|---|---|---|
| `--data` | required | Path to LongMemEval JSON file |
| `--output` | `results/stixdb_results.json` | Output path for per-question results |
| `--url` | `http://localhost:4020` | StixDB server URL (or `STIXDB_URL`) |
| `--api-key` | `None` | StixDB API key (or `STIXDB_API_KEY`) |
| `--mode` | `hybrid` | `hybrid` / `keyword` / `semantic` |
| `--granularity` | `session` | `session` (whole session) or `turn` (per user turn) |
| `--top-k` | `10` | Documents to retrieve per question |
| `--limit` | `None` | Only run first N questions |
| `--qa` | off | Enable answer generation + LLM judge |
| `--judge-model` | `gpt-4o` | Model used as QA judge |
| `--keep-collections` | off | Don't delete temp collections (for debugging) |
| `--verbose` | off | Debug logging |

---

## How It Works

For each question:

1. **Build corpus** — convert haystack sessions into a list of documents (session-level or turn-level)
2. **Ingest** — bulk-store documents into a temporary StixDB collection as episodic nodes
3. **Retrieve** — run `engine.retrieve(mode="hybrid")` for the question text
4. **Score** — compare ranked document IDs against ground-truth `answer_session_ids`
5. **Cleanup** — delete the temporary collection
6. *(QA mode)* **Generate** — run `engine.ask()` over the same collection before cleanup
7. *(QA mode)* **Judge** — use an LLM to compare the generated answer against the reference

Each question uses its own isolated collection so haystacks never bleed across questions.

---

## Expected Output

```
  [  10/500]  recall@10=True   ndcg=0.917  elapsed=48s  eta=2352s  single-session-user
  ...

========================================================================
  StixDB LongMemEval Results  |  mode=hybrid  gran=session  k=10
========================================================================

  Overall (500 questions)
    Recall-Any@10:  78.4%
    Recall-All@10:  71.2%
    NDCG@10:        0.6831

  Per question type:
  Type                          N   R-Any   R-All    NDCG
  --------------------------------------------------------
  knowledge-update            100   82.0%   74.0%  0.7214
  multi-session               100   71.0%   63.0%  0.6102
  single-session-assistant    100   85.0%   80.0%  0.7534
  single-session-preference   100   79.0%   72.0%  0.6891
  single-session-user         100   75.0%   67.0%  0.6414
========================================================================
```

---

## Interpreting Results

| Metric | What it measures |
|---|---|
| **Recall-Any@k** | At least one answer-containing document in the top-k — the most important metric for RAG |
| **Recall-All@k** | Every answer document in the top-k — harder, matters for multi-session questions |
| **NDCG@k** | Ranking quality — are answer documents near the top, not just present? |
| **QA Accuracy** | End-to-end: did StixDB produce a correct answer (not just retrieve correctly)? |

**Question types to watch:**
- `knowledge-update` — tests whether StixDB returns the *latest* fact, not an overwritten one
- `temporal-reasoning` — turn-level granularity (`--granularity turn`) often helps here
- `*_abs` variants — abstention questions; the model should say "I don't know"
