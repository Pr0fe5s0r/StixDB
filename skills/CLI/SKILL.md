---
name: stixdb-cli-memory
description: Use this skill whenever you need persistent memory, cross-session context, or knowledge storage for an AI agent using the StixDB CLI. This covers storing observations, retrieving past context, searching memories, ingesting documents, and managing collections via shell commands. Use this whether you are Claude Code, Claude Desktop, a custom agent, or any AI system that can run shell commands. StixDB gives you a persistent, queryable memory graph that survives across sessions and can be shared across agents and machines.
compatibility: Requires stixdb installed (`pip install stixdb-engine`), Python 3.9+, a running StixDB daemon or server.
---

# StixDB CLI Memory Skill

Use this skill to give yourself persistent, searchable, cross-session memory. StixDB is a graph-based memory engine you control entirely through shell commands. Everything you store persists across sessions. You can retrieve it semantically, reason over it with an LLM, and share it across agents.

---

## One-Time Setup

Run this once on a machine. After this, any agent on the machine can use the memory.

```bash
# 1. Install
pip install stixdb-engine

# 2. Configure (interactive wizard — sets LLM, embedding, storage)
stixdb init

# 3. Start the background daemon
stixdb daemon start

# 4. Verify
stixdb daemon status
```

The daemon runs in the background persistently. You do not need to start it again after reboots — just run `stixdb daemon start` once per machine session. If already running, it will say so.

---

## Every-Session Checklist

At the start of any session where you want memory, run:

```bash
# Check daemon is up
stixdb daemon status

# If not running, start it
stixdb daemon start
```

That's it. Your collections and memories from previous sessions are automatically available.

---

## Core Commands

### Store a Memory

```bash
stixdb store "TEXT"
stixdb store "TEXT" --collection NAME
stixdb store "TEXT" --tags tag1,tag2 --importance 0.8
stixdb store "TEXT" --node-type fact|concept|goal|pattern|rule
```

**Options:**
- `--collection` / `-c` — which memory space to write to (default: `main`)
- `--tags` / `-t` — comma-separated labels for later filtering
- `--importance` — 0.0 (ephemeral) to 1.0 (critical, never pruned)
- `--node-type` — semantic category of the memory

**Examples:**
```bash
stixdb store "User prefers concise responses, no bullet points" --tags preferences --importance 0.9
stixdb store "Project uses FastAPI with PostgreSQL" -c myproject --tags architecture
stixdb store "Deadline for v2 release is 2026-05-01" --node-type goal --importance 1.0
```

---

### Search Memories

Semantic search — finds relevant memories even when the wording differs.

```bash
stixdb search "QUERY"
stixdb search "QUERY" --collection NAME --top-k 10 --depth 2
```

**Options:**
- `--top-k` / `-k` — number of results (default: 5)
- `--depth` — graph expansion hops; 1 = direct matches, 2 = related neighbours (default: 1)
- `--threshold` — minimum similarity 0.0–1.0 (default: 0.25, lower = broader recall)
- `--tags` — filter to memories with these tags
- `--json` — machine-readable output

**Examples:**
```bash
stixdb search "user preferences"
stixdb search "database schema" -c myproject --depth 2
stixdb search "what did we decide about auth" --json
```

---

### Ask a Question (LLM Reasoning over Memory)

Retrieves relevant memories and synthesises a grounded answer using your configured LLM.

```bash
stixdb ask "QUESTION"
stixdb ask "QUESTION" --collection NAME --top-k 20 --depth 3
```

**Options:**
- `--top-k` — context nodes to retrieve before reasoning (default: 15)
- `--depth` — graph traversal depth (default: 2)
- `--json` — returns answer + sources + reasoning as JSON

**Examples:**
```bash
stixdb ask "What is the current architecture of this project?"
stixdb ask "What are this user's known preferences?" -c user_alice
stixdb ask "Summarise all decisions made this week" --top-k 30 --depth 3
```

---

### Ingest Files and Folders

Parse, chunk, embed and store documents into memory.

```bash
stixdb ingest PATH
stixdb ingest PATH --collection NAME --tags tag1,tag2
stixdb ingest PATH --chunk-size 800 --chunk-overlap 150
```

**Supported formats:** `.pdf`, `.md`, `.txt`, `.py`, `.js`, `.ts`, `.json`, `.yaml`, `.csv`, `.html`, `.rst`, and most code/text formats.

**Examples:**
```bash
stixdb ingest ./README.md -c myproject
stixdb ingest ./docs/ -c knowledge --tags documentation
stixdb ingest ./codebase/src/ -c myproject --tags source-code --chunk-size 600
stixdb ingest meeting_notes.pdf --tags meetings,decisions --importance 0.8
```

---

### Manage Collections

```bash
stixdb collections list             # See all collections
stixdb collections stats NAME       # Node count, tiers, clusters
stixdb collections delete NAME      # Permanently delete (irreversible)
```

---

### Daemon Control

```bash
stixdb daemon start                 # Start background server
stixdb daemon stop                  # Stop it
stixdb daemon restart               # Stop + start
stixdb daemon status                # Process alive? API reachable? Collections loaded?
stixdb daemon logs                  # Last 50 log lines
stixdb daemon logs --follow         # Live log tail
```

---

## Collection Strategy

Collections are isolated memory spaces. Use them to separate contexts.

| Pattern | Collection Name | What Goes In |
|---------|----------------|--------------|
| Per user | `user_alice`, `user_bob` | That user's preferences, history, goals |
| Per project | `project_stixdb`, `project_payments` | Architecture, decisions, docs |
| Per domain | `knowledge_security`, `knowledge_legal` | Ingested reference material |
| Shared agent memory | `agent_main` | Cross-session agent state |
| Current session | `session_2026_04_06` | Ephemeral scratch, can be deleted |

**Rules of thumb:**
- One collection per user or project — keeps context tight
- Use `main` (the default) for general-purpose single-agent use
- Never mix unrelated users' data into the same collection

---

## When to Store vs Search vs Ask

| Situation | What to do |
|-----------|-----------|
| You learn something that might matter later | `stixdb store` it immediately |
| User states a preference, goal, or constraint | `stixdb store` with `--importance 0.8+` |
| You're about to answer a complex question | `stixdb search` first to check for prior context |
| You need synthesised reasoning over past context | `stixdb ask` |
| User shares a document or codebase | `stixdb ingest` |
| Starting a new session on a familiar project | `stixdb search "project context"` to orient yourself |

---

## Memory Patterns for AI Agents

### Pattern 1 — Capture User Preferences
```bash
# User says something about how they like to work
stixdb store "User wants responses in plain prose, not bullet points" \
  --tags preferences,style --importance 0.9

# Later, before responding
stixdb search "user style preferences"
```

### Pattern 2 — Project Onboarding
```bash
# First time touching a project
stixdb ingest ./docs/ -c myproject --tags documentation
stixdb ingest ./src/ -c myproject --tags source-code --chunk-size 600

# Orient yourself
stixdb ask "What is this project and how is it structured?" -c myproject
```

### Pattern 3 — Capture Decisions
```bash
stixdb store "Decided to use Pydantic v2 for all models — migrated 2026-04-06" \
  -c myproject --tags decisions,architecture --importance 0.85

# Later
stixdb ask "What architecture decisions have been made?" -c myproject
```

### Pattern 4 — Cross-Session Continuity
```bash
# End of session: store what matters
stixdb store "Left off debugging the embedding dimension mismatch in kuzu backend" \
  -c myproject --tags in-progress --importance 0.95

# Start of next session
stixdb search "in progress work" -c myproject
stixdb ask "Where did we leave off?" -c myproject
```

### Pattern 5 — Multi-Agent Shared Context
```bash
# Agent A stores a finding
stixdb store "Found race condition in worker.py:_run_cycle — cycle skipped if node_count=0" \
  -c shared --tags bugs,agent-a

# Agent B reads it
stixdb search "known bugs" -c shared
stixdb ask "What issues has agent-a found?" -c shared
```

---

## Importance Guide

| Importance | Use for | Lifecycle |
|-----------|---------|-----------|
| `1.0` | Critical facts that must never be forgotten | Pinned permanently |
| `0.8–0.9` | User preferences, key decisions, deadlines | Protected from pruning |
| `0.5–0.7` | Normal project facts, architecture notes | Standard retention |
| `0.2–0.4` | Background context, minor observations | May be pruned over time |
| `0.0–0.1` | Scratch notes, highly ephemeral | Will be pruned |

The background agent automatically prunes low-importance, rarely-accessed nodes and consolidates related memories into summaries. Important memories (≥ 0.8) are protected.

---

## Node Types

| Type | Use for |
|------|---------|
| `fact` | Static assertions — "The DB runs on port 5432" |
| `concept` | Definitions and domain knowledge |
| `goal` | Objectives and intentions — "User wants to ship by May" |
| `rule` | Conditional logic — "If offline, queue retries" |
| `pattern` | Recurring behaviours — "User works best in the morning" |

---

## Claude Code Integration

If you are Claude Code (running inside a terminal), use the Bash tool to call StixDB:

```bash
# Check for prior context before starting work
stixdb search "project context" -c myproject --top-k 5

# Store a key decision
stixdb store "Chose to split cli.py into a package for maintainability" \
  -c myproject --tags architecture,decisions --importance 0.8

# Ask for a summary before diving in
stixdb ask "What is the current state of this project?" -c myproject
```

You can also pipe command output directly to StixDB:
```bash
git log --oneline -20 | stixdb store "$(cat)" -c myproject --tags git-history
```

---

## Claude Desktop / MCP Integration

If StixDB is exposed as an MCP server, you can call it through tools. Otherwise, use the CLI via a shell execution tool. The daemon serves a REST API at `http://localhost:4020` — any HTTP-capable tool can hit it directly:

```bash
# Health + collections
curl http://localhost:4020/health

# Store via API
curl -X POST http://localhost:4020/collections/main/nodes \
  -H "Content-Type: application/json" \
  -d '{"content": "Alice leads the platform team", "node_type": "fact", "importance": 0.8}'

# Search via API
curl -X POST http://localhost:4020/search \
  -H "Content-Type: application/json" \
  -d '{"query": "team leads", "collection": "main", "top_k": 5}'
```

Add `--header "X-API-Key: YOUR_KEY"` if you configured a server API key.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Cannot reach server` | Run `stixdb daemon start` |
| `No config found` | Run `stixdb init` first |
| `Search returns nothing` | Lower `--threshold` to 0.1, or check collection name with `stixdb collections list` |
| `stixdb: command not found` | Run `pip install stixdb-engine` |
| Daemon not starting | Run `stixdb daemon start --fg` to see errors in foreground |
| Slow responses | Reduce `--top-k` or `--depth`; or check `stixdb daemon logs` |

---

## Quick Reference

```bash
# Setup (once)
pip install stixdb-engine && stixdb init && stixdb daemon start

# Every session
stixdb daemon status                          # ensure running

# Store
stixdb store "TEXT" -c COLLECTION --tags TAGS --importance 0.8

# Retrieve
stixdb search "QUERY" -c COLLECTION --top-k 10
stixdb ask "QUESTION" -c COLLECTION

# Ingest documents
stixdb ingest ./path/to/docs -c COLLECTION

# Housekeeping
stixdb collections list
stixdb collections stats COLLECTION
stixdb daemon logs
```
