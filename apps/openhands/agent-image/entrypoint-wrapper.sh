#!/bin/bash
# ── Declarative agent entrypoint ──
# Propagates API keys. No hardcoded models, no profile overwriters.
# All model config comes from OpenHands server (settings.json → profiles).

export OPENAI_API_KEY="${OPENAI_API_KEY:-$LLM_API_KEY}"
export DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-$LLM_API_KEY}"
export GEMINI_API_KEY="${GEMINI_API_KEY:-}"
export LITELLM_PROXY_API_KEY="${LITELLM_PROXY_API_KEY:-$LLM_API_KEY}"
echo "[agent] Keys ready: DS=${DEEPSEEK_API_KEY:0:8}... OAI=${OPENAI_API_KEY:0:8}... GEM=${GEMINI_API_KEY:0:8}..."

export DOCKER_HOST="${DOCKER_HOST:-tcp://host.docker.internal:2375}"
echo "[agent] DOCKER_HOST=$DOCKER_HOST"

git config --global --add safe.directory /workspace/project 2>/dev/null || true
git config --global --add safe.directory /root/deployment-hacohen 2>/dev/null || true
git config --global --add safe.directory /workspace 2>/dev/null || true
echo "[agent] Workspace: $(ls /workspace/ 2>/dev/null | head -3 | tr '\n' ' ')"

exec /usr/bin/tini -- /usr/local/bin/openhands-agent-server "$@"
