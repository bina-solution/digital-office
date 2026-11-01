# Contributing to any-concurrency

Thank you for your interest in contributing! This document covers dev setup, testing, and the PR process.

---

## Dev Setup

### Prerequisites

- Docker + Docker Compose
- Python 3.11+ (for running the backend locally without Docker)

### Run locally (Docker — recommended)

```bash
cd any-concurrency

# Build and run
docker compose -f docker-compose.standalone.yml up --build

# Tail logs
docker compose -f docker-compose.standalone.yml logs -f

# Rebuild after code changes
docker compose -f docker-compose.standalone.yml up --build -d
```

The UI is served at `http://localhost:8080`.

### Run locally (Python venv)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Requires Docker socket access
uvicorn app:app --reload --port 8000
```

---

## Project Structure

```
any-concurrency/
├── app.py                     # FastAPI backend — sources, API, WebSocket hub
├── static/
│   └── index.html             # Single-file frontend (pure canvas, no framework)
├── requirements.txt
├── Dockerfile
├── docker-compose.standalone.yml   # Standalone (no external dependencies)
├── docker-compose.yml              # Production deployment (with Traefik labels)
├── .env.example               # All env vars documented
├── README.md
├── CONTRIBUTING.md            # This file
├── LICENSE
├── docs/
│   ├── architecture.md
│   ├── configuration.md
│   └── custom-sources.md
└── examples/
    ├── docker-compose.n8n.yml
    ├── docker-compose.traefik.yml
    ├── python-webhook.py
    └── node-webhook.js
```

---

## Making Changes

### Backend (`app.py`)

- Add new sources by following the pattern of `traefik_log_loop` / `logspan_log_loop`.
- All loops must call `_mark_source(health, ok, error_msg)` on every state change.
- Register new stores in `lifespan()` and add them to `/api/spans` and `/api/span/{id}`.
- New sources need a matching entry in `/api/sources` and `/healthz`.

### Frontend (`static/index.html`)

- Add new source colors in `SRC_COLORS` and icons in `SRC_ICONS`.
- For unknown/dynamic sources the `_srcColor(src)` helper auto-generates a consistent hue.
- The URL hash encodes all filter and view state — keep the compact encoding scheme.
- No build step needed — the file is served as-is.

### Adding a new env var

1. Add to `app.py` config section (top of file).
2. Add to `.env.example` with a descriptive comment.
3. Add to the configuration table in `README.md`.
4. Add to `docker-compose.standalone.yml`.

---

## Testing

There is currently no automated test suite. Manual testing procedure:

```bash
# 1. Start the stack
docker compose -f docker-compose.standalone.yml up --build -d

# 2. Check health
curl http://localhost:8080/healthz | python3 -m json.tool

# 3. Check sources
curl http://localhost:8080/api/sources | python3 -m json.tool

# 4. Ingest a test span
curl -s -X POST http://localhost:8080/ingest/span \
  -H "Content-Type: application/json" \
  -d "{\"id\":\"test-$(date +%s)\",\"src\":\"test\",\"svc\":\"ci\",\"label\":\"test span\",\"s\":$(date +%s000),\"status\":\"running\"}"

# 5. Open http://localhost:8080 — the test span should appear
```

---

## Pull Request Process

1. Fork the repo and create a branch: `git checkout -b feat/your-feature`
2. Make your changes (keep commits focused — one feature per PR)
3. Verify the stack builds and the UI works manually
4. Open a PR with a clear description of what changed and why
5. Reference any related issues

### Commit style

```
feat: add prometheus metrics endpoint
fix: traefik auto-discovery missing name lstrip
docs: update configuration table
chore: bump fastapi to 0.116
```

---

## Reporting Bugs

Open a GitHub issue with:

- What you expected
- What actually happened
- Docker/Python version
- Relevant log output (`docker logs any-concurrency 2>&1 | tail -50`)

---

## Code Style

- Python: follow existing style (no opinionated formatter enforced)
- JavaScript: vanilla ES2022, no transpilation, no framework
- Keep the frontend self-contained in a single HTML file
