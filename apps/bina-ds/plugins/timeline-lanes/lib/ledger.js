/**
 * ledger.js — the agent's own span store: one append-only JSONL file per UTC day.
 *
 * One file per UTC hour (the reader also takes the legacy day files), so a window read is small.
 *
 * Why a store of our own instead of reading the harness's session log back: the canonical log is
 * the harness's file format (v3, zstd frames appended one per flush), and a second reader of it is
 * a second implementation of its versioning. The plugin already receives every event — with the
 * shape the harness declares — so the projection is derived once, on the way in, and the store this
 * endpoint reads is ours.
 *
 * Shape of a line: one span object, exactly the schema any-concurrency's span endpoint accepts
 * (`id · svc · svcid · label · status · s · e · meta`), WITHOUT `src` — the lane forces its own
 * name on every row it serves, and an id it has not seen. A span is written when it opens, when it
 * is amended (a turn learns its prompt a beat after it starts) and when it closes: `read()` folds
 * by id, last line wins, so the file is a log of states rather than of deltas and a crash between
 * two lines costs accuracy about one span, never the file.
 *
 * The reader answers the two questions `SPAN_SOURCE_<APP>` is contracted for (docs/custom-sources.md):
 * `hours` for a window and `since` for a delta. Its spans are held in a small cache keyed by
 * (path, size, mtime) so a dashboard polling every 15 s re-parses nothing.
 */
import { appendFile, mkdir, readdir, stat, unlink } from 'node:fs/promises'
import { createReadStream } from 'node:fs'
import { join } from 'node:path'

// One file per UTC HOUR — `spans-2026-09-30T16.jsonl` — read alongside the legacy day files
// (`spans-2026-09-30.jsonl`) a previous version wrote, which are simply never written again.
// The rotation is what keeps a WINDOW read cheap: a dashboard asking for 15 minutes parses one
// hour-sized file (a few hundred spans) instead of one 20 MB day, and the 24 h seed parses 25 of
// them rather than blowing through any-concurrency's `SPAN_SOURCE_TIMEOUT_S` (25 s) on a cold cache.
const FILE_RE = /^spans-(\d{4}-\d{2}-\d{2})(?:T(\d{2}))?\.jsonl$/
const HOUR_MS = 3600 * 1000
const DAY_MS = 24 * HOUR_MS

/** The ledger's directory: `BINA_TIMELINE_DIR`, else `$DSH_HOME/timeline`. */
export function ledgerDir(env = process.env) {
  const explicit = (env.BINA_TIMELINE_DIR || '').trim()
  if (explicit) return explicit.replace(/\/+$/, '')
  return `${(env.DSH_HOME || '/data/dsh').replace(/\/+$/, '')}/timeline`
}

/** `spans-2026-09-30T16.jsonl` for the UTC hour `ms` falls in. */
export const fileNameFor = (ms) => `spans-${new Date(ms).toISOString().slice(0, 13)}.jsonl`

/**
 * The `[start, end)` a file covers, from its name: an hour file covers its hour, a legacy day file
 * its day. `null` for anything else in the directory (the reader ignores what it did not write).
 */
function dayBounds(name) {
  const m = FILE_RE.exec(name)
  if (!m) return null
  const hour = m[2]
  const start = Date.parse(`${m[1]}T${hour ?? '00'}:00:00.000Z`)
  if (!Number.isFinite(start)) return null
  return { name, date: m[1], hour: hour ?? null, start, end: start + (hour ? HOUR_MS : DAY_MS) }
}

// ── the writer ───────────────────────────────────────────────────────────────────────────────
/**
 * Append-only writer with an asynchronous drain.
 *
 * The session-event path must not touch the disk synchronously: a listener that blocks is a
 * listener that slows every turn (the same reason `dsh-session-telemetry` hands records off
 * without awaiting). So `write()` only enqueues, and one drain task appends whatever accumulated
 * in the meantime. Bounded on purpose: if the disk is gone the queue is dropped rather than grown
 * until the harness dies with it, and the dropped count is reported through `onError`.
 */
export class Ledger {
  constructor({ dir, keepDays = 14, maxQueue = 5000, onError } = {}) {
    this.dir = dir || ledgerDir()
    this.keepDays = Math.max(1, keepDays)
    this.maxQueue = Math.max(100, maxQueue)
    this.onError = onError || (() => {})
    this.queue = []
    this.draining = null
    this.dropped = 0
    this.written = 0
    this.started = false
  }

  /** Create the directory, prune old files. Never throws — a broken ledger must not stop a session. */
  async start() {
    try {
      await mkdir(this.dir, { recursive: true })
      this.started = true
      await this.prune()
    } catch (error) {
      this.onError(`ledger unavailable (${this.dir}): ${error?.message ?? error}`)
    }
    return this
  }

  /** Delete day files older than the retention window. */
  async prune(now = Date.now()) {
    const cut = now - this.keepDays * DAY_MS
    let names
    try {
      names = await readdir(this.dir)
    } catch {
      return 0
    }
    let removed = 0
    for (const name of names) {
      const day = dayBounds(name)
      if (!day || day.end >= cut) continue
      try {
        await unlink(join(this.dir, day.name))
        removed += 1
      } catch (error) {
        this.onError(`cannot prune ${day.name}: ${error?.message ?? error}`)
      }
    }
    return removed
  }

  /** Enqueue span rows for the day `at` falls in. Synchronous and allocation-light by design. */
  write(rows, at = Date.now()) {
    if (!rows || rows.length === 0) return
    const name = fileNameFor(at)
    for (const row of rows) {
      if (!row || !row.id) continue
      this.queue.push({ name, line: `${JSON.stringify({ ...row, w: at })}\n` })
    }
    if (this.queue.length > this.maxQueue) {
      const over = this.queue.length - this.maxQueue
      this.queue.splice(0, over)
      this.dropped += over
      this.onError(`ledger queue over ${this.maxQueue}; dropped ${over} line(s) (total ${this.dropped})`)
    }
    void this.#drain()
  }

  async #drain() {
    if (this.draining) return this.draining
    this.draining = (async () => {
      while (this.queue.length) {
        const batch = this.queue.splice(0, this.queue.length)
        const byFile = new Map()
        for (const item of batch) byFile.set(item.name, (byFile.get(item.name) || '') + item.line)
        for (const [name, text] of byFile) {
          try {
            await appendFile(join(this.dir, name), text, 'utf8')
            this.written += 1
          } catch (error) {
            this.dropped += text.split('\n').length - 1
            this.onError(`ledger append failed (${name}): ${error?.message ?? error}`)
          }
        }
      }
    })().finally(() => {
      this.draining = null
      if (this.queue.length) void this.#drain()
    })
    return this.draining
  }

  /** Wait for what is queued to reach the disk (used at dispose, and by tests). */
  async flush() {
    while (this.queue.length || this.draining) await this.#drain()
  }

  status() {
    return {
      dir: this.dir,
      available: this.started,
      written: this.written,
      dropped: this.dropped,
      queued: this.queue.length,
    }
  }
}

/**
 * What the store looks like right now, without parsing it: how many day files, how far back they
 * reach, and their total size. Cheap enough for a health probe, which is the only caller.
 */
export async function ledgerStatus(dir) {
  const root = dir || ledgerDir()
  let names = []
  try {
    names = await readdir(root)
  } catch (error) {
    return { dir: root, available: false, reason: error?.code ?? 'unreadable' }
  }
  const days = names.map(dayBounds).filter(Boolean).sort((a, b) => a.start - b.start)
  let bytes = 0
  for (const day of days) {
    try {
      bytes += (await stat(join(root, day.name))).size
    } catch {
      // vanished between readdir and stat — it was pruned; not a problem worth reporting
    }
  }
  return {
    dir: root,
    available: true,
    days: days.length,
    oldest_day: days.length ? days[0].date : null,
    newest_day: days.length ? days[days.length - 1].date : null,
    bytes,
  }
}

// ── the reader ───────────────────────────────────────────────────────────────────────────────
/**
 * Per-file span cache — and the reason this reader is INCREMENTAL.
 *
 * The lane is asked two different questions: a WINDOW (`hours=`) and a DELTA (`since=`), and
 * any-concurrency asks the window on every dashboard load while its poll loop asks the delta every
 * `SPAN_SOURCE_POLL_S` (5 s). Re-parsing the day's file for either would make this lane the most
 * expensive thing the timeline does, and on the office's filesystem a 4 MB read is not free
 * (measured under load, 2026-09-30: tens of seconds for one full read of the day file, while the
 * endpoint then blew through `SPAN_SOURCE_TIMEOUT_S` and the timeline fell back to its ring). So a
 * file is parsed whole ONCE and every later read takes only the bytes appended since — which is
 * precisely what a delta poll needs — while the parsed rows stay in memory for the window filter.
 *
 * Memory is bounded twice over: at most `CACHE_FILES` files are held (least-recently-used evicted),
 * and a file holding more than `MAX_ROWS_PER_FILE` rows drops its OLDEST ones — recording where it
 * did (`dropped_before`), so a later request for an older window knows to re-read that file from
 * scratch instead of answering short. The reader's answers never claim more than it knows: a window
 * it cannot cover is reported through `history_from` and `truncated`.
 */
const cache = new Map()
const CACHE_FILES = 16
const MAX_ROWS_PER_FILE = 400_000

/** Read `[from, to)` of `path` and fold complete lines into `entry.rows`; keep the partial tail. */
async function readRange(path, entry, from, to) {
  if (to <= from) return
  const chunks = []
  await new Promise((resolve, reject) => {
    const stream = createReadStream(path, { start: from, end: to - 1 })
    stream.on('data', (chunk) => chunks.push(chunk))
    stream.on('error', reject)
    stream.on('end', resolve)
  })
  const text = (entry.tail || '') + Buffer.concat(chunks).toString('utf8')
  const lines = text.split('\n')
  const last = lines.pop() ?? ''          // '' when the slice ended exactly on a newline
  entry.tail = last
  entry.offset = to - Buffer.byteLength(last, 'utf8')
  for (const line of lines) {
    if (!line) continue
    try {
      const row = JSON.parse(line)
      if (row && typeof row === 'object' && row.id && Number.isFinite(Number(row.s))) entry.rows.set(row.id, row)
    } catch {
      // A half-written last line is the one case a JSONL append can produce. It costs that line
      // and nothing else, and the next write of the same span restores it.
    }
  }
  if (entry.rows.size > MAX_ROWS_PER_FILE) {
    const byStart = [...entry.rows.values()].sort((a, b) => Number(a.s) - Number(b.s))
    const cut = byStart[byStart.length - MAX_ROWS_PER_FILE]
    for (const row of byStart) {
      if (Number(row.s) >= Number(cut.s)) break
      entry.rows.delete(row.id)
    }
    entry.dropped_before = Math.max(entry.dropped_before || 0, Number(cut.s))
  }
}

/** The folded spans of one day file, parsing only what has been appended since the last call. */
async function fileSpans(path, neededFrom) {
  let info
  try {
    info = await stat(path)
  } catch {
    cache.delete(path)
    return null
  }
  let entry = cache.get(path)
  if (entry && neededFrom != null && entry.dropped_before && neededFrom < entry.dropped_before) {
    entry = null // a window older than what this entry kept: re-read the file rather than answer short
  }
  if (!entry) {
    entry = { size: 0, offset: 0, tail: '', rows: new Map(), dropped_before: 0, used: 0 }
    cache.set(path, entry)
  }
  if (info.size < entry.offset) {          // truncated or rotated under us: start over
    entry.offset = 0
    entry.tail = ''
    entry.rows.clear()
    entry.dropped_before = 0
  }
  if (info.size > entry.offset) await readRange(path, entry, entry.offset, info.size)
  entry.size = info.size
  entry.used = Date.now()
  while (cache.size > CACHE_FILES) {
    let oldest = null
    for (const [key, value] of cache) if (!oldest || value.used < oldest[1].used) oldest = [key, value]
    if (!oldest || oldest[0] === path) break
    cache.delete(oldest[0])
  }
  return entry
}

/**
 * Every span the ledger holds for `[from, to]`.
 *
 * `since` mode is any-concurrency's delta contract: a span is returned when it STARTED after
 * `since` or ENDED after it — an hour-old span that closes now must reach the timeline now, or it
 * renders as running forever. Spans still running are always returned, because "still running" is
 * a fact about now and not about when they were last touched.
 *
 * Staleness: every line carries its write time (`w`), and a span still marked running whose last
 * line is older than `BINA_TIMELINE_STALE_HOURS` (12) is served as `crashed` ending at `w`. Without
 * that rule, a container restart would leave a "running" bar pinned to now on every future window.
 *
 * The answer says how far back the ledger actually reaches (`history_from`) and, when the cap bit,
 * that it did (`truncated`): custom-sources.md is explicit that a silently truncated list reads as
 * "this is everything that happened".
 */
export async function readSpans({ dir, hours, since, limit = 20000, now = Date.now(),
                                staleHours } = {}) {
  const root = dir || ledgerDir()
  const staleMs = Math.max(1, Number(staleHours ?? process.env.BINA_TIMELINE_STALE_HOURS ?? 12)) * 3600 * 1000
  const to = now
  const from = Number.isFinite(since) && since > 0 ? Number(since)
    : Number.isFinite(hours) ? to - hours * 3600 * 1000
      : to - DAY_MS
  let names = []
  try {
    names = await readdir(root)
  } catch (error) {
    return { spans: [], history_from: null, truncated: false, reason: `ledger unavailable (${root})` }
  }
  const days = names.map(dayBounds).filter(Boolean).sort((a, b) => a.start - b.start)
  // Files are hour-wide (or day-wide, for the legacy names); the window is not: keep every file
  // that overlaps [from, to] at all. Read in start order, so the fold's "last line wins" is right
  // for a span whose open landed in one file and whose close landed in the next.
  const wanted = days.filter((d) => d.end >= from && d.start <= to)
  const folded = new Map()
  for (const day of wanted) {
    const entry = await fileSpans(join(root, day.name), from)
    if (!entry) continue
    for (const [id, row] of entry.rows) folded.set(id, row)
  }
  // Filter FIRST, copy only what is actually served, and never allocate for a row outside the
  // window: this loop runs over every span of every day file in the window (tens of thousands on a
  // live office) on every poll, so an object spread per row is not a detail.
  const out = []
  for (const stored of folded.values()) {
    const s = Number(stored.s)
    const eRaw = stored.e
    const e = eRaw === null || eRaw === undefined ? null : Number(eRaw)
    const running = e === null
    const ends = running ? to : e
    if (s > to) continue
    if (ends < from && !running) continue
    // A span the producer never closed belongs to a process that is gone — a restart, a crash, a
    // kill. Serving it as `running` for ever would draw a bar pinned to "now" on every future
    // window, which is the one lie a timeline must not tell; it becomes `crashed`, ending at the
    // last moment anything was written about it (`w`, the store's own write stamp — carried in the
    // served row, and ignored by the base app). Every span a live process owns is refreshed or
    // closed on its own way out, so this only ever catches the abnormal ending.
    if (running && now - Number(stored.w ?? now) > staleMs) {
      out.push({ ...stored, status: 'crashed', e: Number(stored.w ?? s) })
      continue
    }
    out.push(stored)
  }
  out.sort((a, b) => (Number(a.s) - Number(b.s)) || String(a.id).localeCompare(String(b.id)))
  const truncated = out.length > limit
  return {
    spans: truncated ? out.slice(-limit) : out,
    history_from: days.length ? days[0].start : null,
    days: wanted.length,
    total: out.length,
    truncated,
  }
}
