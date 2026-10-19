/**
 * timeline-lanes — the office agent on the office timeline (כל מקביל / any-concurrency).
 *
 * The gap this closes: every other app in the office is visible on the concurrency timeline — n8n's
 * executions, drive's and mail's requests, the browser's tasks, INDOX's documents — and the agent,
 * which is the thing doing most of the work, was a blank row. This plugin is the producer side of
 * the lane `apps/bina-ds/app.json` declares (`SPAN_SOURCE_BINA` → `http://bina-ds:3081/timeline/
 * spans`): it listens to the harness's own session-event firehose, projects each event into a span
 * (mapping.js) and appends it to the lane's store (ledger.js), which the adapter serves.
 *
 * The source is the DSH session API itself, in-process: `session/event` is the post-commit,
 * fire-and-forget feed of the canonical log — it hands us exactly what was just recorded, at the
 * instant it is recorded, with no file read, no API round trip and no lock. Nothing here ever opens
 * a `session*.jsonl(.zstd)`: the canonical log's format is the harness's own business, and a second
 * reader of it would be a second implementation of its versioning.
 *
 * Why not mount a `sessionTelemetry` backend (the harness's reporting seam)? Two reasons, both
 * deliberate. (1) That service is EXCLUSIVE — one backend per context — and a lane that occupies it
 * would block a deployment that later wants the OTel exporter. (2) The seam's records are already a
 * reporting abstraction (channel/severity/attributes/body); this lane wants the session events
 * themselves, which is what the seam taps anyway. So we listen to the same feed one layer lower,
 * and take the seam's two useful properties by hand: adoption of already-live sessions (below) and
 * containment (every handler is wrapped, nothing on the event path awaits or throws).
 *
 * Nor is the projection pulled from the HTTP API (`bbox agent` / the adapter): `session/list` and
 * `session/page` serialize on the harness's own loop, and under load they stop answering (measured
 * 2026-09-30: `GET /v1/health` -> no answer within 240 s while five sessions were working). A lane
 * that polls that, on a timer, in the middle of an outage, is a lane that adds load to the reason
 * the timeline is interesting.
 *
 * Containment is the rule, not a nicety: a listener that throws on `session/event` is a listener
 * that can disturb the agent loop, and one that blocks is a listener that slows every turn. So
 * every handler here is wrapped, nothing is awaited on the event path, and the only thing that
 * touches the disk is a queue drained in the background. If the ledger is unusable, the agent keeps
 * working and the timeline loses bars — never the other way round.
 *
 * Disable with `BINA_TIMELINE_DISABLED=1`. Tuning: `BINA_TIMELINE_DIR` (default `$DSH_HOME/timeline`),
 * `BINA_TIMELINE_KEEP_DAYS` (14), `BINA_TIMELINE_MAX_QUEUE` (5000).
 */
import { Ledger, ledgerDir } from './ledger.js'
import { closeAll, createTrack, project, sessionInfo } from './mapping.js'

export const name = '@bina/dsh-timeline-lanes'
/** The session store is how a hot reload finds the sessions that are already live. */
export const inject = ['sessions']

const OFF = new Set(['0', 'false', 'False', 'no', 'off'])
const int = (raw, fallback) => {
  const n = Number.parseInt(String(raw ?? ''), 10)
  return Number.isFinite(n) ? n : fallback
}

export function apply(ctx, config = {}) {
  if (OFF.has(String(process.env.BINA_TIMELINE_DISABLED ?? '').trim())) {
    note(ctx, 'disabled by BINA_TIMELINE_DISABLED — no lane, no store')
    return
  }

  const dir = config.dir || ledgerDir()
  const ledger = new Ledger({
    dir,
    keepDays: int(config.keepDays ?? process.env.BINA_TIMELINE_KEEP_DAYS, 14),
    maxQueue: int(config.maxQueue ?? process.env.BINA_TIMELINE_MAX_QUEUE, 5000),
    onError: (line) => note(ctx, line),
  })
  /** `BINA_TIMELINE_VERBOSE=1` draws the named plumbing events too (see mapping.js). */
  const verboseEnv = ['1', 'true', 'yes', 'on'].includes(String(process.env.BINA_TIMELINE_VERBOSE ?? '').trim().toLowerCase())
  /** One track per session id: the open brackets and the current turn. */
  const tracks = new Map()
  let seen = 0
  let rows = 0
  let failures = 0

  const warnings = new Map()
  /** Report each distinct failure once — a broken ledger must not flood the log every event. */
  const warn = (line) => {
    const n = (warnings.get(line) || 0) + 1
    warnings.set(line, n)
    if (n <= 2) note(ctx, n === 1 ? line : `${line} (again)`)
  }

  const trackFor = (session) => {
    const id = String(session?.id ?? '')
    if (!id) return undefined
    let track = tracks.get(id)
    if (!track) {
      track = createTrack(sessionInfo(session), { verbose: verboseEnv })
      tracks.set(id, track)
      seen += 1
      note(ctx, `watching session ${track.info.short}${track.info.parent ? ` (subagent of ${track.info.parent.slice(0, 15)})` : ''}`)
    }
    return track
  }

  const emit = (track, list) => {
    if (!track || list.length === 0) return
    rows += list.length
    ledger.write(list)
  }

  /** How many in-memory events of an already-live session are replayed at mount. A session that
   *  has run for days owns tens of thousands; the brackets we need are in its last few hundred. */
  const REPLAY_MAX = 2000
  const replayLive = (track, session) => {
    try {
      if (typeof session?.snapshotEvents !== 'function') return []
      const from = Number(session.firstLiveSeq ?? 0) || 0
      const events = session.snapshotEvents(from) || []
      const tail = events.length > REPLAY_MAX ? events.slice(-REPLAY_MAX) : events
      const out = []
      for (const event of tail) out.push(...project(track, event))
      return out
    } catch (error) {
      warn(`timeline-lanes: replay of ${track?.info?.short} failed: ${error?.message ?? error}`)
      return []
    }
  }

  /** Every handler runs through here: an exception costs the log line, never the session. */
  const guard = (what, fn) => (...args) => {
    try {
      fn(...args)
    } catch (error) {
      failures += 1
      warn(`timeline-lanes: ${what} failed (${failures} total): ${error?.message ?? error}`)
    }
  }

  void ledger.start().then(() => {
    note(ctx, `ledger at ${dir} (keep ${ledger.keepDays}d)`)
  })

  ctx.effect(() => {
    ctx.on('session/created', guard('session/created', (session) => {
      trackFor(session)
    }))

    // The firehose. Post-commit, synchronous, and the only path that produces spans.
    ctx.on('session/event', guard('session/event', (session, event) => {
      const track = trackFor(session)
      if (!track) return
      emit(track, project(track, event))
    }))

    ctx.on('session/disposed', guard('session/disposed', (session) => {
      const id = String(session?.id ?? '')
      const track = tracks.get(id)
      if (!track) return
      emit(track, closeAll(track, Date.now(), 'canceled'))
      tracks.delete(id)
      note(ctx, `session ${track.info.short} closed`)
    }))

    // The agent-error bus: the one failure that never reaches the session log (the loop reports it
    // live instead), and exactly the event a person opens the timeline to find.
    ctx.on('agent/error', guard('agent/error', ({ agent, turn, step, error }) => {
      const session = agent?.session
      const track = session ? trackFor(session) : undefined
      if (!track) return
      const detail = error instanceof Error ? error : new Error(String(error))
      emit(track, [{
        id: `${track.info.id}:error:${turn ?? 0}.${step ?? 0}:${Date.now()}`,
        svc: track.info.row,
        svcid: track.info.id,
        label: `שגיאת סוכן · ${detail.name}: ${String(detail.message).slice(0, 60)}`,
        status: 'error',
        s: Date.now(),
        e: Date.now(),
        meta: { ev: 'agent/error', turn, step, agent: agent?.id, session: track.info.id },
      }])
    }))

    // A hot reload replays no `session/created` (and neither does a plugin that mounts while the
    // office is mid-conversation): adopt whatever is live right now — and take the CURRENT
    // lifecycle of each, so the turn in flight is drawn from its own `turn/start` rather than
    // appearing as a close with no beginning. Bounded on purpose: this reads the live session
    // object the harness already holds in memory (no file, no API call), starts at `firstLiveSeq`
    // instead of at the restored seed, and keeps only the tail of a very long session — the
    // projection needs the open brackets, not a history replay.
    try {
      for (const session of ctx.sessions?.list?.() ?? []) {
        const track = trackFor(session)
        if (track) emit(track, replayLive(track, session))
      }
    } catch (error) {
      warn(`timeline-lanes: session sweep failed: ${error?.message ?? error}`)
    }

    return () => {
      // Disposal is orderly: close what is open, then make sure it reached the disk.
      for (const track of tracks.values()) emit(track, closeAll(track, Date.now(), 'canceled'))
      tracks.clear()
      void ledger.flush()
      note(ctx, `stopped after ${rows} span row(s) from ${seen} session(s), ${ledger.status().written} append(s)`)
    }
  }, 'timeline-lanes.capture()')
}

/** One line per real event, never per span: this runs inside the agent's own process. */
function note(ctx, line) {
  try {
    if (ctx?.logger?.info) ctx.logger.info(`timeline-lanes: ${line}`)
    else process.stderr.write(`timeline-lanes: ${line}\n`)
  } catch {
    // a logger that throws is not worth a session
  }
}
