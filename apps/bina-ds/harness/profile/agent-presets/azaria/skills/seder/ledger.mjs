/**
 * seder/ledger — the day's own bill, from the office's real session store.
 *
 * WHY THIS EXISTS. Step 8 of a סדר (תיעוד) ends with a balance: how many sessions, turns, tool calls
 * and shekels that cycle burned. The number the owner reads must come from the same arithmetic as the
 * pill in his own screen, so the prices here are the ones in
 * `apps/bina-ds/plugins/cost-meter/lib/pricing.js` (DeepSeek's published table, peak = half again).
 * A second copy of the formula that drifts would make the balance a decoration.
 *
 * TWO TRAPS, both paid for once:
 *   * The session store is one zstd-compressed JSONL file per session, written as a SEQUENCE of zstd
 *     frames (one per batch of events) — hence the frame split. A single streaming decompress stops
 *     at the first frame and silently reports a fraction of the session.
 *   * A session is not a day. One long session can run past midnight, and grouping its whole cost
 *     under its start date moves real money between days (measured: a session opened 2026-10-12
 *     23:00 and run to 03:00 carried ₪26.5 into the wrong day). So every request is billed to the day
 *     it was MADE, exactly like the provider's own bill, and a session that crosses midnight appears
 *     in both days with the part it spent in each.
 *
 * Usage: node ledger.mjs [YYYY-MM-DD] [--dir /data/dsh/sessions] [--json] [--line]
 *   no date  → today (Asia/Jerusalem)
 *   --json   → machine-readable: one object per session-day
 *   --line   → ONE line for the agent's own context: the day's spend against the ₪1, the spend of the
 *              session that is writing right now, and its step count against the 40-step cap. This is
 *              the door for "the agent must know its ceiling at all times" — it costs ~0.02 agorot, and
 *              its number is what the pre-action line carries. The cap is the agent's own discipline,
 *              because the harness has no step limit and no `interrupt` route (probed 2026-10-14: 404).
 */
import fs from 'node:fs'
import path from 'node:path'
import zlib from 'node:zlib'
import { execFileSync } from 'node:child_process'

/** USD per 1M tokens at DeepSeek's PEAK rate; mirrors cost-meter/pricing.js. */
const PRICES = {
  flash: { cacheHit: 0.006, cacheMiss: 0.3, output: 1.2 },
  pro: { cacheHit: 0.044, cacheMiss: 1.32, output: 3.96 },
}
const MODEL_ALIASES = {
  'deepseek-flash': 'flash',
  'deepseek-v4-flash': 'flash',
  'deepseek-v4-flash-vision-exp': 'flash',
  'deepseek-v4-pro': 'pro',
  'deepseek-v4-pro-0813': 'pro',
}
const USD_RATE = 3.7
/** Peak windows in UTC hours [from, to); the rest of the day (and weekends) is half price. */
const PEAK_HOURS_UTC = [[1, 4], [6, 10]]
const ZSTD_MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])
const TIMEZONE = 'Asia/Jerusalem'

/** Whether one request's own timestamp falls in a peak window. */
function isPeak(timeMs) {
  const at = new Date(timeMs)
  const day = at.getUTCDay()
  if (day === 0 || day === 6) return false
  const hour = at.getUTCHours() + at.getUTCMinutes() / 60
  return PEAK_HOURS_UTC.some(([from, to]) => hour >= from && hour < to)
}

/** Every frame of one session file, decompressed and parsed into events. */
function readSession(file) {
  const raw = fs.readFileSync(file)
  const offsets = []
  for (let at = raw.indexOf(ZSTD_MAGIC); at !== -1; at = raw.indexOf(ZSTD_MAGIC, at + 4)) offsets.push(at)
  let text = ''
  for (let index = 0; index < offsets.length; index += 1) {
    const end = index + 1 < offsets.length ? offsets[index + 1] : raw.length
    try {
      text += zlib.zstdDecompressSync(raw.subarray(offsets[index], end)).toString('utf8')
    } catch {
      // A frame boundary the splitter got wrong is skipped, never fatal.
    }
  }
  const events = []
  for (const line of text.split('\n')) {
    if (line.trim().length === 0) continue
    try {
      events.push(JSON.parse(line))
    } catch {
      // A truncated last line (a session being written right now) is skipped.
    }
  }
  return events
}

/** The usage sample one event carries, or undefined — mirrors cost-meter's usageOf(). */
function usageOf(event) {
  const data = event?.data
  if (data === undefined) return undefined
  if (event.type === 'assistant/message' && data.usage !== undefined) return data.usage
  if (event.type !== 'assistant/message' && event.type !== 'assistant/attempt') return undefined
  const stream = data.stream
  if (!Array.isArray(stream)) return undefined
  for (let index = stream.length - 1; index >= 0; index -= 1) {
    const record = stream[index]
    if (record?.type === 'chunk' && record.chunk?.type === 'usage') return record.chunk.usage
  }
  return undefined
}

/** The local (Asia/Jerusalem) date of one timestamp. */
const localDay = (ms) => new Date(ms).toLocaleDateString('sv-SE', { timeZone: TIMEZONE })

const emptyDay = () => ({ cost: 0, cacheHit: 0, cacheMiss: 0, output: 0, tools: 0, turns: 0, requests: 0, coldStart: 0, firstAt: 0, lastAt: 0 })

/** One session, split into the days its own requests were made in. */
function foldSession(file) {
  const events = readSession(file)
  const head = events.find((event) => event.type === 'session') ?? {}
  const startedAt = head.createdAt ?? events[0]?.time ?? 0
  const days = new Map()
  let coldStart = 0
  for (const event of events) {
    const at = event.time ?? startedAt
    const day = localDay(at)
    if (!days.has(day)) days.set(day, emptyDay())
    const bucket = days.get(day)
    if (event.type === 'tool/call') bucket.tools += 1
    if (event.type === 'turn/start') bucket.turns += 1
    const usage = usageOf(event)
    if (usage === undefined) continue
    const row = PRICES[MODEL_ALIASES[event.data?.message?.source?.model] ?? 'flash']
    const missed = (usage.inputTokens ?? 0) + (usage.cacheWriteTokens ?? 0)
    const factor = isPeak(at) ? 1 : 0.5
    bucket.cacheHit += usage.cacheReadTokens ?? 0
    bucket.cacheMiss += missed
    bucket.output += usage.outputTokens ?? 0
    bucket.requests += 1
    bucket.cost += ((usage.cacheReadTokens ?? 0) * row.cacheHit + missed * row.cacheMiss + (usage.outputTokens ?? 0) * row.output) / 1e6 * factor
    if (coldStart === 0) {
      coldStart = missed
      bucket.coldStart = missed
    }
    if (bucket.firstAt === 0 || at < bucket.firstAt) bucket.firstAt = at
    if (at > bucket.lastAt) bucket.lastAt = at
  }
  for (const bucket of days.values()) bucket.cost *= USD_RATE
  // A CYCLE IS A SESSION TITLED «סדר …» — the title the door gives it. That is what separates the
  // day's WORK BUDGET (the grant, and the cycles that spend it) from everything else the day's
  // ledger holds: the owner's own conversation, the office's build sessions, a subagent of either.
  // Measured 2026-10-14: without the split, a ₪2 grant read as "day ₪5.89 — over" and the cycle would
  // have gone into ratio mode with three quarters of its own money unspent.
  let title = ''
  for (const event of events) {
    if (event.type === 'session/title' && event.data?.title) title = String(event.data.title)
  }
  return {
    id: path.basename(path.dirname(file)), origin: head.origin ?? 'main', parent: head.parentSession ?? '',
    startedAt, days, title, seder: title.startsWith('סדר '),
  }
}

const args = process.argv.slice(2)
const asJson = args.includes('--json')
const asLine = args.includes('--line')
const asSplit = args.includes('--split')
const dirIndex = args.indexOf('--dir')
const root = dirIndex === -1 ? '/data/dsh/sessions' : args[dirIndex + 1]
const wanted = args.find((arg) => /^\d{4}-\d{2}-\d{2}$/.test(arg))
const today = localDay(Date.now())
const wantedDay = wanted ?? today

/** Where the office's own files live (the day folders and a day's grant are written under it). */
const rootOfOffice = () => process.env.DSH_OFFICE_ROOT || '/workspace/office'

const sessions = []
for (const namespace of fs.readdirSync(root)) {
  const namespaceDir = path.join(root, namespace)
  if (!fs.statSync(namespaceDir).isDirectory()) continue
  for (const sessionId of fs.readdirSync(namespaceDir)) {
    const file = path.join(namespaceDir, sessionId, 'session.v3.jsonl.zstd')
    if (fs.existsSync(file)) sessions.push(foldSession(file))
  }
}

/** Every session-day row, newest first, the day's own money attached to the day it was spent. */
const rows = []
for (const session of sessions) {
  for (const [day, bucket] of session.days) {
    rows.push({ ...bucket, day, id: session.id, origin: session.origin, startedAt: session.startedAt })
  }
}
const total = (list, key) => list.reduce((sum, item) => sum + item[key], 0)
const shekel = (value) => `₪${value.toFixed(3)}`
const thousands = (value) => `${Math.round(value / 1000)}K`
const clock = (ms) => new Date(ms).toLocaleTimeString('he-IL', { timeZone: TIMEZONE, hour: '2-digit', minute: '2-digit' })

const ofWanted = rows.filter((row) => row.day === wantedDay)
const byDay = new Map()
for (const row of rows) {
  if (!byDay.has(row.day)) byDay.set(row.day, [])
  byDay.get(row.day).push(row)
}

if (asSplit) {
  // MANAGEMENT vs WORK — the owner's bar (2026-10-14): at least 90% of a cycle's money must land in
  // the executors (the `subagent` sessions a seder opened), and at most 10% in the office's own turns.
  // This is the line that says whether a cycle advanced the product or only talked about it.
  const rowsToday = rows.filter((row) => row.day === today)
  const work = total(rowsToday.filter((row) => row.origin === 'subagent'), 'cost')
  const managing = total(rowsToday.filter((row) => row.origin !== 'subagent'), 'cost')
  const sum = work + managing
  console.log(`יחס היום: ביצוע ₪${work.toFixed(2)} · ניהול ₪${managing.toFixed(2)} · ביצוע ${sum > 0 ? Math.round((work / sum) * 100) : 0}% (היעד 90%)`)
} else if (asLine) {
  // WHICH SESSION IS "THIS CYCLE". Touched-last is a guess, and a wrong guess on a tie was measured
  // (two sessions writing in the same second gave the line another session's numbers). The agent API
  // knows the truth — it reports which sessions are RUNNING — so that answer is preferred, and the
  // newest file is only the fallback when nothing is running (a cycle that is composing its report).
  let runningId = ''
  try {
    const token = fs.readFileSync(path.join(process.env.DSH_HOME ?? '/data/dsh', 'api-token'), 'utf8').trim()
    const answer = execFileSync('curl', ['-s', '--max-time', '5', '-H', `Authorization: Bearer ${token}`, `${process.env.BINA_DS_AGENT_URL ?? 'http://127.0.0.1:3081'}/v1/sessions`], { encoding: 'utf8' })
    const running = (JSON.parse(answer).sessions ?? []).filter((session) => session.running === true)
    if (running.length === 1) runningId = running[0].id
  } catch {
    // No API, no token, no answer — the file heuristic below still gives a number.
  }
  let active = null
  for (const namespace of fs.readdirSync(root)) {
    const namespaceDir = path.join(root, namespace)
    if (!fs.statSync(namespaceDir).isDirectory()) continue
    for (const sessionId of fs.readdirSync(namespaceDir)) {
      const file = path.join(namespaceDir, sessionId, 'session.v3.jsonl.zstd')
      if (!fs.existsSync(file)) continue
      if (runningId !== '' && sessionId !== runningId) continue
      const mtime = runningId === '' ? fs.statSync(file).mtimeMs : Number.POSITIVE_INFINITY
      if (active === null || mtime > active.mtime) active = { file, mtime, id: sessionId }
    }
  }
  let cycle = 0
  let steps = 0
  if (active !== null) {
    const events = readSession(active.file)
    let lastTurn = 0
    for (const event of events) if (event.type === 'turn/start' && event.data?.turn > lastTurn) lastTurn = event.data.turn
    for (const event of events) {
      if (event.type === 'step/start' && event.data?.turn === lastTurn) steps += 1
      const usage = usageOf(event)
      if (usage === undefined) continue
      const at = event.time ?? 0
      if (localDay(at) !== today) continue
      const row = PRICES[MODEL_ALIASES[event.data?.message?.source?.model] ?? 'flash']
      const missed = (usage.inputTokens ?? 0) + (usage.cacheWriteTokens ?? 0)
      cycle += ((usage.cacheReadTokens ?? 0) * row.cacheHit + missed * row.cacheMiss + (usage.outputTokens ?? 0) * row.output) / 1e6 * (isPeak(at) ? 1 : 0.5)
    }
    cycle *= USD_RATE
  }
  // A CYCLE'S EXECUTORS ARE THEIR OWN SESSIONS, AND THEIR AGOROT BELONG TO THE CYCLE. The skill says
  // the seder session manages and every item runs in a separate session; measured on 2026-10-14, שחרית
  // showed ₪0.26 while its executor spent ₪0.11 more — a meter that ignores the executors is not a
  // meter for a ₪1 day. So the parent chain is walked from the session running right now, and every
  // session under it that was created after it counts.
  const norm = (value) => String(value ?? '').replace(/^session-/, '')
  const byId = new Map(sessions.map((session) => [norm(session.id), session]))
  let executors = 0
  if (active !== null) {
    const rootId = norm(path.basename(path.dirname(active.file)))
    const under = (session) => {
      let cursor = session
      for (let hop = 0; hop < 6; hop += 1) {
        const parent = norm(cursor.parent)
        if (parent === '') return false
        if (parent === rootId) return true
        cursor = byId.get(parent)
        if (cursor === undefined) return false
      }
      return false
    }
    for (const session of sessions) {
      if (norm(session.id) === rootId) continue
      if (session.startedAt < (byId.get(rootId)?.startedAt ?? 0)) continue
      if (!under(session)) continue
      executors += (session.days.get(today) ?? { cost: 0 }).cost
    }
  }
  const day = total(rows.filter((row) => row.day === today), 'cost')

  // THE DAY'S WORK BUDGET — the grant, and what the cycles have spent of it. Everything the day's
  // ledger holds that is NOT a cycle (the owner's conversation, the office's build sessions) is
  // reported beside it, never mixed into it: the grant is for the cycles' work.
  let cycles = 0
  for (const session of sessions) {
    if (!session.seder) continue
    cycles += (session.days.get(today) ?? { cost: 0 }).cost
    for (const other of sessions) {
      if (norm(other.id) === norm(session.id)) continue
      let cursor = other
      let isUnder = false
      for (let hop = 0; hop < 6 && cursor !== undefined; hop += 1) {
        const parent = norm(cursor.parent)
        if (parent === '') break
        if (parent === norm(session.id)) { isUnder = true; break }
        cursor = byId.get(parent)
      }
      if (isUnder) cycles += (other.days.get(today) ?? { cost: 0 }).cost
    }
  }
  let grant = 1
  try {
    grant = Number(JSON.parse(fs.readFileSync(path.join(rootOfOffice(), 'data/bina-ds/sedarim', today, 'תקציב.json'), 'utf8')).grant) || 1
  } catch { /* no grant written for today — the office default of ₪1 */ }
  const grantNote = ` · הסדרים ₪${cycles.toFixed(2)}/₪${grant.toFixed(2)} (${Math.round((cycles / grant) * 100)}%)`
  const executorsNote = executors > 0.005 ? ` (מבצעים ₪${executors.toFixed(2)})` : ''
  console.log(`תקציב: הסדר הזה ₪${(cycle + executors).toFixed(2)}${executorsNote}${grantNote} · היום (הכל) ₪${day.toFixed(2)} · צעד ${steps}/40`)
} else if (asJson) {
  console.log(JSON.stringify(ofWanted.sort((a, b) => b.cost - a.cost), null, 2))
} else {
  const lines = []
  lines.push(`מאזן ${wantedDay}: ${ofWanted.length} סדרים · ${total(ofWanted, 'turns')} סיבובים · ${total(ofWanted, 'tools')} קריאות כלים · ${total(ofWanted, 'requests')} בקשות`)
  lines.push(`טוקנים: ${thousands(total(ofWanted, 'cacheMiss'))} שלא במטמון · ${thousands(total(ofWanted, 'cacheHit'))} מהמטמון · פלט ${thousands(total(ofWanted, 'output'))}`)
  lines.push(`עלות: ${shekel(total(ofWanted, 'cost'))}`)
  for (const row of [...ofWanted].sort((a, b) => b.cost - a.cost)) {
    const span = row.firstAt === row.lastAt ? clock(row.firstAt) : `${clock(row.firstAt)}–${clock(row.lastAt)}`
    lines.push(`  ${span.padEnd(12)} ${shekel(row.cost).padStart(9)}  ${row.origin.padEnd(8)} ${String(row.turns).padStart(3)} סיבובים ${String(row.tools).padStart(4)} כלים  פתיחה ${thousands(row.coldStart)}`)
  }
  lines.push('ימים אחרונים:')
  for (const day of [...byDay.keys()].sort().slice(-7)) {
    const list = byDay.get(day)
    lines.push(`  ${day}  ${shekel(total(list, 'cost')).padStart(9)}  ${String(list.length).padStart(3)} סדרים  ${String(total(list, 'turns')).padStart(4)} סיבובים  ${String(total(list, 'tools')).padStart(5)} כלים`)
  }
  console.log(lines.join('\n'))
}
