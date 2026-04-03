#!/usr/bin/env pwsh
# =============================================================================
# StixDB — Local Development Server (Windows PowerShell)
# =============================================================================
# Starts StixDB with KuzuDB (embedded, persistent, no Docker required).
#
# What this does:
#   1. Optionally installs local dependencies (kuzu + sentence-transformers)
#   2. Copies .env.example -> .env if no .env exists
#   3. Sets STIXDB_STORAGE_MODE=kuzu (embedded graph, data saved to ./stixdb_data/kuzu)
#   4. Starts the StixDB API server on http://localhost:4020
#
# Usage:
#   .\start-local.ps1              # Start with defaults
#   .\start-local.ps1 -Port 4021   # Custom port
#   .\start-local.ps1 -Install     # Force reinstall deps
# =============================================================================

param(
    [int]$Port    = 4020,
    [switch]$Install,
    [switch]$Reload
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║     StixDB  —  Local Development Server         ║" -ForegroundColor Cyan
Write-Host "  ║     Graph: KuzuDB (embedded, persistent)        ║" -ForegroundColor Cyan
Write-Host "  ║     No Docker required                          ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── 1. Ensure .env exists ──────────────────────────────────────────────────
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "  ✔  Created .env from .env.example" -ForegroundColor Green
    } else {
        Write-Host "  ⚠  No .env file found. Using environment variables / defaults." -ForegroundColor Yellow
    }
}

# ── 2. Install dependencies ────────────────────────────────────────────────
$installed = $false
try { python -c "import kuzu" 2>$null; $installed = $true } catch {}

if ($Install -or -not $installed) {
    Write-Host "  📦  Installing local-dev dependencies (kuzu + sentence-transformers)..." -ForegroundColor Yellow
    pip install -e ".[local-dev]"
    Write-Host "  ✔  Dependencies installed" -ForegroundColor Green
} else {
    Write-Host "  ✔  Dependencies already installed" -ForegroundColor Green
}

# ── 3. Create data directory ───────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path ".\stixdb_data\kuzu" | Out-Null
Write-Host "  ✔  Data directory: .\stixdb_data\kuzu" -ForegroundColor Green

# ── 4. Set KuzuDB as storage mode for this session ────────────────────────
$env:STIXDB_STORAGE_MODE = "kuzu"
$env:STIXDB_KUZU_PATH    = ".\stixdb_data\kuzu"
$env:STIXDB_VECTOR_BACKEND = "memory"
$env:STIXDB_DATA_DIR     = ".\stixdb_data"

Write-Host ""
Write-Host "  🚀  Starting StixDB API server on http://localhost:$Port" -ForegroundColor Cyan
Write-Host "  📚  API docs: http://localhost:$Port/docs" -ForegroundColor Cyan
Write-Host "  📊  Metrics:  http://localhost:$Port/metrics" -ForegroundColor Cyan
Write-Host "  💾  Graph DB: .\stixdb_data\kuzu  (persistent, survives restarts)" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Press Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host ""

if ($Reload) {
    uvicorn stixdb.api.server:app --host 0.0.0.0 --port $Port --reload
} else {
    uvicorn stixdb.api.server:app --host 0.0.0.0 --port $Port
}
