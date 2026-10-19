# raphael — the guardian agent's automations

**What it is.** `apps/raphael` is an automation-only app (`kind: blueprint`, no container). It ships
the hard-coded n8n workflows that scan the running DGO on a schedule and, on an anomaly, post a
notice (source `raphael`) and open/append a Raphael agent session. **Raphael the agent** is a
separate thing: a preset in the bina-ds harness (`apps/bina-ds/harness/profile/agent-presets/raphael/`),
with his scan skills. This app is only his hands — the scheduled scans; the preset is his mind.

**Operate it.**
- `./bbox raphael start` — ensure Raphael's automations are present in the office's n8n (idempotent:
  pushes this app's blueprint). This is "Raphael start" from the owner's request — run it once and the
  scans run on their own thereafter.
- `./bbox raphael status` — what is present vs declared.
- The workflows live under `blueprint/n8n/*.workflow.ts`, tagged `app:raphael`, each a Schedule
  Trigger → probe an engine → verdict → (on anomaly) notify + trigger the agent. They import/remove
  with the app's enable/disable, like every blueprint app.

**Depends on n8n** (`use: workflow, requires`). Enabling raphael pulls n8n into the compiled office;
pushing its workflows needs n8n running and, on a fresh instance, the n8n owner sign-in (own-031).
It `wants: notify` so a finding reaches the notification centre.

**What it must not do.** The automations SCAN and REPORT; they never change the system. Any healing is
a suggestion Raphael (the agent) makes to the owner or to עזריה — see the preset's scan skills for the
engines each scan drives (machine, data-management, computers audit, the gate suite, sites-render).

Plane: o-raphael / req-001 (DGO-461); this app = rap-002 (DGO-486).

**rap-009 — the authorised self-pentest is ARMED (owner, 2026-10-09, «כן כן הכל מאושר»).** What is
armed: Raphael may measure how hard this office's OWN deployment is — and only the owner's own
offices, never anything outside them. The command is

```
python3 apps/bina-ds/harness/profile/agent-presets/raphael/skills/pentest/pentest.py --armed --root .
```

It reconnoitres and reports (published host ports and which container publishes them, the edge's TLS
and headers, who sees the docker socket, secrets that still carry the value the repo publishes, the
machine audit) with an evidence line per finding, and it REFUSES any target that is not this office or
a machine in the owner's `computers` fleet — a hostname or URL is not an argument it accepts, and a
neighbour office's project on the same engine is never measured. Deliberately NOT done: no
exploitation, no denial of service, no credential brute force or login attempt, no writes. The
scheduled clock is **`raphaelPentest00001`** (weekly) — it runs only the read-only `computers` audit
and notices (plus a `wake-` notice) only when that audit has an error/warn finding.
