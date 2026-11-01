# timeline-lanes — the office agent on כל מקביל

The producer half of the lane `apps/bina-ds/app.json` declares:

```
SPAN_SOURCE_BINA = http://bina-ds:3081/timeline/spans   →  lane `bina` on the office timeline
```

| File | What it owns |
|---|---|
| `lib/index.js` | The cordis plugin. Listens to the harness's `session/event` (plus `session/created`, `session/disposed`, `agent/error`), projects each event, appends the rows. Contained: nothing on the event path throws, awaits or blocks. |
| `lib/mapping.js` | Pure: one session event → span rows. Bracketed pairs (`turn/start→turn/end`, `step`, `tool/call→tool/result`, `command`, `compaction`, `approval`, `llm/retry`, `tool-workflow`) become real spans; every other event becomes an instant at its own timestamp, and an unknown type is still drawn under its raw name. |
| `lib/ledger.js` | The lane's store: one append-only JSONL file per UTC day on the volume, folded by span id, pruned by age. Also the reader the adapter serves (`hours` / `since`). |

Why a store of our own rather than reading the harness's canonical session log back: that log is
the harness's own file format (v3, zstd frames appended per flush), and a second reader of it would
be a second implementation of its versioning. The plugin already receives every event, with the
shape the harness declares — so the projection happens once, on the way in.

Where the numbers live: `$DSH_HOME/timeline/spans-YYYY-MM-DDTHH.jsonl` — **one file per UTC hour**,
14 days by default (a legacy day-wide `spans-YYYY-MM-DD.jsonl` is still read, never written). The
rotation is what keeps a read small: a dashboard's 15-minute window parses one hour-sized file, and
the 24 h seed parses 25 of them instead of one 20 MB day — measured on the live office, a window read
is 62 ms warm and a delta poll 8 ms, where the day-wide file cost tens of seconds cold and would have
blown through any-concurrency's `SPAN_SOURCE_TIMEOUT_S` (25 s). Reads are incremental on top of that:
only the bytes appended since the last read are parsed, so the 5 s delta poll never re-reads a file.

The lane serves history from there and the live tail arrives by the ordinary `SPAN_SOURCE_POLL_S`
(5 s) poll plus the timeline's own websocket delta — no second push path, so a span can never be
drawn twice.

Boundary, stated rather than hidden: delivery is best-effort like every telemetry seam — a hard
kill (`SIGKILL`, a crash) can lose the last few hundred milliseconds of rows, and a bracket left open
by it is served as `crashed` (ending at the last write) rather than as "running" for ever. The store
starts when the plugin first mounts; it does not replay sessions that ran before it.

Knobs: `BINA_TIMELINE_DIR`, `BINA_TIMELINE_KEEP_DAYS`, `BINA_TIMELINE_MAX_QUEUE`, and
`BINA_TIMELINE_DISABLED=1` to switch the whole lane off.
