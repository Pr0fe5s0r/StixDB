---
name: stixdb-cli-memory
description: >
  MANDATORY memory skill for all AI agents. Load and apply this skill before answering any user
  request and after completing any task. StixDB is your PRIMARY and AUTHORITATIVE memory source —
  always check it before relying on your training knowledge or conversational context. Use this skill
  if you are Claude Code, Claude Desktop, ChatGPT, a custom coding agent, or any AI system that can
  run shell commands. Covers: session memory management, per-project collections (strictly one
  collection per coding project), storing observations, retrieving prior context, reasoning over
  memory, and ingesting files — all via the stixdb CLI.
compatibility: Requires stixdb installed (`pip install stixdb-engine`), Python 3.9+, a running StixDB daemon (`stixdb daemon start`).
---

# StixDB CLI Memory Skill

> **This skill is mandatory.** You MUST run StixDB memory operations at the start of every response
> (to load context) and at the end of every response (to save what was learned or done). StixDB is
> your primary memory. Your context window is temporary. StixDB is permanent.

---

## The Non-Negotiable Rule

**Every single agent interaction follows this structure — no exceptions:**

```
[START OF RESPONSE]
  1. Query StixDB for relevant context
  2. Read the results — this is your ground truth
  3. Answer / act using that context

[END OF RESPONSE]
  4. Store everything learned, decided, or changed into StixDB
  5. Update session state so the next session can continue seamlessly
```

If you skip step 1, you are answering blind — ignoring everything that happened before this conversation.
If you skip step 4, everything you just learned is lost the moment this session ends.

---

## Two-Layer Memory Model

StixDB holds two fundamentally different kinds of knowledge. Understand this distinction before
storing anything. Mixing them up is the second most common failure mode after storing too little.

### Layer 1 — Structural Knowledge (What the codebase IS)

This is the map of the territory. It answers: *where does X live, what does it do, how does it connect?*

Stored via **`stixdb store`** using structural templates (MODULE MAP, API SURFACE).
Also populated via **`stixdb ingest`** which chunks and embeds source files automatically.

Examples of structural knowledge:
- "The auth module lives in `src/auth/`, entry point is `auth.py:42`, handles JWT and OAuth2."
- "The `DatabaseManager` class at `db/manager.py:18` is a singleton — only instantiate once."
- "All API routes are registered in `app/routes/__init__.py`. Adding a route requires updating the router map at line 34."

### Layer 2 — Experiential Knowledge (What has been LEARNED and DONE)

This is the accumulated wisdom from working in the codebase. It answers: *what decisions were made,
what bugs were fixed, what patterns were discovered, what changed and why?*

Stored exclusively via **`stixdb store`** using experiential templates (DECISION, BUG FIXED,
PATTERN, REFACTOR, IN PROGRESS, SESSION SUMMARY).

Examples of experiential knowledge:
- "We switched from Argon2 to bcrypt on 2026-03-12 because Argon2 was causing memory spikes under load."
- "Bug: the worker cycled every 30s on empty collections. Fixed at `worker.py:150` with a node count guard."
- "Convention: all database queries must go through `db/manager.py`. Direct SQLAlchemy calls in route handlers are explicitly forbidden."

> **Rule:** Never mix these two layers in a single entry. A MODULE MAP entry should not contain
> decisions. A DECISION entry should not contain file structure. Keep them separate so retrieval
> stays clean.

---

## What Goes Into StixDB vs What Stays on Disk

This is the most important rule in this document. Get it wrong and you poison your own memory.

### ✅ Store in StixDB

| What | Why |
|---|---|
| File and module references (path + line range + purpose) | Navigation without re-reading |
| Function/class signatures and their *behavioral* contracts | What it does, not what it is |
| Decisions with rationale and rejected alternatives | Cannot be inferred from code alone |
| Bug root causes and fixes (path:line, exact symptom, exact fix) | Prevents re-investigation |
| Discovered conventions and patterns | Tacit knowledge not written anywhere |
| In-progress state with exact next action | Session continuity |
| API surface: inputs, outputs, side effects | Contracts that must be honoured |
| Refactors: what moved where and why | Prevents confusion from stale file paths |

### ❌ Never Store in StixDB

| What | Why not | What to do instead |
|---|---|---|
| **Raw source code** | Bloats the graph, becomes stale, redundant with the filesystem | Use `stixdb ingest` to chunk files properly, or store only the function signature + behavioral description |
| **Full conversation transcripts** | Noisy, unstructured, expensive to retrieve over | Distill into a SESSION SUMMARY or DECISION entry |
| **Transient debug output** | One-time noise, not persistent knowledge | Store only if it reveals a root cause worth remembering |
| **Things directly readable from the filesystem** | Redundant, will drift from reality | Reference the file:line instead |
| **Identical or near-identical entries** | Creates contamination — retrieval returns both | Always check with `stixdb search` before storing to detect near-duplicates |
| **Vague summaries without specifics** | Forces re-investigation — the exact failure mode StixDB exists to prevent | Use templates. Fill every field. |

> **The test:** Before storing anything, ask: *"Can the next agent read only this entry and continue
> work immediately without opening a single file?"* If no — add more detail. If it contains raw
> code blocks — extract the behavioral description and file reference instead.

---

## Memory Evolution: The SUPERSEDES Pattern

**This is the most critical thing the original approach got wrong.**

Every time a fact changes — a decision is reversed, a file is moved, a bug reappears — you MUST
explicitly supersede the old entry. If you only add a new entry without marking the old one stale,
both entries exist. The next agent retrieves both, cannot know which is current, and either
picks the wrong one or asks you to clarify. That is **context contamination**, and it compounds silently.

### How to Supersede

Always begin the new entry with `SUPERSEDES: [topic of old entry]` and include what changed:

```bash
# Old entry exists: "Use Argon2 for password hashing"
# New decision reverses it. DO THIS:

stixdb store "DECISION: Password hashing uses bcrypt, NOT Argon2. \
SUPERSEDES: previous Argon2 hashing decision (2026-01-15). \
CONTEXT: Argon2 was causing memory spikes (1.2GB peak) under concurrent login load. \
RATIONALE: bcrypt has lower memory footprint at equivalent security level for our scale. \
ALTERNATIVES REJECTED: Argon2id with reduced memory params — still unstable under load. \
LOCATION: src/auth/hashing.py:23 — HashManager.hash_password(). \
CONSEQUENCES: All existing hashed passwords remain valid (bcrypt reads Argon2 hashes \
for legacy users). New registrations hash with bcrypt. Do not revert without load testing. \
DATE: 2026-03-12." \
  -c proj_myapp --tags decisions,auth,security --importance 0.95
```

### When to Supersede

| Situation | Action |
|---|---|
| A decision is reversed | New DECISION entry with `SUPERSEDES:` |
| A file is moved or renamed | New MODULE MAP entry with `SUPERSEDES:` noting old path |
| A bug reappears after a fix | New BUG FIXED entry with `SUPERSEDES:` referencing first fix |
| A convention changes | New PATTERN entry with `SUPERSEDES:` |
| An API changes its contract | New API SURFACE entry with `SUPERSEDES:` |
| In-progress work is completed | New entry tagged `completed` that `SUPERSEDES:` the IN PROGRESS entry |

### Memory Drift Warning

If you do not supersede old entries, the following failure cascade occurs:
1. Old entry: "Use Argon2" — retrieved with high relevance
2. New entry: "Use bcrypt" — also retrieved
3. Agent sees both, cannot determine which is current
4. Agent picks one arbitrarily or halts to ask
5. If wrong pick: wrong code is written, bug introduced
6. Bug is discovered sessions later with no memory of why it happened

**This is "context contamination" and it kills long-running projects.**

---

## The Most Important Rule: Store Full Discovery, Not References

> **The number one failure mode of agents using StixDB.**

Storing a short reference like `"Fixed bug in worker.py"` or `"Updated config schema"` is useless.
It tells the next agent nothing. It forces re-reading all the same files, re-tracing the same
execution paths, re-discovering the same things. That is exactly what StixDB exists to prevent.

**The goal of every store operation is to make the next agent's re-discovery completely unnecessary.**

### The Test

Before you store anything, ask:

> *"If the next agent reads only this StixDB entry and nothing else, can they continue
> work immediately without opening a single file?"*

If the answer is no, your entry is not detailed enough. Add more.

---

## What Good vs Bad Storage Looks Like

### Bug Fix

**BAD — useless reference:**
```bash
stixdb store "Fixed empty collection bug in worker.py" -c proj_stixdb
```

**GOOD — full discovery, structural reference, no raw code:**
```bash
stixdb store "BUG FIXED: agent worker was running full perceive/plan/act cycle even when \
collection had zero nodes, causing cycle spam every 30s in daemon logs (cycle=1,2,3... \
with all zeros). ROOT CAUSE: _run_cycle() in stixdb/agent/worker.py had no guard for \
empty collections — it entered the full reasoning loop regardless of node count. \
FIX: added node_count = await self.graph.count_nodes() at line 150, early return if \
node_count == 0 with a debug-level log. graph.count_nodes() is defined at \
stixdb/graph/memory_graph.py:146. The fix does NOT increment cycle_count so logs stay \
clean. VERIFIED: after fix, logs show no cycle entries until data is ingested. \
RELATED: daemon.py start() calls _run_cycle() on a timer — no changes needed there." \
  -c proj_stixdb --tags bugfix,worker,agent --importance 0.9
```

---

### Architecture Discovery

**BAD — vague, cannot navigate from this:**
```bash
stixdb store "CLI was refactored into a package" -c proj_stixdb
```

**GOOD — structural map with line refs and connection logic:**
```bash
stixdb store "MODULE MAP: stixdb/cli/ package (split from monolithic stixdb/cli.py ~1200 lines). \
STRUCTURE: \
  __init__.py — app assembly, registers all sub-commands via Typer. \
  _helpers.py — shared constants (GLOBAL_DIR, GLOBAL_CONFIG, DAEMON_PID, DAEMON_LOG path), \
    helpers (http_get, http_post, http_delete), daemon_running(), require_global_config(). \
  _server.py — cmd_init, cmd_serve, cmd_status, cmd_info. \
  _daemon.py — daemon_app sub-typer: start/stop/restart/status/logs. \
  _api.py — collections_app sub-typer, cmd_ingest, cmd_store, cmd_search, cmd_ask. \
ENTRY POINT: pyproject.toml: stixdb = 'stixdb.cli:app'. \
DEPENDENCIES: All API commands read host/port/api_key from ~/.stixdb/config.json via _helpers. \
GOTCHAS: Do not import from _server.py in _api.py — circular import via _helpers. \
  If adding a new command, register it in __init__.py, not inline." \
  -c proj_stixdb --tags file-map,architecture,cli --importance 0.9
```

---

### Decision Made

**BAD — no rationale, cannot evaluate if still valid:**
```bash
stixdb store "Decided to store API keys in config.json" -c proj_stixdb
```

**GOOD — full decision with rationale, consequences, and constraints:**
```bash
stixdb store "DECISION: API keys stored as plain values directly in config.json \
(cf.llm.api_key, cf.embedding.api_key, cf.server.api_key), NOT as env var name references. \
RATIONALE: previous approach stored env var names (e.g. NEBIUS_API_KEY) and called \
os.getenv() at runtime. This caused a cascade failure: wizard stored the raw key value \
as an env var name, os.getenv('v1.CmMK...') returned None, server fell back to \
sentence_transformers for embedding, which triggered a corrupt numexpr install. \
ALTERNATIVES REJECTED: env var references — too fragile at config write time. \
  Secret manager integration — out of scope for v1. \
CONSEQUENCES: Anyone with config.json has the keys. File must stay private, never committed \
to git. ~/.stixdb/config.json is outside all repos by design. \
DATE: 2026-01-20." \
  -c proj_stixdb --tags decisions,security,api-keys --importance 0.95
```

---

### Pattern Discovered (new — not in original skill)

Use this when you discover an unwritten convention or a repeating structure in the codebase.
These are the most valuable memories to store because they are *nowhere in the documentation*.

```bash
stixdb store "PATTERN: All async database operations in this project follow a \
'context manager + explicit commit' contract. DO NOT use Session.add() without \
a matching await session.commit() in the same try/finally block — the DB layer \
does NOT auto-commit. Pattern is established in db/base.py:AsyncSessionMixin (line 44). \
Every service that writes to DB inherits from this mixin. \
GOTCHAS: Forgetting the commit causes silent data loss — no exception is raised. \
  Read-only queries do not need commit. Pattern applies to SQLAlchemy async sessions only; \
  the Redis client (cache/redis.py) does auto-flush. \
DISCOVERED: 2026-03-15 while fixing a missing commit in user_service.py:89." \
  -c proj_myapp --tags pattern,database,async --importance 0.9
```

---

### API Surface (new — not in original skill)

Use this when you need to document a function, class, or service interface whose contract
must be understood before calling it — inputs, outputs, side effects, invariants.

```bash
stixdb store "API SURFACE: HashManager.hash_password() at src/auth/hashing.py:67. \
SIGNATURE: async def hash_password(plain: str, scheme: Literal['bcrypt','legacy']) -> str \
INPUT: plain — raw password string (must not be pre-hashed). \
  scheme — 'bcrypt' for new users, 'legacy' for Argon2 migration path. \
OUTPUT: hashed string, bcrypt format '$2b$12$...' or Argon2 format '$argon2id$...' \
SIDE EFFECTS: none — pure function, no DB writes. \
INVARIANTS: Never call with an already-hashed string — no detection, will double-hash. \
  Always pair with HashManager.verify() — do not use passlib directly in calling code. \
CALLERS: auth/service.py:register_user (line 34), auth/service.py:change_password (line 89). \
NOTE: The 'legacy' scheme exists only for reading existing Argon2 hashes — do not use \
for new writes. See DECISION: Password hashing uses bcrypt entry for context." \
  -c proj_myapp --tags api-surface,auth,hashing --importance 0.85
```

---

### Refactor (new — not in original skill)

Use this whenever code moves, is renamed, or is restructured. Stale file paths are a silent
killer — an agent confidently edits a file that no longer exists at that path.

```bash
stixdb store "REFACTOR [2026-03-20]: User API split from monolith into microservice. \
SUPERSEDES: MODULE MAP entry for src/api/users.py (old monolith path no longer valid). \
WHAT MOVED: \
  src/api/users.py → services/user-service/app/routes.py (all route handlers) \
  src/models/user.py → services/user-service/app/models.py (User, UserProfile models) \
  src/services/user_service.py → services/user-service/app/service.py (business logic) \
WHAT STAYED: \
  src/api/gateway.py — now proxies /users/* to user-service via HTTP (see line 88). \
NEW ENTRY POINTS: \
  services/user-service/app/main.py — FastAPI app, port 8001. \
  services/user-service/Dockerfile — local dev: docker-compose up user-service. \
GOTCHAS: The gateway uses async httpx, not direct import. Any change to user routes \
must be reflected in gateway.py route map at line 88. \
MOTIVATION: User service was 40% of monolith by LOC. Extracted for independent scaling." \
  -c proj_myapp --tags refactor,file-map,users-api --importance 0.9
```

---

### In-Progress Work

**BAD — next agent has no idea where to start:**
```bash
stixdb store "Working on wizard changes" -c proj_stixdb
```

**GOOD — next agent can pick up immediately:**
```bash
stixdb store "IN PROGRESS [2026-04-06]: Updating wizard.py (stixdb/wizard.py). \
COMPLETED: added _step_agent() as Step 4/5 — cycle_interval (default 300s) asked \
upfront, all other 7 params gated behind 'Configure advanced agent settings? [N]' confirm. \
Updated _step_advanced() to return tuple of 4 (added ObservabilityFileConfig). \
Updated run_wizard() call sequence and ConfigFile construction to pass agent_cfg, obs_cfg. \
CURRENT STATE: wizard runs end-to-end but _preview() table is missing the new rows. \
_server.py cmd_info() shows new fields but stixdb info output not verified against live config. \
REMAINING (in order): \
  1. Read wizard.py lines 330-380 — understand _preview() table structure. \
  2. Add rows for agent.* and observability.* sections to _preview(). \
  3. Run stixdb init --force to test full wizard flow. \
  4. Run stixdb info and verify all new config fields appear. \
NEXT ACTION: Open stixdb/wizard.py, jump to line 330, read _preview(). \
BLOCKERS: None — all dependencies are in place." \
  -c proj_stixdb --tags in-progress,wizard --importance 0.95
```

---

## `stixdb ingest` vs `stixdb store` — Critical Distinction

These two commands serve completely different purposes. Using the wrong one is a common failure.

### `stixdb ingest` — For code files and documents (automated chunking)

`ingest` reads a file or directory, chunks it using AST-aware splitting (respecting function
and class boundaries), generates embeddings, and stores the chunks in the graph. The agent does
not write the content — StixDB handles it automatically.

**Use `ingest` for:**
- Source code files and directories (initial project orientation)
- README, docs, API specs, architecture diagrams
- Any file whose *content* should be semantically searchable

```bash
# Ingest the full codebase at project start
stixdb ingest ./ -c proj_myapp --tags source-code --chunk-size 600 --chunk-overlap 150

# Ingest a specific changed file after a major rewrite
stixdb ingest src/auth/hashing.py -c proj_myapp --tags source-code,auth

# Ingest documentation
stixdb ingest ./docs/architecture.md -c proj_myapp --tags architecture --importance 0.9
```

**Important:** `ingest` creates chunks of raw content — it does not store behavioral understanding,
decisions, or experiential knowledge. You must use `stixdb store` for those.

Re-ingest a file after significant changes so search returns current content, not stale chunks.

### `stixdb store` — For synthesized knowledge (agent-written)

`store` takes a text string you write, generates its embedding, and stores it as a node.
This is for experiential knowledge — things the agent has synthesized, decided, or learned.

**Use `store` for:**
- Everything in the templates section below
- Any knowledge that cannot be discovered by simply reading a file

---

## Storage Templates for Coding Agents

Use these templates. Fill in every field. Do not abbreviate.

### Bug Fix Template
```bash
stixdb store "BUG FIXED: [symptom — what was observed in logs/output/behavior]. \
ROOT CAUSE: [exact technical explanation — what was wrong in the code and why]. \
LOCATION: [file:line_number — function/class name]. \
FIX: [exactly what changed — the behavioral change, not the raw code]. \
VERIFIED: [how you confirmed the fix worked — log output, test result, manual check]. \
RELATED: [other files/functions involved or that should be checked]." \
  -c COLLECTION --tags bugfix,AREA --importance 0.9
```

### Module Map Template (structural — Layer 1)
```bash
stixdb store "MODULE MAP: [module or file name]. \
LOCATION: [file path, key line numbers for main classes/functions]. \
PURPOSE: [what this module does and why it exists in the system]. \
STRUCTURE: [key classes and functions, with line numbers and one-line descriptions each]. \
DEPENDENCIES: [what it imports from, what imports it — the call direction matters]. \
HOW IT CONNECTS: [data flow and call chain — how data enters and exits this module]. \
GOTCHAS: [non-obvious things that would trip up someone reading cold — naming confusion, \
  hidden side effects, initialization order requirements, etc]." \
  -c COLLECTION --tags file-map,architecture --importance 0.85
```

### API Surface Template (structural — Layer 1)
```bash
stixdb store "API SURFACE: [ClassName.method_name() or function_name()] at [file:line]. \
SIGNATURE: [full signature with types]. \
INPUT: [each parameter — type, valid values, gotchas]. \
OUTPUT: [return type and what it represents]. \
SIDE EFFECTS: [what this function changes in the world — DB writes, cache invalidation, events]. \
INVARIANTS: [contracts the caller must uphold — preconditions, postconditions]. \
CALLERS: [key call sites — file:line for each]. \
NOTE: [anything else critical — error cases, thread safety, performance profile]." \
  -c COLLECTION --tags api-surface,AREA --importance 0.85
```

### Pattern Discovered Template (experiential — Layer 2)
```bash
stixdb store "PATTERN: [name or one-line description of the pattern]. \
WHERE IT APPLIES: [which modules, layers, or situations this pattern governs]. \
THE RULE: [exactly what must be done — specific enough to follow without examples]. \
EXAMPLE LOCATION: [file:line where this pattern is canonically implemented]. \
GOTCHAS: [what breaks if you violate this pattern — and how it breaks (silently vs loudly)]. \
EXCEPTIONS: [any known legitimate exceptions to the rule and where they are]. \
DISCOVERED: [date and context — what led to finding this pattern]." \
  -c COLLECTION --tags pattern,AREA --importance 0.9
```

### Decision Template (experiential — Layer 2)
```bash
stixdb store "DECISION: [what was decided — one specific, unambiguous statement]. \
SUPERSEDES: [previous decision on this topic, if any — or 'none']. \
CONTEXT: [what problem this was solving — the situation that forced a decision]. \
RATIONALE: [why this option over the alternatives — the actual reasoning]. \
ALTERNATIVES REJECTED: [what else was considered and exactly why it was ruled out]. \
CONSEQUENCES: [constraints this creates going forward — what you must/must not do now]. \
DATE: [YYYY-MM-DD]." \
  -c COLLECTION --tags decisions,AREA --importance 0.95
```

### Refactor Template (experiential — Layer 2)
```bash
stixdb store "REFACTOR [YYYY-MM-DD]: [one-line description of what moved]. \
SUPERSEDES: [MODULE MAP or file-map entries that are now stale — list them]. \
WHAT MOVED: [old path → new path for every affected file/class/function]. \
WHAT STAYED: [files that look related but did NOT change — prevent unnecessary searching]. \
NEW ENTRY POINTS: [new canonical locations for things that moved]. \
HOW TO REACH IT NOW: [how callers need to update — import path, config, etc.]. \
GOTCHAS: [things that will break if someone uses the old paths]. \
MOTIVATION: [why the refactor happened — performance, maintainability, extraction, etc.]." \
  -c COLLECTION --tags refactor,file-map --importance 0.9
```

### In-Progress Template (experiential — Layer 2)
```bash
stixdb store "IN PROGRESS [YYYY-MM-DD]: [feature or task name — one line]. \
COMPLETED SO FAR: [specific things done, with file:line references for each]. \
CURRENT STATE: [exact state of the code right now — what works, what doesn't, what is broken]. \
REMAINING (in order): \
  1. [first remaining step — specific enough to execute without re-investigation] \
  2. [second step] \
  3. [third step — and so on] \
NEXT ACTION: [the exact first thing to do when resuming — file to open, line to jump to, \
  command to run]. \
BLOCKERS: [anything unclear or unresolved that must be addressed first — or 'none']." \
  -c COLLECTION --tags in-progress --importance 0.95
```

### Session Summary Template (experiential — Layer 2)
```bash
stixdb store "SESSION SUMMARY [YYYY-MM-DD]: [one-line description of the session's focus]. \
ACCOMPLISHED: \
  - [completed item 1 — with file:line reference] \
  - [completed item 2] \
DECISIONS MADE: \
  - [decision — or 'see DECISION entry: [topic]' if already stored separately] \
BUGS FIXED: \
  - [bug — with file:line reference — or 'see BUG FIXED entry: [topic]'] \
PATTERNS DISCOVERED: \
  - [pattern — or 'see PATTERN entry: [topic]'] \
CURRENT STATE: [where the project stands right now — what works end-to-end]. \
LEFT OFF AT: [exact stopping point — file, function, or task]. \
NEXT SESSION SHOULD START WITH: [specific first action — not a category, an action]." \
  -c COLLECTION --tags session-summary --importance 0.85
```

---

## One-Time Setup

Run once per machine. After this, every agent on this machine has persistent memory.

```bash
pip install stixdb-engine   # Install
stixdb init                 # Configure (wizard: LLM, embeddings, storage)
stixdb daemon start         # Start the background memory server
stixdb daemon status        # Verify it's running
```

---

## Session Startup — Run This Every Time

Do not open any files or start any work until you have completed this sequence.

```bash
stixdb daemon start
COLL="proj_$(basename $(pwd))"

# Step 1 — Full orientation via synthesis (LLM reasoning over memory)
stixdb ask "What is the current state of this project, what was I working on, \
  and what should I do next?" -c $COLL --top-k 25 --depth 3 --thinking 2 --hops 4

# Step 2 — Targeted recall for active work items
stixdb search "in progress" -c $COLL --top-k 5
stixdb search "known issues blockers" -c $COLL --top-k 5
stixdb search "user preferences" -c $COLL --top-k 3

# Step 3 — Check for superseded entries on your task area before touching anything
stixdb search "[your task area]" -c $COLL --top-k 10
# Read results carefully — if you see two conflicting entries, the one with SUPERSEDES: wins.
```

---

## Session End — Run This Every Time

```bash
COLL="proj_$(basename $(pwd))"
DATE=$(date +%Y-%m-%d)

# Check: did anything I worked on today change a previous fact?
# If yes — store a new entry with SUPERSEDES: before storing the summary.

# Store in-progress state with full detail
stixdb store "IN PROGRESS [$DATE]: [use the IN PROGRESS template above — full detail]" \
  -c $COLL --tags in-progress,$DATE --importance 0.95

# Store session summary
stixdb store "SESSION SUMMARY [$DATE]: [use the SESSION SUMMARY template above]" \
  -c $COLL --tags session-summary,$DATE --importance 0.85
```

---

## New Project Setup

```bash
COLL="proj_$(basename $(pwd))"

# Step 1 — Ingest the codebase so StixDB can chunk and embed it
stixdb ingest ./README.md -c $COLL --tags overview --importance 0.9
stixdb ingest ./ -c $COLL --tags source-code --chunk-size 600 --chunk-overlap 150

# Step 2 — Orient yourself
stixdb ask "What is this project, what does it do, and how is it structured?" \
  -c $COLL --top-k 20 --depth 3

# Step 3 — Store your initial architectural understanding using MODULE MAP template
# Do this for the top 3-5 most important modules. Do not store raw code.
stixdb store "MODULE MAP: [entry point module — full MODULE MAP template]" \
  -c $COLL --tags file-map,architecture --importance 0.9
```

---

## The Cardinal Rule: One Collection Per Coding Project

> **STRICT — Never mix coding projects into the same collection.**

Every coding project gets its own isolated collection.

### Naming Convention

```
proj_<repo-name>    →   proj_stixdb   proj_payments-api   proj_auth-service
```

### Why Mixing Projects Breaks Everything

- **Context contamination**: `stixdb ask` synthesises across all nodes — mixing projects means the LLM reasons over two codebases simultaneously and produces incoherent answers.
- **Decision bleed**: "We use Pydantic v2" is true in one project, false in another. The agent applies the wrong decision.
- **Stale path references**: `src/auth/hashing.py:23` is meaningless in a different repo.
- **SUPERSEDES failures**: Superseded entries from Project A surface as relevant during Project B work, making contamination impossible to detect.

---

## Core Commands

### Store (agent-written synthesized knowledge)
```bash
stixdb store "TEXT" -c COLLECTION --tags TAGS --importance 0.8 --node-type TYPE
```

### Ingest (file/directory chunking — automated)
```bash
stixdb ingest PATH -c COLLECTION --tags TAGS --chunk-size 600 --chunk-overlap 150
```

### Search (semantic recall — no LLM, fast)
```bash
stixdb search "QUERY" -c COLLECTION --top-k 10 --depth 2 --threshold 0.2
```

### Ask (LLM reasoning over memory — slower, costs tokens)
```bash
stixdb ask "QUESTION" -c COLLECTION --top-k 20 --depth 3 --thinking 2
```

### Manage
```bash
stixdb collections list
stixdb collections stats COLLECTION
stixdb daemon start | stop | restart | status | logs
```

---

## `ask` vs `search` — Know Which to Use

### `stixdb search` — Fast semantic lookup, zero LLM cost

Use `search` when:
- You need a **specific fact** you know is stored
- You want to **check for near-duplicates** before storing
- You are doing a **targeted mid-task recall**
- You need **raw nodes** to read yourself
- You want to **detect if a SUPERSEDES conflict exists**

```bash
stixdb search "api key config field" -c proj_myapp --top-k 5
stixdb search "database migration strategy" -c proj_myapp --top-k 3
stixdb search "in progress" -c proj_myapp --top-k 10 --threshold 0.1
```

### `stixdb ask` — LLM reasoning over memory, costs tokens

Use `ask` when:
- You need to **connect multiple pieces of context** across nodes
- You need **synthesis** — not just retrieval
- The answer **requires inference** ("what should I do next?")
- You are **starting a session** and need the full picture
- A question spans **more than one module or concept**

```bash
stixdb ask "What is the current state of this project and what should I work on next?" \
  -c proj_myapp --top-k 25 --depth 3

stixdb ask "How does configuration flow from disk through to the engine at runtime?" \
  -c proj_myapp --top-k 20 --depth 3

stixdb ask "What decisions have been made about the storage layer and why?" \
  -c proj_myapp --top-k 15 --depth 2
```

---

### `--top-k` and `--depth` Tuning Guide

| Situation | `--top-k` | `--depth` | Why |
|---|---|---|---|
| Session startup / full orientation | `25–30` | `3` | Broad, deep picture needed |
| Complex architectural question | `20` | `3` | Multiple interconnected nodes |
| Specific decision or bug | `15` | `2` | Focused context sufficient |
| Quick mid-task question | `10` | `1` | Speed matters, context narrow |
| Checking for a single fact | `5–8` | `1` | Minimal noise |

**`--top-k`** — nodes retrieved by semantic similarity before graph expansion. More = richer context, slower, more tokens.
**`--depth`** — hops traversed from each retrieved node along graph edges. `depth=3` is the practical maximum.

---

### `--thinking` and `--hops` — Multi-hop Reasoning Mode

Use when the answer is distributed across multiple nodes and requires following a "trail" through the graph.

| Flag | Default | When to increase |
|---|---|---|
| `--thinking` | `1` | Use `2–3` for complex/ambiguous questions spanning multiple modules |
| `--hops` | `4` | Increase if a single thinking step still misses context |

```bash
# Deep multi-module investigation
stixdb ask "Explain the data flow from REST API to database" \
  -c proj_myapp --thinking 2 --hops 4
```

---

## When to Store vs Search vs Ask

| Situation | Action |
|---|---|
| About to answer — check what is already known | `search` (fast) or `ask` if synthesis needed |
| Just read a file and understood it | Store MODULE MAP — full structural detail |
| Just fixed a bug | Store BUG FIXED — full root cause and fix |
| Just discovered a coding convention | Store PATTERN — the rule, where it lives, what breaks if violated |
| Just made a decision | Store DECISION — rationale and alternatives rejected |
| A fact changed from what was previously stored | Store new entry with SUPERSEDES: pointing to old topic |
| About to close the session | Store IN PROGRESS + SESSION SUMMARY |
| Starting a session | `ask --top-k 25 --depth 3`, then targeted `search` |
| User states a preference or constraint | Store immediately at `--importance 0.9` |
| Need a simple fact | `search` — do not waste an LLM call |
| Need inference across multiple pieces | `ask` — search alone will miss connections |
| Before storing — check for existing near-duplicate | `search` first — if match exists, supersede it, don't duplicate |

---

## Importance Guide

| Score | Use for |
|---|---|
| `1.0` | Hard invariants — must never be forgotten or superseded without explicit justification |
| `0.9–0.95` | IN PROGRESS entries, user preferences, critical decisions, active patterns |
| `0.85–0.9` | Bug fixes, refactors, architecture docs, API surfaces, session summaries |
| `0.7` | Normal facts, file locations, discovered but non-critical patterns |
| `0.5` | Background context |
| `0.2` | Ephemeral scratch |

---

## Session Continuity Tags

| Tag | Meaning |
|---|---|
| `in-progress` | Work started but not finished |
| `session-summary` | Full session narrative |
| `decisions` | Architecture or design decisions |
| `bugfix` | Bug found and fixed |
| `known-issues` | Problems not yet fixed |
| `todo` | Explicit next steps |
| `user-preferences` | How the user wants things done |
| `file-map` | Where things live in the codebase |
| `architecture` | Structural or design facts |
| `api-surface` | Function/class contracts |
| `pattern` | Discovered coding conventions |
| `refactor` | Code that moved or was restructured |
| `superseded` | Old entry now replaced (add to old-style entries when creating a superseding one) |
| `YYYY-MM-DD` | Date stamp — always add to in-progress and session-summary |

---

## The Four Memory Failure Modes — and How StixDB Prevents Them

| Failure Mode | What Happens | StixDB Prevention |
|---|---|---|
| **Overload** | Too much context retrieved — agent drowns, picks wrong thing | Tune `--top-k` and `--depth`. Store structured entries, not raw transcripts. |
| **Distraction** | Irrelevant memories retrieved alongside relevant ones | One collection per project. Use specific tags. Search before storing to keep graph clean. |
| **Contamination** | Incorrect/stale info sits alongside current info — agent picks wrong one | Always use SUPERSEDES pattern. Never just add — check and supersede. |
| **Drift** | Gradual degradation over sessions as facts accumulate and contradict | SESSION SUMMARY at every session end. Date-stamp everything. SUPERSEDES discipline. |

---

## Claude Code — Exact Integration

**Before your first tool call in any response:**
```bash
stixdb daemon start
stixdb ask "What context do I need for this task: [task description]?" \
  -c proj_$(basename $(pwd)) --top-k 20 --depth 3
```

**Before storing — always check for conflicts first:**
```bash
stixdb search "[topic of what you're about to store]" -c proj_$(basename $(pwd)) --top-k 5
# If an existing entry covers the same topic, write a SUPERSEDES entry — not a duplicate
```

**After your last tool call, before closing your response:**
```bash
COLL="proj_$(basename $(pwd))"
DATE=$(date +%Y-%m-%d)

stixdb store "BUG FIXED / DECISION / ARCHITECTURE / PATTERN: [FULL CONTENT — use templates]" \
  -c $COLL --tags TYPE,$DATE --importance 0.85

stixdb store "IN PROGRESS [$DATE]: [FULL IN-PROGRESS TEMPLATE]" \
  -c $COLL --tags in-progress --importance 0.95
```

---

## REST API (Claude Desktop / ChatGPT / HTTP-only Agents)

```bash
# Store
curl -X POST http://localhost:4020/collections/proj_myapp/nodes \
  -H "Content-Type: application/json" \
  -d '{"content": "FULL DETAILED CONTENT — use templates", "node_type": "fact", "importance": 0.85, "tags": ["architecture"]}'

# Search
curl -X POST http://localhost:4020/search \
  -H "Content-Type: application/json" \
  -d '{"query": "QUERY", "collection": "proj_myapp", "top_k": 10}'

# Ask
curl -X POST http://localhost:4020/collections/proj_myapp/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "QUESTION", "top_k": 20, "depth": 3}'
```

Add `-H "X-API-Key: YOUR_KEY"` if configured.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Cannot reach server` | `stixdb daemon start` |
| `No config found` | `stixdb init` |
| `command not found: stixdb` | `pip install stixdb-engine` |
| Search returns nothing | Lower `--threshold 0.1`, verify collection with `stixdb collections list` |
| Getting wrong project context | Wrong collection — `stixdb collections list`, use `proj_<repo>` |
| Daemon won't start | `stixdb daemon start --fg` to see error |
| Two conflicting entries on same topic | The one with `SUPERSEDES:` is current. Store a new SUPERSEDES entry if neither does. |
| Retrieval returns stale file paths | Run `stixdb search "[module name]" --top-k 10` — look for REFACTOR entries. Re-ingest changed files. |

---

## Quick Reference

```bash
# Setup (once)
pip install stixdb-engine && stixdb init && stixdb daemon start

# New project
COLL="proj_$(basename $(pwd))"
stixdb ingest ./ -c $COLL --tags source-code --chunk-size 600
stixdb ask "What is this project and how is it structured?" -c $COLL --top-k 20

# Every session start
stixdb daemon start
stixdb ask "Current state and where did we leave off?" -c proj_$(basename $(pwd)) --top-k 25 --depth 3

# Before storing — check for conflicts
stixdb search "[topic]" -c proj_$(basename $(pwd)) --top-k 5

# While working — full detail only, use templates
stixdb search "QUERY" -c proj_$(basename $(pwd)) --top-k 10
stixdb store "BUG FIXED/DECISION/MODULE MAP/PATTERN/REFACTOR: [full template]" \
  -c proj_$(basename $(pwd)) --importance 0.85
stixdb ask "QUESTION" -c proj_$(basename $(pwd)) --top-k 20 --depth 3

# Every session end
stixdb store "IN PROGRESS [DATE]: [full template]" -c proj_$(basename $(pwd)) --tags in-progress --importance 0.95
stixdb store "SESSION SUMMARY [DATE]: [full template]" -c proj_$(basename $(pwd)) --tags session-summary --importance 0.85
```