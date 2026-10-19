---
date: 2026-08-04
status: canonical-design
tags: [browser42, groups, session, agents, architecture]
---

# Browser42 session groups — design

## What it solves

Browser42 is **one shared Chromium with one cookie jar and one `/view`**. Multiple coding agents
(Copilot, Claude Code, OpenHands) can browse simultaneously, but each must not mix up with another
agent's tabs.

A **session group** is one stable, named tab (tagged `b42g:<slug>`) that an agent owns for the
duration of a task. The slug is minted once per session and reused forever; the same slug always
finds the same tab. Simultaneous agents each get a different slug, so they never navigate each
other's pages.

## Session slug — the stable identity

An agent calls `bbox b42 session <name>` once. The name is deterministic (lowercased, non-alnum →
`-`). The slug is printed; the agent uses it verbatim in every later call. Same name → same slug →
same group, forever. The group's manifest is persisted at `data/browser42/groups/<slug>/group.json`
so it survives container restarts.

With no name, the CLI reuses the `.current` marker file — a convenience for a single agent. For
simultaneous agents, always pass an explicit name.

## Group get-or-use

`bbox b42 group [slug]` opens the group:

- Find the tab tagged `b42g:<slug>` in `contexts[0]` (the shared default context). Page 0 is
  the human `/view` anchor and is never touched.
- If found → reuse it.
- If not → create a new `about:blank` page, set `window.name = "b42g:<slug>"`.

The verb prints a ready-to-paste Python snippet bound to that tab. The agent pastes it into any
browser container `docker exec` session and works on `me` only.

When a URL is also passed (`bbox b42 group <slug> <url>`), the old broker-allocate path applies:
a native colored/labeled Chrome Tab Group is created through the extension, with ownership
generation and popup adoption. This is the "full" group path used by the task protocol.

## Tab ownership

All group tabs share `contexts[0]` — one cookie jar. The `b42g:` prefix on `window.name` is the
structural boundary between agents:

- The reaper **spares** every `b42g:*` and `b42:*` tab — only untagged junk is capped.
- `close <slug>` closes exactly that group's tabs (never page 0 or another group's).
- `gc [--stale N]` closes stale groups (last-seen older than N hours) — the automatic cleanup
  backstop for simultaneous browsing agents.

## CLI surface

| Verb | Purpose |
|---|---|
| `bbox b42 session [name]` | Resolve/mint the stable slug; write manifest; print it |
| `bbox b42 group [slug] [url]` | Get-or-use the group; print attach snippet. With URL: full native group allocation |
| `bbox b42 groups` | List every group (slug, created, last-seen, tabs) |
| `bbox b42 close <slug>` | Close exactly that group's tabs; remove its manifest |
| `bbox b42 gc [--stale H]` | Close + remove groups idle > H hours (default 24) |

Each verb is a file in `apps/browser42/hooks/` and one line of help in `app.json`.

## What it is NOT

- **Not a separate browser context.** All groups share `contexts[0]` — one cookie jar, one profile.
  The group is purely a tab-naming convention made mechanical by the CLI.
- **Not cookie isolation.** All agents share the same authenticated sessions (Google, etc.).
  If you need authenticated privacy, create a separate Chrome profile or use the MCP's incognito
  context.
- **Not a guarantee against a broken agent.** A malicious or buggy agent can still navigate any
  tab in the shared browser. The group mechanism makes correct behavior the easy default and the
  reaper/gc clean up the rest.

## What it builds on

The existing `group-manager.py` already has `session`, `open`, `list`, `close`, and `gc` commands,
all using the extension broker for native Chrome Tab Groups when a URL is provided. The lightweight
get-or-use path (no URL, shared context, `window.name` tagging) fills the gap for session-identity
tab ownership — the "which tab is mine?" question that makes simultaneous agents practical.
