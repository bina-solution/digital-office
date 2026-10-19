# Custom Sources

## Webhook API (simplest — any language)

`POST /ingest/span` accepts a single span or a JSON array of spans.

### Minimal span

```json
{"id": "job-1", "src": "my-app", "s": 1700000000000, "status": "running"}
```

### Full span

```json
{
  "id":     "job-1",
  "src":    "my-app",
  "svc":    "nightly-import",
  "svcid":  "customer-42",
  "label":  "Import customer 42",
  "status": "running",
  "s":      1700000000000,
  "e":      null,
  "meta":   {"rows": 5200, "region": "us-east-1"}
}
```

### Batch ingest

```json
[
  {"id": "span-1", "src": "batch", "svc": "step-1", "s": 1700000000000, "e": 1700000001500, "status": "success"},
  {"id": "span-2", "src": "batch", "svc": "step-2", "s": 1700000001500, "status": "running"}
]
```

### Close a running span

```
POST /ingest/span/{span_id}/close
Content-Type: application/json

{"status": "success", "meta": {"rows_processed": 5200}}
```

---

## LogSpan — log-marker format

If you control a container that is already being tailed for other reasons, you can embed span lifecycle markers directly in its log output.

Format: any log line that contains `WA_SPAN` followed by a JSON object.

### Open a span

```
WA_SPAN {"evt":"msg_start","id":"<unique-id>","ts":<unix-ms>,"from":"<identifier>","type":"<category>","fromMe":true}
```

### Close a span

```
WA_SPAN {"evt":"msg_end","id":"<unique-id>","ts":<unix-ms>,"dur":<duration-ms>,"ok":true}
```

### Error span

```
WA_SPAN {"evt":"msg_end","id":"<unique-id>","ts":<unix-ms>,"dur":<duration-ms>,"ok":false,"err":"timeout"}
```

### Example (Python)

```python
import json, time

def span_start(span_id: str, from_: str, type_: str = "task"):
    marker = json.dumps({"evt": "msg_start", "id": span_id,
                         "ts": int(time.time() * 1000),
                         "from": from_, "type": type_, "fromMe": True})
    print(f"WA_SPAN {marker}")

def span_end(span_id: str, dur_ms: int, ok: bool = True, err: str | None = None):
    marker = {"evt": "msg_end", "id": span_id,
              "ts": int(time.time() * 1000), "dur": dur_ms, "ok": ok}
    if err:
        marker["err"] = err
    print(f"WA_SPAN {json.dumps(marker)}")
```

Enable this source:
```env
LOGSPAN_CONTAINER=my-container-name
ENABLE_LOGSPAN=1
```

---

## Custom — gunicorn/uvicorn JSON access log

Point `CUSTOM_CONTAINER` at any container writing JSON access logs where each line has at minimum:

```json
{"method": "POST", "path": "/api/run", "status": 200, "duration_ms": 142}
```

Additional recognised fields: `request_id`, `service`, `remote_addr`, `user_agent`.

Enable this source:
```env
CUSTOM_CONTAINER=my-api-container
ENABLE_CUSTOM=1
```

---

## Span source — an endpoint the app serves

Some apps already **hold** their spans: a table with a start column and an end column, going back
days. Tailing a log cannot reach that history and the ring buffer cannot hold it, so for those the
app serves the projection and this service pulls it.

```env
SPAN_SOURCE_INDOX=http://incoming-documents:8080/incomingDocuments/timeline/spans
```

The lane name comes from the **variable name** (`SPAN_SOURCE_INDOX` → lane `indox`), so a URL
carrying a query string stays unambiguous. `SPAN_SOURCE_<APP>=<url>=<lane>` overrides it, and
`SPAN_SOURCES=url[=lane],…` is the operator escape hatch for an endpoint no app declares.

Your endpoint answers two questions, both returning the span schema above:

| request | meaning |
|---|---|
| `GET <url>?hours=<h>` | every span in that window — served straight through to `/api/spans` |
| `GET <url>?since=<ms>` | anything that **started or ended** after `<ms>` — the delta poll |

`since` is start-*or*-end, not start alone: a span that opened an hour ago and closes now must
reach the timeline when it closes, or it renders as running forever.

Return either a bare array or `{"spans": [...]}`. Rows are validated on arrival — a malformed row
costs that row and nothing else — and `src` is forced to the configured lane, so an endpoint
declared as one lane cannot publish into another.

**Why the app owns the projection:** the timeline knows how to draw a span; only the app knows
which of its own states mean "still moving" and which mean "at rest". Keeping that judgement on
the app's side is also what keeps the base service free of any app's schema.

**History lives in your store, not in the ring.** The ring is only the live tail — `/api/spans`
re-asks your endpoint for whatever window the caller wanted, exactly as the `n8n` source re-queries
Postgres. If your endpoint caps its answer, say so in the response: a silently truncated list reads
as "this is everything that happened."

Tuning: `SPAN_SOURCE_POLL_S` (5), `SPAN_SOURCE_TIMEOUT_S` (25), `SPAN_SOURCE_SEED_H` (24),
`SPAN_SOURCE_OVERLAP_S` (60), `SPAN_BUFFER_<LANE>` / `SPAN_BUFFER_DEFAULT` (20000).

---

## DIY source (Python)

To add a fully custom source loop inside `app.py`, follow this pattern:

```python
async def my_source_loop(store: RingStore, broadcast, health: dict) -> None:
    while True:
        try:
            # ... get data from wherever ...
            spans = [{"id": "...", "src": "my-source", "svc": "...",
                      "s": int(time.time() * 1000), "e": ...,
                      "status": "success", ...}]
            new = await store.upsert_many(spans)
            _mark_source(health, True, event=bool(new))
            if new:
                await broadcast({"type": "delta", "rows": new})
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _mark_source(health, False, repr(exc))
            await asyncio.sleep(15)
```

Then in `lifespan()`:
1. Add `app.state.my_store = RingStore(buffer_size)`
2. Add `app.state.source_health["my-source"] = _source_health(True)`
3. `tasks.append(asyncio.create_task(my_source_loop(...)))`
4. Include in `/api/spans` and `/api/span/{id}` lookups
