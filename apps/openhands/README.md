# OpenHands — AI Coding Platform

Self-hosted [OpenHands](https://github.com/All-Hands-AI/OpenHands) (v1.8.0)
for the deployment-hacohen stack. MIT-licensed, 76K+ GitHub stars.

## Architecture

```
Traefik (443) → openhands-bina-deployment (3000)
                  ├── FastAPI backend (REST + WebSocket)
                  ├── React SPA frontend
                  └── Agent SDK (spawns sandbox containers)

Dispatcher → agent-runner (7700) → DeepSeek V4 Pro / Claude
```

## Services

| Service | Port | Container |
|---------|------|-----------|
| openhands | 3000 (internal) | ghcr.io/openhands/openhands:1.8.0 |
| dispatcher | 8800 (internal) | custom Node.js bridge |

## URLs

- **Web UI**: https://openhands.hacohen.bina-solutions.co.il
- **Dispatcher health**: http://dispatcher:8800/healthz (internal only)

## Configuration

```env
# .env
OPENHANDS_BASE_URL=openhands.hacohen.bina-solutions.co.il
OPENHANDS_JWT_SECRET=<secret>
DISPATCHER_TOKEN=<token>
```

Uses the shared `DEEPSEEK_API_KEY` and `DEEPSEEK_BASE_URL` from root `.env`.

## Known Limitations

1. **WSS behind Traefik**: The self-hosted OpenHands image spawns agent-server
   containers on dynamic ports (e.g., 37263). The SPA tries to connect WebSocket
   directly to these ports, which aren't routed through Traefik. The web UI
   loads but agent conversations fail with `ERR_SSL_PROTOCOL_ERROR`.

   **Workaround**: Use the Dispatcher service (WhatsApp menu 22) or agent-runner
   for actual agent tasks.

2. **REST API**: When `SERVE_FRONTEND=true` (default), the SPA catch-all at `/`
   intercepts API routes. When `SERVE_FRONTEND=false`, API routes return 404.

## Dispatcher Integration

The dispatcher bridges WhatsApp → agent-runner with full read-write access:

```
WhatsApp (menu 22) → chat → dispatcher:8800 → agent-runner:7700 /dev-turn
```

Supports: deepseek-chat, deepseek-v4-pro, deepseek-reasoner, haiku, sonnet, opus,
claude-haiku-4-6, claude-sonnet-4-6, claude-opus-4-6.

## Deploy

```bash
cd /root/deployment-hacohen
docker compose up -d --build openhands dispatcher
```
