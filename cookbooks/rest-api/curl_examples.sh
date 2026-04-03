#!/bin/bash
# REST API Examples with curl
# ============================
#
# Prerequisites:
#   • StixDB server running: stixdb serve --port 4020
#   • curl installed
#   • export STIXDB_API_KEY=your-key (if using API key)
#   • export OPENAI_API_KEY=sk-... (if using ask/chat)

set -e

BASE="http://localhost:4020"
COLLECTION="my_agent"
API_KEY="${STIXDB_API_KEY:-test-key}"

echo "=== StixDB REST API Examples ==="
echo ""
echo "Base URL: $BASE"
echo "Collection: $COLLECTION"
echo ""

# Helper function to pretty print
function hr() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  $1"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}

# 1. Health check
hr "1. Health Check"
curl -s -H "X-API-Key: $API_KEY" "$BASE/health" | jq .
echo ""

# 2. Store a memory
hr "2. Store a Memory"
curl -s -X POST "$BASE/collections/$COLLECTION/nodes" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Alice leads the payments team",
    "node_type": "entity",
    "tags": ["team", "contacts"],
    "importance": 0.9
  }' | jq .

echo ""

# 3. Bulk store
hr "3. Bulk Store Memories"
curl -s -X POST "$BASE/collections/$COLLECTION/nodes/bulk" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '[
    {
      "content": "Project deadline is June 1st, 2026",
      "node_type": "fact",
      "tags": ["deadline"],
      "importance": 0.85
    },
    {
      "content": "Sprint 1 includes payment gateway integration",
      "node_type": "event",
      "tags": ["sprint"],
      "importance": 0.7
    }
  ]' | jq .

echo ""

# 4. List nodes
hr "4. List Nodes in Collection"
curl -s "$BASE/collections/$COLLECTION/nodes?limit=5" \
  -H "X-API-Key: $API_KEY" | jq '.nodes[] | {id, content}'

echo ""

# 5. Retrieve (Search API, no LLM)
hr "5. Retrieve (Search, no LLM cost)"
curl -s -X POST "$BASE/collections/$COLLECTION/retrieve" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Who is responsible for payments?",
    "top_k": 3,
    "threshold": 0.2
  }' | jq '.results[] | {score, content}'

echo ""

# 6. Ask (Agentic reasoning with LLM)
hr "6. Agentic Question Answering (with LLM reasoning)"
curl -s -X POST "$BASE/collections/$COLLECTION/ask" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Who is responsible for the payments deadline?",
    "top_k": 5
  }' | jq '{answer, confidence, sources: [.sources[] | {content, score}]}'

echo ""

# 7. Graph stats
hr "7. Collection Stats"
curl -s "$BASE/collections/$COLLECTION/stats" \
  -H "X-API-Key: $API_KEY" | jq .

echo ""

# 8. Agent status
hr "8. Agent Status"
curl -s "$BASE/collections/$COLLECTION/agent/status" \
  -H "X-API-Key: $API_KEY" | jq .

echo ""

# 9. Trigger agent cycle
hr "9. Trigger Agent Cycle Manually"
curl -s -X POST "$BASE/collections/$COLLECTION/agent/cycle" \
  -H "X-API-Key: $API_KEY" | jq .

echo ""

# 10. OpenAI-compatible endpoint
hr "10. OpenAI-Compatible /chat/completions"
curl -s -X POST "$BASE/v1/chat/completions" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "'$COLLECTION'",
    "messages": [
      {"role": "user", "content": "What is the project status?"}
    ],
    "temperature": 0.2,
    "max_tokens": 500
  }' | jq '.choices[0].message'

echo ""

# 11. List models (available collections)
hr "11. List Models (Collections)"
curl -s "$BASE/v1/models" \
  -H "X-API-Key: $API_KEY" | jq '.data[] | {id}'

echo ""

# 12. Cross-collection search
hr "12. Cross-Collection Search"
curl -s -X POST "$BASE/search" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "deadline",
    "collections": ["'$COLLECTION'"],
    "max_results": 3,
    "top_k": 3
  }' | jq '.results[] | {score, content, collection}'

echo ""

# 13. Get traces
hr "13. Get Traces (Reasoning Log)"
curl -s "$BASE/traces?collection=$COLLECTION&limit=3" \
  -H "X-API-Key: $API_KEY" | jq '.traces[] | {timestamp, type, details}'

echo ""

echo "=== Examples Complete ==="
