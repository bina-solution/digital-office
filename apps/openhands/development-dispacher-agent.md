# Development Dispatcher Agent — Architecture

> **A dispatcher agent + OpenHands fully declarative one-click setup, capable of managing issues / schedules / development sessions (searching / creating / provoking / monitoring / retrying / etc.)**

---

## 1. Header

| Field | Value |
|-------|-------|
| **Project Name** | `development-dispacher-agent` |
| **Repository** | `deployment-hacohen/openhands/` |
| **Branch** | `COPILOT` |
| **Deployment Domain** | `dispatch.hacohen.bina-solutions.co.il` |
| **OpenHands Domain** | `openhands.hacohen.bina-solutions.co.il` |
| **Setup Command** | `docker compose up -d openhands dispatcher` |
| **Net Lines of Config** | ~200 (compose) + ~3000 (dispatcher) + ~130 (init) |

---

## 2. Dispatcher Agent — Mindset & Capabilities

### System Prompt (Core Identity)
```
You are the Dispatcher Agent — an autonomous AI coordinator with
thinking, planning, and media analysis capabilities.
```

### Decision Flow
```
User Message → Intent Router
  ├── System Commands (/status, /help, /files, /issues, /sessions, /schedule)
  ├── Direct Answer (facts, math, casual chat, image description via Gemini vision)
  └── OpenHands Delegation (code, files, browse, deploy, complex tasks)
```

### Capabilities Matrix

| Capability | Handled By | Model Used |
|-----------|-----------|------------|
| Text Q&A | Dispatcher Direct | DeepSeek V4 Pro |
| Image Description | Dispatcher Vision | **Gemini 2.5 Flash** (auto-detected) |
| System Commands | Dispatcher Internal | No LLM |
| Issue Tracking | SQLite DB | REST API + Telegram |
| Scheduling | Cron-like timer | No LLM |
| Code/File Ops | OpenHands Agent | User-selectable (9 profiles) |
| Web Browsing | OpenHands Agent | User-selectable |
| Deployment Ops | OpenHands Agent | Auto-selects based on task |
| Media Analysis | OpenHands Agent | **Gemini 2.5 Flash** (for media tasks) |

### Message Protocol (2 messages max per turn)
```
Message 1 (editable): 🔧 Turn N · Model · ⏱ Xs
  ▸ Queue position / thinking / progress / tools count
Message 2 (final):     [answer text]
  🔗 View session: https://dispatch.../chat?uid=tg-{chatId}
```

### Session Features
- **Persistent sessions** across restarts (JSON file)
- **Queue system**: concurrent messages queued, processed FIFO
- **Retry**: `/retry` command re-sends last failed message
- **Scheduling**: `/schedule add "every 5 min" "task"`
- **Issue tracker**: SQLite DB with Telegram commands + Web UI
- **Obsidian Brain**: Vault integration for persistent AI memory
- **Session links**: Direct to dispatcher chat dashboard
- **VNC browser view**: Live agent browser at `/vnc`

### Model Auto-Discovery
```javascript
// Dispatcher reads models from OpenHands settings.json (shared volume)
// Zero hardcoded models — dynamically loads all profiles
loadOpenHandsProfiles(); // → MODEL_MAP, PROFILE_TO_LITELLM, AVAILABLE_MODELS

// Vision auto-selects Gemini when available
VISION_MODEL = GEMINI_API_KEY ? 'gemini-2.5-flash' : 'deepseek-chat';
```

---

## 3. OpenHandsConfig — Version-Controlled Declarative Setup

### File Inventory
```
openhands/
├── docker-compose.yml       # OpenHands + dispatcher + init + agent-proxy
├── generate-settings.sh     # Python script: API keys → profiles
├── agent-image/
│   ├── Dockerfile           # Custom agent image (entrypoint wrapper)
│   └── entrypoint-wrapper.sh # Key propagation, no hardcoded models
├── agent-proxy/
│   ├── Dockerfile           # WebSocket bridge for agent sandboxes
│   └── server.js
├── dispatcher/
│   ├── Dockerfile           # Node 22 Alpine
│   ├── server.js            # ~3000 lines dispatcher logic
│   └── lib/
│       ├── telegram.js      # Telegram API helpers
│       └── openhands.js     # OpenHands API client
└── docker-proxy/
    └── Dockerfile           # Docker TCP proxy
```

### Init Container (Declarative Model Generation)
```bash
# openhands-init reads .env API keys and auto-generates settings.json
# Change detection: hashes generate-settings.sh CONTENT + API keys
# Any change → regenerates on next docker compose up

docker compose up -d openhands  # init runs first, then openhands starts
```

### Model Profiles (Auto-Generated from .env)
```
.env → init → settings.json → OpenHands server → agent sandboxes
                                        ↓
                              dispatcher reads via shared volume
```

| Provider | Models Generated | Trigger |
|----------|-----------------|---------|
| DeepSeek | V4 Pro, V4 Flash, Reasoner | `DEEPSEEK_API_KEY` set |
| Gemini | 2.5 Flash, 2.5 Pro | `GEMINI_API_KEY` set |
| OpenAI | GPT-4o, GPT-4o Mini | `OPENAI_API_KEY` set AND ≠ DEEPSEEK key |
| Anthropic | Claude Sonnet 4, Haiku 4 | `ANTHROPIC_API_KEY` set |

### Agent Image (`openhands-agent-fixed`)
```
Base: ghcr.io/openhands/agent-server:1.27.0-python
Adds: entrypoint-wrapper.sh (key propagation + git safe.directory)
Env:  OPENAI_API_KEY, DEEPSEEK_API_KEY, GEMINI_API_KEY, OH_ENABLE_VNC
Note: No hardcoded models, no profile overwriters, no file patchers
```

### Web UI Access
```
openhands.hacohen.bina-solutions.co.il
  ├── /                          → Main dashboard
  ├── /conversations/{id}        → Conversation view
  ├── /settings                  → LLM profile settings
  └── Model selector dropdown    → All auto-discovered profiles
```

---

## 4. Deployment Context

### What This Tells Agents

The `ai/context/deployment-context.txt` file is injected into OpenHands agent tasks as system context when the task involves deployment operations. It provides:

| Section | What Agents Learn |
|---------|------------------|
| Service Map | 60+ services, their ports, URLs, resource limits |
| Compose Structure | 14 sub-compose files, Traefik v3.3 proxy |
| Domain Pattern | `<service>.hacohen.bina-solutions.co.il` |
| Network Architecture | `traefik-network` for all services |
| Deployment Instructions | How to add new services with Traefik labels |
| Database Info | PostgreSQL versions, connection strings |
| Auth Integration | Authentik ForwardAuth, protected vs own-auth services |
| Monitoring | GlitchTip DSNs, log collection |
| Maintenance | Scripts, backup locations, SSL certs |

### When Context Is Injected
```javascript
// server.js — dispatchForTelegram()
if (/deploy|clone|setup|create.*service|add.*docker|nginx/i.test(message)) {
  finalMessage += DEPLOYMENT_CONTEXT; // Full deployment instructions
}
```

### Key Deployment Rules (for agents)
1. Use HOST paths for volume mounts, not sandbox paths
2. `/workspace/project/` maps to `/root/deployment-hacohen/` on Docker host
3. Add new services to root `compose.yml` `include` directive
4. Traefik labels: `traefik.enable=true`, host rule, TLS
5. Restart from root: `cd /root/deployment-hacohen && docker compose up -d`

---

## 5. Orchestration — Minimal Required Files

### Core Files (must exist for system to work)
```
deployment-hacohen/
├── .env                              # API keys + config vars
├── compose.yml                       # Root compose (includes openhands/...)
├── compose.override.yaml             # Traefik labels per service
├── openhands/
│   ├── docker-compose.yml            # OpenHands + dispatcher + init + proxy
│   ├── generate-settings.sh          # Declarative profile generator
│   ├── agent-image/
│   │   ├── Dockerfile                # Custom agent image
│   │   └── entrypoint-wrapper.sh     # Agent startup
│   ├── agent-proxy/
│   │   ├── Dockerfile
│   │   └── server.js
│   ├── dispatcher/
│   │   ├── Dockerfile
│   │   ├── server.js                 # Main dispatcher logic
│   │   └── lib/
│   │       ├── telegram.js           # Telegram API
│   │       └── openhands.js          # OpenHands API client
│   └── docker-proxy/
│       └── Dockerfile
├── traefik/
│   ├── traefik-dynamic.yaml
│   └── acme.json                     # Auto-generated SSL certs
└── ai/context/
    └── deployment-context.txt        # Agent deployment instructions
```

### Volume Mounts
```
openhands_state:  /.openhands-state   → settings.json, dispatcher DBs
openhands_config: /.openhands         → settings.json seed
/var/run/docker.sock                  → Docker API access
/root/deployment-hacohen              → Workspace mount (full host access)
/root/deployment-hacohen/downloads    → Shared file transfer
/root/deployment-hacohen/ai/obsidian     → AI memory vault
```

### Startup Sequence
```
1. openhands-init   → Detects API keys → Generates settings.json
2. openhands        → Reads settings.json → Starts web UI + API
3. dispatcher       → Reads settings.json → Loads model profiles
                    → Sets Telegram webhook → Ready for messages
4. User sends msg   → dispatcher routes to direct answer or OpenHands
5. OpenHands agent  → Created on demand → Reads profiles from server
```

---

## 6. Dependencies

### External APIs (keys in .env)
```
DEEPSEEK_API_KEY         → api.deepseek.com         (required)
GEMINI_API_KEY           → generativelanguage.googleapis.com (optional, vision)
OPENAI_API_KEY           → api.openai.com           (optional)
ANTHROPIC_API_KEY        → api.anthropic.com        (optional)
TELEGRAM_BOT_TOKEN       → api.telegram.org         (required for TG bot)
```

### Docker Images
```
ghcr.io/openhands/openhands:1.8.0           → OpenHands server
ghcr.io/openhands/agent-server:1.27.0-python → Agent sandbox base
python:3-alpine                              → Init container
node:22-alpine                               → Dispatcher runtime
alpine:latest                                → Agent proxy
```

### Node.js Dependencies (dispatcher)
```
node:sqlite   → SQLite (session + issues DB)
node:http     → HTTP server
node:fs       → File system access
node:path     → Path utilities
node:crypto   → UUID generation
node:child_process → Docker CLI access
```

### Docker Networks
```
traefik-network    → All services communicate here
default            → docker-compose internal network
```

---

## 7. Self-Developed Parts

| Component | Lines | Language | Purpose |
|-----------|-------|----------|---------|
| `dispatcher/server.js` | ~2950 | Node.js (ESM) | Full dispatcher agent logic |
| `dispatcher/lib/telegram.js` | ~120 | Node.js | Telegram API helpers |
| `dispatcher/lib/openhands.js` | ~140 | Node.js | OpenHands API client |
| `generate-settings.sh` | ~130 | Python (in shell) | Declarative profile generator |
| `entrypoint-wrapper.sh` | ~30 | Bash | Agent key propagation |
| `agent-proxy/server.js` | ~80 | Node.js | WebSocket sandbox proxy |
| **Total** | **~3450** | | |

### Dispatcher Internal Modules (in server.js)
- **Session Manager**: Persistent sessions, history, auto-save
- **Schedule Engine**: Cron-like task scheduler with persistence
- **Issue Tracker**: SQLite DB + REST API + Telegram commands + Web UI
- **Obsidian Brain**: Vault read/write/search for AI memory
- **Dashboard**: Chat UI with SSE streaming, session sidebar
- **Image Proxy**: In-memory + disk cache for Telegram photos
- **Auto-Cleanup**: Dead agent container removal every 30min

---

## 8. Orchestration Integration — How Everything Connects

### Data Flow
```
┌─────────────────────────────────────────────────────────────┐
│                        .env                                 │
│  DEEPSEEK_API_KEY  GEMINI_API_KEY  TELEGRAM_BOT_TOKEN ...   │
└──────┬──────────────┬──────────────────┬────────────────────┘
       │              │                  │
       ▼              ▼                  ▼
┌──────────┐  ┌──────────────┐  ┌──────────────────┐
│ openhands│  │  dispatcher  │  │  Telegram API     │
│  -init   │  │  container   │  │  (webhook)        │
│          │  │              │  │                   │
│ generates│  │ reads        │  │ POST /telegram-   │
│ settings │  │ settings.json│  │ webhook           │
│ .json    │  │ from volume  │  │                   │
└────┬─────┘  └──────┬───────┘  └────────┬──────────┘
     │               │                   │
     ▼               ▼                   │
┌──────────┐  ┌──────────────┐           │
│openhands │  │ dispatcher   │◄──────────┘
│ server   │  │ routes msg   │
│          │  │              │
│ reads    │  │ direct?      │
│ settings │  │   → LLM call │
│ .json    │  │   → respond  │
│          │  │              │
│ provides │  │ delegate?    │
│ profiles │──▶ → OpenHands  │
│ to agents│  │   API call   │
└────┬─────┘  │   → monitor  │
     │        │   → respond  │
     ▼        └──────────────┘
┌──────────┐
│ agent    │
│ sandbox  │
│          │
│ reads    │
│ profile  │
│ from     │
│ server   │
│          │
│ executes │
│ task     │
└──────────┘
```

### Volume Sharing
```
openhands_state (Docker volume)
  ├── /.openhands-state/settings.json     ← init writes, openhands reads, dispatcher reads
  ├── /.openhands-state/dispatcher-issues.db  ← dispatcher writes
  ├── /.openhands-state/dispatcher-sessions.json ← dispatcher writes
  ├── /.openhands-state/openhands.db      ← openhands writes, dispatcher reads
  └── /.openhands-state/v1_conversations/ ← agent events, dispatcher polls
```

### Network Flow
```
Internet
  │
  ▼
Traefik (443)
  ├── openhands.hacohen... → openhands:3000 (Web UI + API)
  └── dispatch.hacohen...  → dispatcher:8800 (Chat UI + Telegram webhook)
                                │
                                ├── Direct LLM call (DeepSeek API)
                                ├── Vision LLM call (Gemini API)
                                └── OpenHands API → agent sandbox
```

### One-Command Setup
```bash
# 1. Clone repo
git clone https://github.com/solomonBoltin/deployment-hacohen
cd deployment-hacohen

# 2. Configure .env (add API keys)
cp .env.ex .env
# Edit .env: add DEEPSEEK_API_KEY, TELEGRAM_BOT_TOKEN, optionally GEMINI_API_KEY

# 3. Start
docker compose up -d openhands dispatcher

# 4. Done — dispatcher auto-discovers models, sets webhook, ready for messages
```

---

## Appendix: Issue Tracker Schema

```sql
CREATE TABLE issues (
  id TEXT PRIMARY KEY,
  number INTEGER UNIQUE NOT NULL,
  title TEXT NOT NULL,
  description TEXT DEFAULT '',
  status TEXT DEFAULT 'open',
  priority TEXT DEFAULT 'medium',
  labels TEXT DEFAULT '[]',
  reporter TEXT DEFAULT '',
  image_urls TEXT DEFAULT '[]',
  conversation_id TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE comments (
  id TEXT PRIMARY KEY,
  issue_id TEXT NOT NULL,
  author TEXT DEFAULT '',
  body TEXT NOT NULL,
  image_urls TEXT DEFAULT '[]',
  created_at TEXT NOT NULL
);
```

## Appendix: Session Schema
```javascript
sessions = Map<userId, {
  model: string,           // OpenHands profile name
  turnCount: number,       // Total conversation turns
  ohConvId: string|null,   // Current OpenHands conversation ID
  lastActiveAt: timestamp,
  history: message[],      // Last 20 messages
  processing: boolean,     // Lock for queue
  queue: message[],        // Queued messages
  lastFailedMessage: string // For /retry
}>
```
