# Bina's clock (n8n)

The office's automation for **בינה** lives here, as declared workflows — not as a loop in the container.
The owner, 2026-10-14: «use n8n automation blueprinted inside bina-ds app. And remove pulse and all of
this mod bullshit, keep clean and official like dsreleased». So `apps/bina-ds/pulse.sh` — a shell loop
that slept, woke conversations and re-armed goals inside the container — is **deleted**, and what it did
is either the harness's own job or a workflow in this folder.

| workflow | fires | does |
|---|---|---|
| `binaSeder00001` | 07:00 · 13:00 · 21:00 (Asia/Jerusalem) | `POST http://bina-ds:3081/v1/seder/<cycle>` — opens the day's cycle |

## The door a workflow may call

`POST /v1/seder/<cycle>` where `<cycle>` is `shacharit`, `mincha` or `arvit`. It is served by the app's
own adapter (`apps/bina-ds/adapter/server.mjs`) and it is **one verb wide on purpose**:

- it opens a new session, names it `סדר <name> · <date> · <time>` and hands it the `seder` brief;
- it refuses a second start of the same cycle on the same day (`{started:false, reason}`), so two
  triggers, a retry, or a second clock somebody adds later cannot run a cycle twice;
- it posts a notice with the conversation's link, and answers `{started:true, session, link}`.

It is **outside the Bearer-token gate** because the clock holds no credential — and the agent's token
can do far more than start a cycle (list, read and drive every conversation), which is why it is not
handed to n8n. Everything else at `bina-ds:3081` still answers 401 without it.

## Importing

```
./bbox n8n code validate          # the workflows compile
./bbox n8n push bina-ds           # import into the office's n8n (restarts n8n — the owner's yes)
```

Tags: `app:bina`, `role:infra`. Errors go to the shared `errorHandler01` workflow, like Raphael's scans.
