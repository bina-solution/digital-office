# Operating «התראות» (the `notifications` app)

The office's notice board: errors and events from any app, kept in one list, and rung on the
owner's phone when they matter. Other apps post here: security, autoheal, the browser's stalled
tasks, meet's watch. It polls GlitchTip's unresolved issues every minute, and a notice turns read
when its issue resolves.

## From inside the office network (`http://notifications:8977`)

```bash
GET    /api/notifications?unread=1&source=&level=&limit=50   # the list (limit ≤ 500)
GET    /api/notifications/<id>                               # one notice
GET    /api/notifications/unread-count | /stats
POST   /api/notifications   {"source": "…", "title": "…", "source_id": "…", "body": "…",
                             "level": "info|warning|error", "link": "…", "meta": {"to": "…"}}
POST   /api/notifications/<id>/read · /read-all
DELETE /api/notifications/<id>          ·   POST /api/notifications/clear-read
```

The same `source` + `source_id` updates one notice instead of adding another: give a recurring
problem a stable `source_id`. From the shell: `./bbox notifications list|show <id>|unread|stats`
(reads), and `./bbox notifications verify` (healthy: the database, the GlitchTip poller and its token). The screen is `/a/alerts/`, and a phone subscribes to push from
it.

## Rules

- **A notice at level `error` rings every subscribed device of every person in the office**
  (`PUSH_LEVELS`, default `error`). With `meta.to` it rings only the people named. Post `error` only
  when someone must act now. `info` and `warning` stay on the board.
- Ringing is guarded: a recurring notice rings again at most every 240 minutes, and past 30 in an
  hour one summary replaces the rest. Don't rely on the guard; post less.
- `POST /api/push/test` pushes to the caller's own phones, and only on request. The `/api/push/*`
  routes need the edge's sign-in header (`X-authentik-username`); without it they answer 401.
- Mark read what you handled. **Delete and `clear-read` remove notices for good**, so leave that to
  the owner.

## Traps

- `/healthz` is 503 when GlitchTip answers but `GLITCHTIP_API_TOKEN` is empty, and 200 "idle" when
  GlitchTip is not there at all.
- A deleted notice of an unresolved GlitchTip issue comes back on the next poll: resolve the issue.
- The push key (`/data/vapid.pem`) is made once. A new key silences every subscribed phone until
  each subscribes again.

Gates: G27 (the shared screen blocks); its own tests (`test_push.py`).
