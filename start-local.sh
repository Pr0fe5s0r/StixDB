#!/usr/bin/env bash
# =============================================================================
# StixDB — Local Development Server (Linux / macOS)
# =============================================================================
# Starts StixDB with KuzuDB (embedded, persistent, no Docker required).
#
# Usage:
#   ./start-local.sh              # Start with defaults
#   ./start-local.sh --port 4021  # Custom port
#   ./start-local.sh --install    # Force reinstall deps
# =============================================================================

set -euo pipefail

PORT=4020
INSTALL=false
RELOAD=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)   PORT="$2"; shift 2 ;;
        --install) INSTALL=true; shift ;;
        --reload) RELOAD=true; shift ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

echo ""
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║     StixDB  —  Local Development Server         ║"
echo "  ║     Graph: KuzuDB (embedded, persistent)        ║"
echo "  ║     No Docker required                          ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo ""

# ── 1. Ensure .env exists ──────────────────────────────────────────────────
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp .env.example .env
    echo "  ✔  Created .env from .env.example"
fi

# ── 2. Install dependencies ────────────────────────────────────────────────
INSTALLED=false
python -c "import kuzu" 2>/dev/null && INSTALLED=true || true

if [ "$INSTALL" = true ] || [ "$INSTALLED" = false ]; then
    echo "  📦  Installing local-dev dependencies (kuzu + sentence-transformers)..."
    pip install -e ".[local-dev]"
    echo "  ✔  Dependencies installed"
else
    echo "  ✔  Dependencies already installed"
fi

# ── 3. Create data directory ───────────────────────────────────────────────
mkdir -p ./stixdb_data/kuzu
echo "  ✔  Data directory: ./stixdb_data/kuzu"

# ── 4. Export env vars for this session ───────────────────────────────────
export STIXDB_STORAGE_MODE=kuzu
export STIXDB_KUZU_PATH=./stixdb_data/kuzu
export STIXDB_VECTOR_BACKEND=memory
export STIXDB_DATA_DIR=./stixdb_data

echo ""
echo "  🚀  Starting StixDB API server on http://localhost:$PORT"
echo "  📚  API docs: http://localhost:$PORT/docs"
echo "  📊  Metrics:  http://localhost:$PORT/metrics"
echo "  💾  Graph DB: ./stixdb_data/kuzu  (persistent, survives restarts)"
echo ""
echo "  Press Ctrl+C to stop."
echo ""

if [ "$RELOAD" = true ]; then
    uvicorn stixdb.api.server:app --host 0.0.0.0 --port "$PORT" --reload
else
    uvicorn stixdb.api.server:app --host 0.0.0.0 --port "$PORT"
fi
