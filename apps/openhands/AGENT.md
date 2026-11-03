# Operating «סוכן קוד» (the `openhands` app)

OpenHands, an autonomous coding agent, with a dispatcher, an LLM gateway and its own runtime
containers. It is **retired in the herd** (`apps/computers/herd.yaml`: no office runs it), and it
ships off. It has no console tile.

## Rules

- **Do not enable, restart or call it.** It holds the engine's socket read-write, and its
  `docker-proxy` is an unauthenticated door to the engine, which together are root on the machine.
  `scripts/refactor/exposure-lint.py` records why this was accepted for a disabled gallery app.
- Its dispatcher (`dispatcher:8800`, `POST /dispatch`) wants a bearer token, but a header from the
  dashboard skips it. Never rely on that door.
- Its own `*.md` files (PRODUCT.md, current.md, next.md) describe the June 2026 deployment on the
  VPS. The compose names that machine's paths (`/var/run/docker.sock`, `/root/deployment-hacohen`).
  On another office it would reach the wrong engine.
- Coding work in this office goes through bina-ds (`bbox agent`), not here.

Gates: G23 (a gallery app ships disabled), G27. It also appears in G32's and G84's exemption lists,
which excuse it rather than check it.
