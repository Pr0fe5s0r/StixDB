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

## OS Compatibility — Set Your Shell Variables First

StixDB's CLI works identically on all platforms. Only the **shell syntax for setting variables**
and **line continuation characters** differ. Identify your OS once, use the right block everywhere.

### macOS / Linux — bash or zsh

```bash
# Set once at the start of every session
COLL="proj_$(basename $(pwd))"
DATE=$(date +%Y-%m-%d)

# Use in commands
stixdb ask "..." -c $COLL
stixdb store "..." -c $COLL --tags TAG --importance 0.9
# Line continuation inside a command: backslash \
stixdb store "LINE ONE \
LINE TWO" -c $COLL
```

### Windows — PowerShell (recommended for Windows)

```powershell
# Set once at the start of every session
$COLL = "proj_$((Get-Location).Name)"
$DATE = Get-Date -Format "yyyy-MM-dd"

# Use in commands
stixdb ask "..." -c $COLL
stixdb store "..." -c $COLL --tags TAG --importance 0.9
# Line continuation inside a command: backtick `
stixdb store "LINE ONE `
LINE TWO" -c $COLL
```

### Windows — Command Prompt (CMD)

```cmd
:: Set once at the start of every session
for %I in (.) do set COLL=proj_%~nxI
set DATE=%date:~10,4%-%date:~4,2%-%date:~7,2%

:: Use in commands  (note: %COLL% not $COLL)
stixdb ask "..." -c %COLL%
stixdb store "..." -c %COLL% --tags TAG --importance 0.9
:: Line continuation: caret ^
stixdb store "LINE ONE ^
LINE TWO" -c %COLL%
```

> **Windows recommendation:** Use PowerShell. CMD date parsing varies by locale and is fragile.
> PowerShell is available on all modern Windows systems and works reliably.

> **All platforms:** The `stixdb` CLI commands themselves (`store`, `search`, `ask`, `ingest`,
> `daemon`) are identical across all OSes. Only the shell wrapper syntax differs.

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

**macOS / Linux:**
```bash
pip install stixdb-engine   # Install (use pip3 if pip points to Python 2)
stixdb init                 # Configure (wizard: LLM, embeddings, storage)
stixdb daemon start         # Start the background memory server
stixdb daemon status        # Verify it's running
```

**Windows (PowerShell or CMD):**
```powershell
pip install stixdb-engine   # Same command on Windows
stixdb init                 # Same wizard — fully cross-platform
stixdb daemon start         # Runs as a background process on Windows too
stixdb daemon status        # Verify it's running
```

> **Windows PATH note:** If `stixdb` is not found after install, your Python Scripts folder may
> not be in PATH. Run `python -m stixdb` as a fallback, or add the Scripts directory to PATH:
> `%APPDATA%\Python\PythonXX\Scripts` (replace XX with your Python version).

---

## Session Startup — Run This Every Time

Do not open any files or start any work until you have completed this sequence.

**macOS / Linux:**
```bash
stixdb daemon start
COLL="proj_$(basename $(pwd))"

# Step 1 — Full structured orientation (NEVER ask generically — always ask in sub-questions)
stixdb ask "I am starting a new session on this project. \
  Answer each of these specifically: \
  (1) What tasks are currently in progress — list each with its exact next action. \
  (2) What decisions were made in recent sessions that I must not contradict? \
  (3) Are there any known bugs, blockers, or unresolved issues? \
  (4) What should I work on first, and why?" \
  -c $COLL --top-k 25 --depth 3 --thinking 2 --hops 4

# Step 2 — Targeted recall for specific entry types
stixdb search "in progress" -c $COLL --top-k 5
stixdb search "known issues blockers" -c $COLL --top-k 5
stixdb search "user preferences" -c $COLL --top-k 3

# Step 3 — Once you know your task, ask a focused question about THAT specific area
# Replace [task area] with the actual module or feature you are about to touch
stixdb ask "I am about to work on [task area]. \
  What decisions apply here, what bugs were previously fixed in this area, \
  and what patterns must I follow?" \
  -c $COLL --top-k 20 --depth 3
```

**Windows (PowerShell):**
```powershell
stixdb daemon start
$COLL = "proj_$((Get-Location).Name)"

# Step 1 — Full structured orientation
stixdb ask "I am starting a new session on this project. Answer each of these specifically: (1) What tasks are currently in progress — list each with its exact next action. (2) What decisions were made in recent sessions that I must not contradict? (3) Are there any known bugs, blockers, or unresolved issues? (4) What should I work on first, and why?" -c $COLL --top-k 25 --depth 3 --thinking 2 --hops 4

# Step 2 — Targeted recall
stixdb search "in progress" -c $COLL --top-k 5
stixdb search "known issues blockers" -c $COLL --top-k 5
stixdb search "user preferences" -c $COLL --top-k 3

# Step 3 — Focused question about your specific task area
stixdb ask "I am about to work on [task area]. What decisions apply here, what bugs were fixed in this area before, and what patterns must I follow?" -c $COLL --top-k 20 --depth 3
```

**Windows (CMD):**
```cmd
stixdb daemon start
for %I in (.) do set COLL=proj_%~nxI

stixdb ask "I am starting a new session. What tasks are in progress with their next actions? What recent decisions must I not contradict? Any known bugs or blockers? What should I start with?" -c %COLL% --top-k 25 --depth 3 --thinking 2 --hops 4
stixdb search "in progress" -c %COLL% --top-k 5
stixdb search "known issues blockers" -c %COLL% --top-k 5
stixdb search "user preferences" -c %COLL% --top-k 3
stixdb ask "I am about to work on [task area]. What decisions apply, what bugs were fixed here, what patterns must I follow?" -c %COLL% --top-k 20 --depth 3
```

> Read results carefully at Step 3 — if you see two conflicting entries, the one with `SUPERSEDES:` wins.

---

## Session End — Run This Every Time

**macOS / Linux:**
```bash
COLL="proj_$(basename $(pwd))"
DATE=$(date +%Y-%m-%d)

# Check: did anything I worked on today change a previous fact?
# If yes — store a SUPERSEDES entry before storing the summary.

stixdb store "IN PROGRESS [$DATE]: [use IN PROGRESS template — full detail]" \
  -c $COLL --tags in-progress,$DATE --importance 0.95

stixdb store "SESSION SUMMARY [$DATE]: [use SESSION SUMMARY template]" \
  -c $COLL --tags session-summary,$DATE --importance 0.85
```

**Windows (PowerShell):**
```powershell
$COLL = "proj_$((Get-Location).Name)"
$DATE = Get-Date -Format "yyyy-MM-dd"

stixdb store "IN PROGRESS [$DATE]: [use IN PROGRESS template — full detail]" `
  -c $COLL --tags "in-progress,$DATE" --importance 0.95

stixdb store "SESSION SUMMARY [$DATE]: [use SESSION SUMMARY template]" `
  -c $COLL --tags "session-summary,$DATE" --importance 0.85
```

**Windows (CMD):**
```cmd
for %I in (.) do set COLL=proj_%~nxI
for /f "tokens=2 delims==" %I in ('wmic os get localdatetime /value') do set DT=%I
set DATE=%DT:~0,4%-%DT:~4,2%-%DT:~6,2%

stixdb store "IN PROGRESS [%DATE%]: [full IN PROGRESS template]" -c %COLL% --tags in-progress --importance 0.95
stixdb store "SESSION SUMMARY [%DATE%]: [full SESSION SUMMARY template]" -c %COLL% --tags session-summary --importance 0.85
```

---

## New Project Setup

**macOS / Linux:**
```bash
COLL="proj_$(basename $(pwd))"

stixdb ingest ./README.md -c $COLL --tags overview --importance 0.9
stixdb ingest ./ -c $COLL --tags source-code --chunk-size 600 --chunk-overlap 150

stixdb ask "I have just ingested this codebase for the first time. \
  What is this project, what problem does it solve, what are the main modules, \
  and what is the entry point I should read first to understand how it works?" \
  -c $COLL --top-k 20 --depth 3

stixdb store "MODULE MAP: [entry point module — full MODULE MAP template]" \
  -c $COLL --tags file-map,architecture --importance 0.9
```

**Windows (PowerShell):**
```powershell
$COLL = "proj_$((Get-Location).Name)"

stixdb ingest .\README.md -c $COLL --tags overview --importance 0.9
stixdb ingest .\ -c $COLL --tags source-code --chunk-size 600 --chunk-overlap 150

stixdb ask "What is this project, what does it do, and how is it structured?" -c $COLL --top-k 20 --depth 3

stixdb store "MODULE MAP: [entry point module — full MODULE MAP template]" `
  -c $COLL --tags file-map,architecture --importance 0.9
```

**Windows (CMD):**
```cmd
for %I in (.) do set COLL=proj_%~nxI

stixdb ingest .\README.md -c %COLL% --tags overview --importance 0.9
stixdb ingest .\ -c %COLL% --tags source-code --chunk-size 600 --chunk-overlap 150
stixdb ask "What is this project and how is it structured?" -c %COLL% --top-k 20 --depth 3
stixdb store "MODULE MAP: [entry point module — full MODULE MAP template]" -c %COLL% --tags file-map,architecture --importance 0.9
```

> **Path separators:** `stixdb ingest` accepts both `/` and `\` on all platforms. Using `./` on
> Windows PowerShell is also valid — PowerShell handles forward slashes transparently.

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

## How to Ask Good Questions — The #1 Query Mistake

> **This is the most common runtime failure in agents using StixDB.**
> Generic questions with low `top_k` return near-empty results, cause reasoning model failures,
> and give the agent false confidence that there is no relevant memory.

### The Bad Pattern

```json
{ "question": "What was I working on?", "top_k": 5 }
```

This is wrong for three reasons:

1. **No task context injected** — the LLM has no anchor to pull relevant nodes. "What was I working on?" matches everything and nothing simultaneously. The retrieval is unfocused, the reasoning model gets semi-random nodes, and returns empty or hallucinated output.

2. **`top_k: 5` is too low for any orientation query** — 5 nodes out of potentially hundreds means a >90% chance the relevant context was not retrieved. The reasoning model then synthesizes from irrelevant nodes and either returns empty or confidently wrong answers.

3. **No `depth` or `thinking`** — no graph traversal, no multi-hop reasoning. Connected nodes (e.g., a DECISION linked to an IN PROGRESS linked to a BUG FIXED) are never reached.

---

### The Good Pattern

Always inject two things into every `ask` query:
- **What you are currently trying to do** (the task)
- **What specific context you need** (not "everything", but a focused question)

```json
{
  "question": "I am about to work on the authentication module. What decisions were made about auth, what bugs were fixed there, and what was left in progress?",
  "top_k": 20,
  "depth": 3,
  "thinking": 2
}
```

The question gives the retrieval step a semantic anchor. `top_k: 20` ensures broad coverage. `depth: 3` pulls in connected nodes. `thinking: 2` lets the agent follow multi-hop trails.

---

### Question Templates by Situation

**Session startup — full orientation:**
```
"I am starting a new session on [project name]. What is the current state of the project,
what was I last working on, what decisions have been made, and what should I do first?"
```
Parameters: `top_k: 25, depth: 3, thinking: 2, hops: 4`

**Before touching a specific area:**
```
"I am about to work on [specific module or feature]. What do I need to know —
decisions made, bugs fixed, patterns that apply, and anything in progress?"
```
Parameters: `top_k: 20, depth: 3`

**Before making a decision:**
```
"I need to decide [X]. What relevant decisions have already been made in this project
that I should know about? What constraints exist?"
```
Parameters: `top_k: 15, depth: 2`

**Debugging a specific symptom:**
```
"I am seeing [exact symptom]. What do we know about this — has it happened before,
what was the root cause, what was tried?"
```
Parameters: `top_k: 15, depth: 3, thinking: 2`

**Before storing something:**
```
# Use search, not ask — faster and sufficient for duplicate detection
stixdb search "[topic of what you're about to store]" --top-k 5
```

---

### Minimum Parameters by Query Type

| Query type | `top_k` | `depth` | `thinking` | Why |
|---|---|---|---|---|
| Session startup | `25` | `3` | `2` | Need broad coverage + multi-hop |
| Module/feature orientation | `20` | `3` | `1–2` | Multiple connected nodes |
| Specific decision or bug | `15` | `2` | `1` | Focused but needs context |
| Quick mid-task fact | `10` | `1` | `1` | Speed, narrow scope |
| Duplicate check before storing | use `search` | — | — | No LLM needed |

> **Hard rule:** Never use `top_k` below `10` for `ask`. If you are considering `top_k: 5`,
> use `search` instead — it is faster and doesn't invoke the LLM at all.

---

### Handling Empty Responses

If the reasoning model returns an empty response, it means one of three things:

| Cause | Diagnosis | Fix |
|---|---|---|
| `top_k` too low — relevant nodes not retrieved | Run `stixdb search "[topic]" --top-k 20` and check if nodes exist | Retry with `top_k: 20–25` |
| Collection is empty or wrong collection | `stixdb collections stats COLLECTION` — check node count | Ingest project files first, or verify collection name |
| Question too generic — no semantic anchor for retrieval | The question matches nothing specifically | Rewrite question with explicit task context (see templates above) |
| LLM timeout or daemon issue | `stixdb daemon status` | Restart daemon, retry |



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

#### The Question Construction Rule

Every `ask` query must contain **three elements**:

```
1. What you are currently doing or about to do  (task context — the anchor)
2. What specific information you need           (focused question, not "everything")
3. What areas or modules are relevant           (scope — narrows retrieval)
```

Without element 1, the vector search has no semantic anchor and returns semi-random nodes.
Without elements 2 and 3, the LLM synthesizes from noise and may return empty.

#### Good Examples

```bash
# Session startup — structured sub-questions, never "what was I doing?"
stixdb ask "I am starting a new session. \
  (1) What tasks are in progress with their exact next action? \
  (2) What decisions were made recently that constrain my work? \
  (3) Any known bugs or blockers? \
  (4) What should I start with?" \
  -c proj_myapp --top-k 25 --depth 3 --thinking 2

# Before touching a specific module
stixdb ask "I am about to modify the auth module. \
  What decisions govern how auth works, what bugs were fixed there, \
  and what patterns must I follow when changing it?" \
  -c proj_myapp --top-k 20 --depth 3

# Before making an architectural decision
stixdb ask "I need to decide how to add rate limiting. \
  What relevant decisions were already made about the API layer, \
  what constraints exist, and have we discussed rate limiting before?" \
  -c proj_myapp --top-k 15 --depth 2

# Debugging a specific symptom
stixdb ask "I am seeing 500 errors on POST /users during load testing. \
  Has this happened before? What do we know about the user creation path, \
  what bugs were fixed there, and what patterns apply?" \
  -c proj_myapp --top-k 20 --depth 3 --thinking 2

# Understanding a module before editing it
stixdb ask "I am about to refactor the config loading chain. \
  How does configuration flow from disk to the runtime engine? \
  Which modules are involved and in what order?" \
  -c proj_myapp --top-k 20 --depth 3 --thinking 2 --hops 4
```

#### Bad Examples — Do Not Use

```bash
# ❌ No task context — matches everything, anchors nothing
stixdb ask "What was I working on?" -c proj_myapp --top-k 5

# ❌ Too vague — LLM gets unrelated nodes and returns empty or wrong answer
stixdb ask "Current state?" -c proj_myapp --top-k 10

# ❌ top_k too low for any ask — use search instead if you want just 5 nodes
stixdb ask "What is the database schema?" -c proj_myapp --top-k 5

# ❌ No scope — "everything" is not a question
stixdb ask "Tell me everything about this project" -c proj_myapp --top-k 25
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
# Deep multi-module investigation — always state what you are about to do
stixdb ask "I am about to modify the data ingestion pipeline. \
  Walk me through the full data flow from the REST API to the database — \
  which modules are involved in order, what contracts must be honoured, \
  and where have bugs occurred in this path before?" \
  -c proj_myapp --top-k 20 --depth 3 --thinking 2 --hops 4
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

Always compose your `ask` question with three elements before calling it:
`(1) what you are about to do` + `(2) what you specifically need` + `(3) which area/module is in scope`

macOS / Linux:
```bash
stixdb daemon start
# Fill in all three placeholders — never send a generic question to ask
stixdb ask "I am about to [exact task description]. \
  What decisions apply to [module or area]? \
  What bugs were previously fixed here? \
  What patterns must I follow? \
  Is anything currently in progress that this work might affect?" \
  -c proj_$(basename $(pwd)) --top-k 20 --depth 3
```

Windows (PowerShell):
```powershell
stixdb daemon start
# Fill in all three placeholders — never send a generic question to ask
stixdb ask "I am about to [exact task description]. What decisions apply to [module or area]? What bugs were previously fixed here? What patterns must I follow? Is anything in progress that this work might affect?" -c "proj_$((Get-Location).Name)" --top-k 20 --depth 3
```

**Before storing — always check for conflicts first:**

```bash
# macOS / Linux
stixdb search "[topic of what you're about to store]" -c proj_$(basename $(pwd)) --top-k 5

# Windows PowerShell
stixdb search "[topic of what you're about to store]" -c "proj_$((Get-Location).Name)" --top-k 5

# Windows CMD
stixdb search "[topic]" -c %COLL% --top-k 5
```

If an existing entry covers the same topic, write a SUPERSEDES entry — not a duplicate.

**After your last tool call, before closing your response:**

macOS / Linux:
```bash
COLL="proj_$(basename $(pwd))"
DATE=$(date +%Y-%m-%d)

stixdb store "BUG FIXED / DECISION / MODULE MAP / PATTERN: [FULL CONTENT — use templates]" \
  -c $COLL --tags TYPE,$DATE --importance 0.85

stixdb store "IN PROGRESS [$DATE]: [FULL IN-PROGRESS TEMPLATE]" \
  -c $COLL --tags in-progress --importance 0.95
```

Windows (PowerShell):
```powershell
$COLL = "proj_$((Get-Location).Name)"
$DATE = Get-Date -Format "yyyy-MM-dd"

stixdb store "BUG FIXED / DECISION / MODULE MAP / PATTERN: [FULL CONTENT — use templates]" `
  -c $COLL --tags "TYPE,$DATE" --importance 0.85

stixdb store "IN PROGRESS [$DATE]: [FULL IN-PROGRESS TEMPLATE]" `
  -c $COLL --tags in-progress --importance 0.95
```

---

## REST API (Claude Desktop / ChatGPT / HTTP-only Agents)

**macOS / Linux / Windows with curl:**
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

**Windows (PowerShell — if curl is unavailable):**
```powershell
# Store
Invoke-WebRequest -Method POST http://localhost:4020/collections/proj_myapp/nodes `
  -ContentType "application/json" `
  -Body '{"content": "FULL DETAILED CONTENT", "node_type": "fact", "importance": 0.85, "tags": ["architecture"]}'

# Search
Invoke-WebRequest -Method POST http://localhost:4020/search `
  -ContentType "application/json" `
  -Body '{"query": "QUERY", "collection": "proj_myapp", "top_k": 10}'

# Ask
Invoke-WebRequest -Method POST http://localhost:4020/collections/proj_myapp/ask `
  -ContentType "application/json" `
  -Body '{"question": "QUESTION", "top_k": 20, "depth": 3}'
```

> **Windows curl note:** Windows 10 (1803+) and Windows 11 ship with `curl.exe` natively.
> In PowerShell, `curl` is an alias for `Invoke-WebRequest` — to use the real curl binary,
> call it explicitly as `curl.exe` instead of `curl`.

Add `-H "X-API-Key: YOUR_KEY"` (curl) or `-Headers @{"X-API-Key"="YOUR_KEY"}` (PowerShell) if configured.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Cannot reach server` | `stixdb daemon start` |
| `No config found` | `stixdb init` |
| `command not found: stixdb` (Mac/Linux) | `pip install stixdb-engine` — ensure pip's bin dir is in PATH |
| `stixdb is not recognized` (Windows) | Run `pip install stixdb-engine` then restart terminal. If still missing, try `python -m stixdb` or add `%APPDATA%\Python\PythonXX\Scripts` to PATH |
| Search returns nothing | Lower `--threshold 0.1`, verify collection with `stixdb collections list` |
| Getting wrong project context | Wrong collection — `stixdb collections list`, use `proj_<repo>` |
| Daemon won't start (Mac/Linux) | `stixdb daemon start --fg` to see error output |
| Daemon won't start (Windows) | Run `stixdb daemon start` in PowerShell as Administrator if port 4020 is blocked by firewall |
| Two conflicting entries on same topic | The one with `SUPERSEDES:` is current. Store a new SUPERSEDES entry if neither does. |
| Retrieval returns stale file paths | Run `stixdb search "[module name]" --top-k 10` — look for REFACTOR entries. Re-ingest changed files. |
| `curl` not working on Windows PowerShell | Use `curl.exe` explicitly, or use `Invoke-WebRequest` — see REST API section |
| Variable `$COLL` is empty (Windows CMD) | Use `for %I in (.) do set COLL=proj_%~nxI` — the `for` trick is required to get the folder basename |
| Date format wrong in CMD | Use the `wmic` method from the Session End section — `%DATE%` format is locale-dependent |

---

## Quick Reference

**macOS / Linux:**
```bash
# Setup (once)
pip install stixdb-engine && stixdb init && stixdb daemon start

# New project
COLL="proj_$(basename $(pwd))"
stixdb ingest ./ -c $COLL --tags source-code --chunk-size 600
stixdb ask "I have just ingested this codebase. What is this project, what does it do, what are the main modules, and what should I read first?" -c $COLL --top-k 20 --depth 3

# Every session start — structured sub-questions, never a generic "what was I doing?"
stixdb daemon start
COLL="proj_$(basename $(pwd))"
stixdb ask "I am starting a new session. \
  (1) What tasks are in progress with their exact next action? \
  (2) What decisions were made recently that I must not contradict? \
  (3) Any known bugs or blockers? \
  (4) What should I start with?" \
  -c $COLL --top-k 25 --depth 3 --thinking 2

# Before touching a specific area — inject your task
stixdb ask "I am about to work on [module/feature]. \
  What decisions apply, what bugs were fixed here, what patterns must I follow?" \
  -c $COLL --top-k 20 --depth 3

# Before storing — check for conflicts
stixdb search "[topic]" -c $COLL --top-k 5

# While working — search for facts, ask for synthesis
stixdb search "SPECIFIC FACT OR TERM" -c $COLL --top-k 10
stixdb store "BUG FIXED/DECISION/MODULE MAP/PATTERN/REFACTOR: [full template]" \
  -c $COLL --importance 0.85
stixdb ask "I am debugging [symptom]. What do we know about this — prior bugs, related decisions, patterns in this area?" \
  -c $COLL --top-k 20 --depth 3

# Every session end
DATE=$(date +%Y-%m-%d)
stixdb store "IN PROGRESS [$DATE]: [full template]" -c $COLL --tags in-progress --importance 0.95
stixdb store "SESSION SUMMARY [$DATE]: [full template]" -c $COLL --tags session-summary --importance 0.85
```

**Windows (PowerShell):**
```powershell
# Setup (once)
pip install stixdb-engine; stixdb init; stixdb daemon start

# New project
$COLL = "proj_$((Get-Location).Name)"
stixdb ingest .\ -c $COLL --tags source-code --chunk-size 600
stixdb ask "I have just ingested this codebase. What is this project, what does it do, what are the main modules, and what should I read first?" -c $COLL --top-k 20 --depth 3

# Every session start — structured sub-questions
stixdb daemon start
$COLL = "proj_$((Get-Location).Name)"
stixdb ask "I am starting a new session. (1) What tasks are in progress with their exact next action? (2) What decisions were made recently that I must not contradict? (3) Any known bugs or blockers? (4) What should I start with?" -c $COLL --top-k 25 --depth 3 --thinking 2

# Before touching a specific area
stixdb ask "I am about to work on [module/feature]. What decisions apply, what bugs were fixed here, what patterns must I follow?" -c $COLL --top-k 20 --depth 3

# Before storing — check for conflicts
stixdb search "[topic]" -c $COLL --top-k 5

# While working
stixdb search "SPECIFIC FACT OR TERM" -c $COLL --top-k 10
stixdb store "BUG FIXED/DECISION/MODULE MAP/PATTERN/REFACTOR: [full template]" `
  -c $COLL --importance 0.85
stixdb ask "I am debugging [symptom]. What do we know — prior bugs, related decisions, patterns in this area?" -c $COLL --top-k 20 --depth 3

# Every session end
$DATE = Get-Date -Format "yyyy-MM-dd"
stixdb store "IN PROGRESS [$DATE]: [full template]" -c $COLL --tags in-progress --importance 0.95
stixdb store "SESSION SUMMARY [$DATE]: [full template]" -c $COLL --tags session-summary --importance 0.85
```

**Windows (CMD):**
```cmd
:: Setup (once)
pip install stixdb-engine && stixdb init && stixdb daemon start

:: New project
for %I in (.) do set COLL=proj_%~nxI
stixdb ingest .\ -c %COLL% --tags source-code --chunk-size 600
stixdb ask "I have just ingested this codebase. What is this project, what does it do, what are the main modules, and what should I read first?" -c %COLL% --top-k 20 --depth 3

:: Every session start — structured sub-questions, never generic
stixdb daemon start
for %I in (.) do set COLL=proj_%~nxI
stixdb ask "I am starting a new session. (1) Tasks in progress with exact next actions? (2) Recent decisions I must not contradict? (3) Known bugs or blockers? (4) What should I start with?" -c %COLL% --top-k 25 --depth 3 --thinking 2

:: Before touching a specific area
stixdb ask "I am about to work on [module/feature]. What decisions apply, what bugs were fixed here, what patterns must I follow?" -c %COLL% --top-k 20 --depth 3

:: While working
stixdb search "SPECIFIC FACT OR TERM" -c %COLL% --top-k 10
stixdb store "BUG FIXED/DECISION/MODULE MAP/PATTERN: [full template]" -c %COLL% --importance 0.85
stixdb ask "I am debugging [symptom]. What do we know — prior bugs, decisions, patterns in this area?" -c %COLL% --top-k 20 --depth 3

:: Session end
for /f "tokens=2 delims==" %I in ('wmic os get localdatetime /value') do set DT=%I
set DATE=%DT:~0,4%-%DT:~4,2%-%DT:~6,2%
stixdb store "IN PROGRESS [%DATE%]: [full template]" -c %COLL% --tags in-progress --importance 0.95
stixdb store "SESSION SUMMARY [%DATE%]: [full template]" -c %COLL% --tags session-summary --importance 0.85
```