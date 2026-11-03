# Operating «כל מקביל» (the `any-concurrency` app)

The office's timeline of everything that ran at once: n8n executions, requests through the edge,
container starts and stops, and spans that other apps send or serve. Every lane is drawn as a Gantt.
Use it to answer "what was running when this got slow", "did that workflow overlap the other one",
and "is the queue backing up".

It only reads. Its sources are:

- n8n's Postgres (SELECT only), and Redis for the queue;
- the edge's log;
- docker events, and the log tails other apps declare (mail, drive, apitools);
- the span addresses other apps serve (`SPAN_SOURCE_*` in their app.json: indox, project-pln,
  bina-ds, security);
- spans posted to it.

Spans are kept in memory, not in a database.

## From inside the office network (`http://any-concurrency:8080`)

```bash
GET  /api/sources                          # each source: enabled, ok, last event
GET  /api/spans?hours=1&sources=n8n,traefik  # the spans of a window (0.01 h to 14 days)
GET  /api/span/<id>                        # one span
GET  /api/executions                       # n8n executions in the window
GET  /api/queue                            # the n8n queue now
GET  /api/n8n/exec/<id>                    # one n8n execution, as a span
POST /ingest/span | /ingest/spans          # add spans (≤ 1000 per call; 503 when the webhook source is off)
POST /ingest/span/<id>/close               # close an open span
WS   /ws                                   # the live feed the screen draws
```

From the shell: `./bbox any-concurrency sources|queue|executions [h]|spans [h] [sources]` read the same
API. `./bbox any-concurrency verify` fails when the container is down or an enabled source
is not answering. Log lines worth a read only make it warn (exit 0), so read its output, not only
the exit code. The screen is `/a/any-concurrency/`; the view it shows is written in the address.

## Rules

- Everything is safe to read. A posted span is seen by everyone who has the screen open, so post
  only real work, under your own source name.
- Nothing here stops, starts or deletes anything. To act on what you saw, go to the app that owns it
  (n8n, computers, app-management).

## Traps

- A restart empties the webhook, edge and docker lanes (memory only, 384M cap). An empty lane after
  a restart is not an idle office.
- A source counts as broken only when it is enabled, and the webhook source reads "ok" when its door
  is open, not when traffic arrived.
- `data.volumes` names `n8n_storage`, n8n's volume, mounted read-only here. Never uninstall this app
  with `purge`: the purge walks `data.volumes`, so it would delete n8n's data.

Gates: G27 (the shared screen blocks). G84 reads its compose file as it reads every app's; its
standalone harness and the two `examples/` compose files are on G84's not-run list.
