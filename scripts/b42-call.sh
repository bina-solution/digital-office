#!/usr/bin/env bash
# Minimal MCP streamable-HTTP client for driving browser42's Playwright MCP.
# Usage: SID=<session-id> ./scripts/b42-call.sh '<json-rpc-payload>'
# Reads BROWSER42_MCP_TOKEN from .env. Strips SSE framing, prints data line.
set -euo pipefail
REPO="$(cd -- "$(dirname -- "$0")/.." && pwd)"
TOKEN=$(grep -E '^BROWSER42_MCP_TOKEN=' "$REPO/.env" | head -1 | cut -d= -f2- | tr -d '\r"')
: "${SID:?set SID to the Mcp-Session-Id}"
curl -s \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SID" \
  -X POST "http://127.0.0.1:8931/mcp" \
  -d "$1" | sed -n 's/^data: //p'
