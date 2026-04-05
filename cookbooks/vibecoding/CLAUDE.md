# StixDB Shared Memory — Claude Code Instructions

This file tells Claude Code how to use the shared memory script during vibecoding sessions.

## On session start — ALWAYS run this first

```bash
python cookbooks/vibecoding/shared_memory.py context
```

This restores full project context from all previous sessions and agents. Never skip this.

## During the session — store decisions as you make them

```bash
# Architectural or design decisions
python cookbooks/vibecoding/shared_memory.py decision "We use React Query for all data fetching"

# Code patterns and conventions discovered or established
python cookbooks/vibecoding/shared_memory.py pattern "API route handlers live in src/app/api/ — one folder per resource"

# Bug fixes — so no agent ever repeats the same mistake
python cookbooks/vibecoding/shared_memory.py bug "Next.js 14 server components cannot use useState — must add 'use client' directive"

# General facts that don't fit the above
python cookbooks/vibecoding/shared_memory.py store "Deployment target is Vercel, not AWS"
```

## Ask questions against memory at any time

```bash
python cookbooks/vibecoding/shared_memory.py ask "How does authentication work?"
python cookbooks/vibecoding/shared_memory.py ask "What database ORM are we using?"
python cookbooks/vibecoding/shared_memory.py ask "Any known bugs with the payment flow?"
```

## On session end — store what you did and what's next

```bash
python cookbooks/vibecoding/shared_memory.py progress "Completed user dashboard. Next: notifications system."
```

## Index source code into memory

```bash
# Run once when starting on a new codebase, or after major refactors
python cookbooks/vibecoding/shared_memory.py ingest ./src
```

## Check memory health

```bash
python cookbooks/vibecoding/shared_memory.py status
```

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Enables Claude reasoning for `ask` and `context` | — |
| `OPENAI_API_KEY` | Enables GPT-4o reasoning (fallback) | — |
| `STIXDB_VIBE_PATH` | Path to the memory store on disk | `./vibecode_memory` |
| `STIXDB_VIBE_PROJECT` | Collection name (one per project) | `vibecode` |

## Multiple projects

Use `--project` to keep memories separate:

```bash
python cookbooks/vibecoding/shared_memory.py context --project frontend
python cookbooks/vibecoding/shared_memory.py context --project backend
```

## Sharing memory across machines

Point `STIXDB_VIBE_PATH` at a shared volume or sync the directory with rsync/Dropbox/git-lfs:

```bash
export STIXDB_VIBE_PATH=/shared/team_memory
python cookbooks/vibecoding/shared_memory.py context
```
