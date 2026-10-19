/**
 * mapping.js — the agent's session log, read as timeline spans.
 *
 * One rule decides everything here: the timeline is the agent's OWN log, drawn. The harness appends
 * a lossless event for every beat of a session (turn, step, model call, tool call, command,
 * compaction, approval, goal, subagent, workflow, …), and `session/event` hands us each one as it
 * commits. So the projection is not a summary and not a poll of some other store: it is a
 * 1:1 reading of the log where
 *
 *   * a bracketed pair (turn/start→turn/end, step/start→step/end, tool/call→tool/result, …) is a
 *     real span with a real duration, and
 *   * every other event is an instant span at its own timestamp (`s === e`), named for what
 *     happened.
 *
 * The second half is the point of the whole exercise: a timeline that shows only the big brackets
 * answers "was it busy", and the owner asked for "every last thing". An event this build has never
 * heard of (a plugin's own event type) lands as an instant marked with its raw type name rather
 * than vanishing — a vocabulary this file does not know is exactly the case worth seeing.
 *
 * Nothing here throws and nothing here is expensive: unknown data costs a generic label, a missing
 * bracket closes as "we saw the ending, not the beginning", and every string is bounded. The
 * mapping is pure — the clock, the ledger and the network live in index.js and ledger.js.
 */

/** Longest label we keep `meta.text`/excerpts out of: the lane's labels are read, not parsed. */
const EXCERPT = 60
const LABEL_MAX = 120

// ── small helpers ────────────────────────────────────────────────────────────────────────────
const clamp = (s, n = LABEL_MAX) => {
  const one = String(s ?? '').replace(/\s+/g, ' ').trim()
  return one.length <= n ? one : `${one.slice(0, n - 1)}…`
}

/** The text of a message's content blocks (`[{type:'text',text}, …]`), bounded. */
function textOf(content, n = EXCERPT) {
  if (typeof content === 'string') return clamp(content, n)
  if (!Array.isArray(content)) return ''
  const parts = []
  for (const block of content) {
    if (!block || typeof block !== 'object') continue
    if (typeof block.text === 'string') parts.push(block.text)
    else if (typeof block.content === 'string') parts.push(block.content)
    if (parts.join(' ').length > n) break
  }
  return clamp(parts.join(' '), n)
}

const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : undefined)

/** The session's own identity, as the timeline's row. Computed once per session. */
export function sessionInfo(session) {
  const id = String(session?.id ?? '')
  const header = session?.header ?? {}
  const parent = header.parentSession ? String(header.parentSession) : ''
  const delegates = parent !== '' || Number(header.delegationDepth ?? 0) > 0
  const short = id.replace(/^session-/, '').slice(0, 8)
  return {
    id,
    short,
    parent,
    cwd: header.cwd ?? '',
    preset: header.agentPreset ?? '',
    /** The row this session's spans are drawn on. Stable for the session's whole life: a title
     *  that arrives mid-flight must not move every earlier span to a second row. */
    row: delegates ? `תת-סוכן ${short}` : `סשן ${short}`,
  }
}

// ── the bracket vocabulary ───────────────────────────────────────────────────────────────────
/** Turn-end reasons, in the timeline's own status words. */
const TURN_STATUS = {
  completed: 'success',
  error: 'error',
  aborted: 'canceled',
  blocked: 'canceled',
  'max-tokens': 'success',
  interrupted: 'error',
}

/**
 * Events that BRACKET work: `<open>` carries the start, `<close>` the end, both under one id.
 * `key` picks the identity out of each half — a shared id when the harness has one (`callId`,
 * `commandId`), else the opening event's sequence number, else `null` meaning "pair with the
 * oldest open bracket of this kind" (the honest reading of a marker whose payload carries no id).
 */
const BRACKETS = {
  'turn/start': { kind: 'turn', label: (d) => `סבב ${d.turn ?? '?'}`, key: (d) => d.turn },
  'turn/end': { kind: 'turn', close: true, key: (d) => d.turn, status: (d) => TURN_STATUS[d.reason?.kind] || 'unknown', note: (d) => d.reason?.kind },
  'step/start': { kind: 'step', label: (d) => `צעד ${d.turn ?? '?'}.${d.step ?? '?'}`, key: (d) => `${d.turn}.${d.step}` },
  'step/end': { kind: 'step', close: true, key: (d) => `${d.turn}.${d.step}`, status: () => 'success' },
  'tool/call': { kind: 'tool', label: (d) => `${d.name ?? 'כלי'} · ${argsSummary(d.arguments)}`, key: (d) => d.callId, meta: (d) => ({ tool: d.name, args: clamp(d.arguments, 200) }) },
  'tool/result': { kind: 'tool', close: true, key: (d) => d.callId, status: (d) => (d.message?.content?.[0]?.isError === true ? 'error' : 'success'), meta: (d) => ({ error: d.error?.name, reason: clamp(d.error?.reason, 120) }) },
  'command/run': { kind: 'cmd', label: (d) => `פקודה /${d.name ?? '?'}`, key: (d) => d.commandId, meta: (d) => ({ args: clamp(d.args, 120), source: d.source?.kind ?? d.source }) },
  'command/done': { kind: 'cmd', close: true, key: (d) => d.commandId, status: (d) => (d.kind === 'error' ? 'error' : 'success'), meta: (d) => ({ text: clamp(d.text, 120) }) },
  'compaction/start': { kind: 'compact', label: () => 'דחיסת הקשר', key: () => null },
  'compaction/end': { kind: 'compact', close: true, key: () => null, status: () => 'success' },
  'approval/asked': { kind: 'approval', label: (d) => `ממתין לאישור · ${d.tool ?? d.toolName ?? d.request?.toolName ?? '?'}`, key: () => null, status: () => 'waiting', meta: (d) => ({ tool: d.tool ?? d.toolName }) },
  'approval/decided': { kind: 'approval', close: true, key: () => null, status: (d) => (d.decision === 'deny' || d.allowed === false ? 'canceled' : 'success'), meta: (d) => ({ decision: d.decision ?? d.allowed }) },
  'llm/retry-started': { kind: 'retry', label: (d) => `ניסיון חוזר · ${d.provider ?? d.model ?? 'מודל'}`, key: () => null },
  'llm/retry': { kind: 'retry', close: true, key: () => null, status: (d) => (d.error ? 'error' : 'success'), meta: (d) => ({ error: d.error?.name, attempt: num(d.attempt) }) },
  'tool-workflow/run-start': { kind: 'wf', label: (d) => `תהליך · ${clamp(d.title ?? d.name ?? d.workflowId, 40)}`, key: (d) => d.runId ?? d.callId },
  'tool-workflow/run-end': { kind: 'wf', close: true, key: (d) => d.runId ?? d.callId, status: (d) => (d.ok === false || d.error ? 'error' : 'success') },
  'tool-workflow/agent-start': { kind: 'wfagent', label: (d) => `סוכן בתהליך · ${clamp(d.label ?? d.agentId, 40)}`, key: (d) => d.agentId ?? d.runId ?? d.callId },
  'tool-workflow/agent-end': { kind: 'wfagent', close: true, key: (d) => d.agentId ?? d.runId ?? d.callId, status: (d) => (d.ok === false || d.error ? 'error' : 'success') },
  'tool/ptc-dispatch-start': { kind: 'ptc', label: (d) => `שיגור · ${clamp(d.name ?? d.tool, 40)}`, key: () => null },
  'tool/ptc-dispatch': { kind: 'ptc', close: true, key: () => null, status: (d) => (d.isError ? 'error' : 'success') },
}

/** A tool call's arguments, as the one word a person needs to recognise the call. */
function argsSummary(raw) {
  const text = String(raw ?? '').replace(/\s+/g, ' ').trim()
  if (!text) return ''
  try {
    const parsed = JSON.parse(text)
    if (parsed && typeof parsed === 'object') {
      const first = ['command', 'file_path', 'path', 'pattern', 'query', 'url', 'prompt', 'description', 'skill', 'name']
        .map((k) => (typeof parsed[k] === 'string' && parsed[k] ? `${k}=${parsed[k]}` : ''))
        .find(Boolean)
      if (first) return clamp(first, EXCERPT)
      const keys = Object.keys(parsed).slice(0, 3)
      if (keys.length) return clamp(keys.join(','), EXCERPT)
    }
  } catch {
    // not JSON — show it as it came
  }
  return clamp(text, EXCERPT)
}

// ── events that are instants, and how each one is named ──────────────────────────────────────
/**
 * Every session event that is not a bracket becomes an instant span with a name a person reads.
 * A type absent from this table is still emitted, under its own raw name (see `project`), so a
 * harness upgrade or a new plugin widens the timeline instead of silently narrowing it.
 */
const INSTANTS = {
  'user/message': (d) => ({ label: `קלט · ${textOf(d.content) || (d.source?.kind ?? 'הודעה')}`, meta: { source: d.source?.kind ?? d.source } }),
  'system/message': (d) => ({ label: `הנחיות מערכת · ${textOf(d.message?.content, 40).length} תווים`, meta: { chars: textOf(d.message?.content, 40000).length } }),
  'assistant/attempt': (d) => ({ label: `ניסיון מודל ללא תשובה${d.error?.name ? ` · ${d.error.name}` : ''}`, status: 'error', meta: { error: d.error?.name } }),
  'request/header': (d) => ({ label: `בקשה · ${d.header?.config?.provider ?? '?'}/${d.header?.config?.model ?? '?'}`, meta: { reason: d.reason, model: d.header?.config?.model } }),
  'request/context': (d) => ({ label: `הקשר בקשה · ${d.provider ?? '?'}/${d.model ?? '?'}`, meta: { context_window: num(d.contextWindow) } }),
  'model/selection': (d) => ({ label: `בחירת מודל · ${d.model ?? d.selected ?? '?'}`, meta: { model: d.model ?? d.selected } }),
  'compaction/summary': (d) => ({ label: `סיכום דחיסה · ${textOf(d.summary ?? d.text, 40)}` }),
  'compaction/prune': (d) => ({ label: `גיזום הקשר${Number.isFinite(Number(d.removed)) ? ` · ${d.removed}` : ''}`, meta: { removed: num(d.removed) } }),
  'goal/change': (d) => ({ label: `מטרה · ${clamp(d.goal?.objective ?? d.objective ?? d.phase ?? d.kind, 48)}`, meta: { op: d.op ?? d.kind, phase: d.goal?.phase ?? d.phase } }),
  'plan/mode': (d) => ({ label: `מצב תכנון · ${d.mode ?? d.planMode ?? '?'}`, meta: { mode: d.mode ?? d.planMode } }),
  'todo/write': (d) => ({ label: `רשימת משימות · ${Array.isArray(d.todos) ? d.todos.length : '?'}`, meta: { items: Array.isArray(d.todos) ? d.todos.length : undefined } }),
  'session/title': (d) => ({ label: `כותרת · ${clamp(d.title ?? d.text ?? d.snapshot?.title, 48)}`, meta: { title: clamp(d.title ?? d.text ?? d.snapshot?.title, 120) } }),
  'session/end-seed': null, // log plumbing: never work, always noise
  'permission/preset': (d) => ({ label: `הרשאות · ${d.preset ?? d.mode ?? '?'}`, meta: { preset: d.preset ?? d.mode } }),
  'sandbox/mode': (d) => ({ label: `ארגז חול · ${d.mode ?? '?'}`, meta: { mode: d.mode } }),
  'agent-preset/selected': (d) => ({ label: `תצורת סוכן · ${d.agentPreset ?? d.preset ?? '?'}`, meta: { preset: d.agentPreset ?? d.preset } }),
  'agent/inbox/spliced': (d) => ({
    label: `תור הסוכן · הוזנו ${Array.isArray(d.inserted) ? d.inserted.length : '?'}${d.removedCount ? ` · הוסרו ${d.removedCount}` : ''}`,
    status: d.outcome === 'canceled' ? 'canceled' : 'success',
    meta: { target: d.target?.kind ?? d.target, inserted: Array.isArray(d.inserted) ? d.inserted.length : undefined, removed: num(d.removedCount) },
  }),
  'deliverables/presented': (d) => ({ label: `תוצרים · ${Array.isArray(d.files) ? d.files.length : '?'}`, meta: { files: Array.isArray(d.files) ? d.files.length : undefined } }),
  'image/offload': (d) => ({ label: 'העברת תמונה מההקשר', meta: { id: d.id } }),
  'feedback/record': (d) => ({ label: `משוב · ${d.rating ?? d.kind ?? '?'}`, meta: { kind: d.kind } }),
  'feedback/message-put': () => ({ label: 'משוב על הודעה' }),
  'feedback/message-delete': () => ({ label: 'מחיקת משוב' }),
  'schedule/change': (d) => ({ label: `תזמון · ${d.op ?? d.kind ?? '?'}`, meta: { op: d.op ?? d.kind } }),
  'hook/invoked': (d) => ({ label: `וובהוק פנימי · ${clamp(d.name ?? d.event ?? d.kind, 32)}` }),
  'hook/result': (d) => ({ label: `תוצאת וובהוק · ${clamp(d.name ?? d.event ?? d.kind, 32)}` }),
  'team/member': (d) => ({ label: `חבר צוות · ${clamp(d.name ?? d.memberId ?? d.op, 32)}`, meta: { op: d.op } }),
  'team/task': (d) => ({ label: `משימת צוות · ${clamp(d.subject ?? d.taskId ?? d.op, 32)}`, meta: { op: d.op } }),
  'team/message/queued': (d) => ({ label: `הודעה לקבוצה · ${clamp(d.subject ?? d.to, 32)}` }),
  'team/message/delivered': (d) => ({ label: `הודעה נמסרה · ${clamp(d.subject ?? d.to, 32)}` }),
  'subagent/catalog': (d) => ({
    label: `קטלוג תת-סוכנים · ${d.op ?? (Array.isArray(d.entries) ? d.entries.length : Array.isArray(d.providers) ? d.providers.length : '?')}`,
    meta: { op: d.op },
  }),
  'approval/policy': (d) => ({
    label: `מדיניות אישורים · ${typeof d.policy === 'string' ? d.policy : (d.policy?.kind ?? d.policy?.mode ?? '?')}${d.source ? ` (${d.source})` : ''}`,
    meta: { policy: typeof d.policy === 'string' ? d.policy : undefined, source: d.source },
  }),
  'subagent/descriptor': (d) => ({ label: `תת-סוכן · ${clamp(d.descriptor?.label ?? d.label ?? d.op, 40)}`, meta: { op: d.op } }),
  'subagent/model-selection-policy': () => ({ label: 'מדיניות מודל לתת-סוכנים' }),
  'session/title-llm-request': (d) => ({ label: `בקשת כותרת · ${clamp(d.model, 32)}`, meta: { model: d.model } }),
  'web/deepseek-search-llm-request': (d) => ({ label: `חיפוש רשת · ${clamp(d.query, 40)}`, meta: { query: clamp(d.query, 120) } }),
  // Plumbing, named and excluded on purpose: the session-log delivery receipt fires once per log
  // upload and, measured on a live office (2026-09-30, five working sessions), it was 842 of ~2 800
  // spans in 40 minutes — tripling the density of the rows it shares with real work while saying
  // nothing about what the agent did. `BINA_TIMELINE_VERBOSE=1` draws it (and `session/end-seed`)
  // again; nothing else is ever filtered, and an event this build has never seen is always drawn.
  'session-log-deepseek/delivery-accepted': null,
  'tool/ptc-dispatch-log': (d) => ({ label: `יומן שיגור · ${clamp(d.name ?? d.tool, 32)}` }),
}

// ── the projection ───────────────────────────────────────────────────────────────────────────
/**
 * The per-session bracket bookkeeping. One of these lives per session id and is the only state
 * this projection has: which brackets are open, and how many of each kind.
 */
export function createTrack(info, options = {}) {
  return { info, open: new Map(), currentTurn: null, title: '', verbose: options.verbose === true }
}

/** The oldest bracket of a kind still open — how a close with no id of its own finds its start. */
function oldestOpen(track, kind) {
  for (const bracket of track.open.values()) if (bracket.kind === kind) return bracket
  return undefined
}

const row = (track, id, { label, status, s, e, meta }) => ({
  id,
  svc: track.info.row,
  svcid: track.info.id,
  label: clamp(label || id),
  status: status || 'unknown',
  s,
  e: e ?? null,
  meta: {
    session: track.info.id,
    ...(track.info.parent ? { parent_session: track.info.parent } : {}),
    ...(meta || {}),
  },
})

/**
 * One session event in, zero or more span rows out.
 *
 * Rows carry the span's WHOLE state, not a delta — the ledger is folded by id, so re-emitting a
 * span with a longer label or a later end is how an update is expressed.
 */
export function project(track, event, at = Date.now()) {
  const rows = []
  const type = String(event?.type ?? '')
  const d = event?.data ?? {}
  const t = num(event?.time) ?? at
  const seq = num(event?.seq)

  const open = (kind, key, fields) => {
    // The bracket REMEMBERS how it was described: a closer (`turn/end`, `tool/result`) carries the
    // outcome and no name of its own, so the bar must keep the name its opener gave it — otherwise
    // closing a tool call renames it to "כלי" and the timeline loses the only useful word on it.
    const bracket = { id: `${track.info.id}:${kind}:${key ?? seq ?? t}`, s: t, kind, key: key ?? null,
                      label: fields.label, meta: fields.meta }
    bracket.slot = `${kind}:${key ?? `#${seq ?? t}`}`
    track.open.set(bracket.slot, bracket)
    rows.push(row(track, bracket.id, { ...fields, s: t, e: null, status: fields.status || 'running' }))
    return bracket
  }

  /** Close a bracket. A close with no matching open is still reported — as an instant, since the
   *  beginning happened before this projection was watching and inventing a start would lie. */
  const close = (kind, key, fields) => {
    const named = key === null || key === undefined ? undefined : track.open.get(`${kind}:${key}`)
    const bracket = named ?? oldestOpen(track, kind)
    if (bracket) {
      track.open.delete(bracket.slot)
      rows.push(row(track, bracket.id, {
        label: fields.label ?? bracket.label,
        status: fields.status,
        s: bracket.s,
        e: Math.max(bracket.s, t),
        meta: { ...(bracket.meta || {}), ...(fields.meta || {}) },
      }))
      return
    }
    rows.push(row(track, `${track.info.id}:${kind}:late:${seq ?? t}`, { ...fields, s: t, e: t }))
  }

  const bracket = BRACKETS[type]
  if (bracket) {
    const key = bracket.key ? bracket.key(d) : null
    if (bracket.close) {
      close(bracket.kind, key, {
        // only when the CLOSER names itself; otherwise the opener's description stands
        ...(bracket.label ? { label: bracket.label(d) } : {}),
        status: bracket.status ? bracket.status(d) : 'success',
        meta: { ...(bracket.meta ? bracket.meta(d) : {}), ev: type, seq, turn: num(d.turn), step: num(d.step), reason: bracket.note ? bracket.note(d) : undefined },
      })
    } else {
      open(bracket.kind, key, {
        label: bracket.label ? bracket.label(d) : kindLabel(bracket.kind),
        meta: { ...(bracket.meta ? bracket.meta(d) : {}), ev: type, seq, turn: num(d.turn), step: num(d.step) },
      })
    }
    if (bracket.kind === 'turn' && !bracket.close) track.currentTurn = d.turn ?? track.currentTurn
    return rows
  }

  // `assistant/message` is the model's answer: it is the STEP's payload, so it sharpens the step
  // it belongs to instead of adding a bar of its own.
  if (type === 'assistant/message') {
    const slotKey = `step:${d.turn}.${d.step}`
    const bracketOpen = track.open.get(slotKey)
    const usage = d.usage || {}
    const tokens = num(usage.totalTokens ?? usage.outputTokens ?? usage.inputTokens)
    if (bracketOpen) {
      rows.push(row(track, bracketOpen.id, {
        label: `צעד ${d.turn}.${d.step}${tokens ? ` · ${tokens} טוקנים` : ''}${d.interrupted ? ' · נקטע' : ''}`,
        status: 'running',
        s: bracketOpen.s,
        e: null,
        meta: { ev: type, seq, turn: num(d.turn), step: num(d.step), model: d.message?.source?.model, tokens, interrupted: d.interrupted === true },
      }))
    }
    if (d.interrupted === true) {
      rows.push(row(track, `${track.info.id}:ev:${seq ?? t}:interrupted`, {
        label: `תשובה נקטעה · סבב ${d.turn ?? '?'}`,
        status: 'canceled',
        s: t,
        e: t,
        meta: { ev: type, seq },
      }))
    }
    return rows
  }

  const instant = INSTANTS[type]
  if (instant === null && !track.verbose) return rows
  const made = (instant ? instant(d) : null) || { label: type, meta: {} }
  if (!made) return rows
  rows.push(row(track, `${track.info.id}:ev:${seq ?? t}:${type.replace(/[^A-Za-z0-9]+/g, '-')}`, {
    label: made.label,
    status: made.status || 'success',
    s: t,
    e: t,
    meta: { ev: type, seq, ...(made.meta || {}) },
  }))
  if (type === 'session/title') track.title = String(made.meta?.title ?? '')
  // The prompt that opens a turn arrives AFTER `turn/start`, under the message event itself: the
  // turn's bar is re-sent with the text, so the row reads "what was asked", not "סבב 7".
  // Only a message the PERSON sent names the turn (`source.kind === 'user'`): an injected reminder
  // or a skill's content is context the harness spliced in, and a bar labelled
  // "<system-reminder> …" says nothing about what the owner asked for.
  if (type === 'user/message' && d?.source?.kind === 'user' && track.currentTurn !== null) {
    const slotKey = `turn:${track.currentTurn}`
    const bracketOpen = track.open.get(slotKey)
    const prompt = textOf(d.content, 48)
    if (bracketOpen && prompt) {
      rows.push(row(track, bracketOpen.id, {
        label: `סבב ${track.currentTurn} · ${prompt}`,
        status: 'running',
        s: bracketOpen.s,
        e: null,
        meta: { ev: 'turn/start', turn: track.currentTurn, prompt: clamp(d.content ? textOf(d.content, 200) : '', 200) },
      }))
    }
  }
  return rows
}

/** Close every bracket still open (session disposal, or the process going down in order). */
export function closeAll(track, at = Date.now(), status = 'canceled') {
  const rows = []
  for (const bracket of track.open.values()) {
    rows.push(row(track, bracket.id, {
      label: bracket.label ?? kindLabel(bracket.kind),
      status,
      s: bracket.s,
      e: Math.max(bracket.s, at),
      meta: { closed_by: 'dispose' },
    }))
  }
  track.open.clear()
  return rows
}

const KIND_LABELS = {
  turn: 'סבב',
  step: 'צעד',
  tool: 'כלי',
  cmd: 'פקודה',
  compact: 'דחיסת הקשר',
  approval: 'אישור',
  retry: 'ניסיון חוזר',
  wf: 'תהליך',
  wfagent: 'סוכן בתהליך',
  ptc: 'שיגור',
}

const kindLabel = (kind) => KIND_LABELS[kind] || kind
