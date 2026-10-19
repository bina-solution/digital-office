/**
 * The projection's own test: a session read as spans.
 *
 * It runs with `node --test apps/bina-ds/plugins/timeline-lanes/test/` and needs nothing but node —
 * no harness, no container, no network. The interesting cases are the ugly ones: an event type this
 * build has never heard of, a close whose open was never seen (the plugin mounted mid-session), and
 * a turn whose prompt arrives after the turn started.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { createTrack, project, sessionInfo, closeAll } from '../lib/mapping.js'
import { Ledger, ledgerStatus, readSpans } from '../lib/ledger.js'

const session = { id: 'session-1234abcd-0000-0000-0000-000000000000', header: { cwd: '/office', agentPreset: 'azaria' } }
const subagent = { id: 'session-9999ffff-0000-0000-0000-000000000000', header: { parentSession: session.id, delegationDepth: 1 } }

const track = () => createTrack(sessionInfo(session))

test('a turn is a span, and its prompt arrives a beat later', () => {
  const t = track()
  const start = project(t, { type: 'turn/start', seq: 1, time: 1000, data: { turn: 1 } })
  assert.equal(start.length, 1)
  assert.equal(start[0].status, 'running')
  assert.equal(start[0].s, 1000)
  assert.equal(start[0].e, null)
  assert.equal(start[0].svc, t.info.row, 'the row is the session, stable for its whole life')

  const injected = project(t, { type: 'user/message', seq: 2, time: 1002, data: { content: [{ type: 'text', text: '<system-reminder> office instructions' }], source: { kind: 'plugin' } } })
  assert.match(injected[0].label, /system-reminder/, 'an injected context still lands as its own instant')
  assert.equal(injected.length, 1, 'and it does NOT rename the turn bar')
  const prompt = project(t, { type: 'user/message', seq: 3, time: 1005, data: { content: [{ type: 'text', text: 'תוסיף אינטגרציה מלאה' }], source: { kind: 'user' } } })
  assert.equal(prompt.length, 2)
  assert.match(prompt[1].label, /סבב 1 · תוסיף/)
  assert.equal(prompt[1].id, start[0].id, 'the turn bar is re-sent, not duplicated')

  const end = project(t, { type: 'turn/end', seq: 9, time: 5000, data: { turn: 1, reason: { kind: 'completed' } } })
  assert.equal(end[0].id, start[0].id)
  assert.equal(end[0].status, 'success')
  assert.equal(end[0].e, 5000)
  assert.equal(end[0].meta.reason, 'completed')
})

test('a tool call is a span with the tool and its argument in the label', () => {
  const t = track()
  project(t, { type: 'turn/start', seq: 1, time: 1000, data: { turn: 1 } })
  project(t, { type: 'step/start', seq: 2, time: 1001, data: { turn: 1, step: 1 } })
  const call = project(t, { type: 'tool/call', seq: 3, time: 1100, data: { turn: 1, step: 1, callId: 'c1', name: 'bash', arguments: '{"command":"ls -la"}' } })
  assert.match(call[0].label, /bash · command=ls -la/)
  assert.equal(call[0].status, 'running')
  const result = project(t, { type: 'tool/result', seq: 4, time: 1600, data: { turn: 1, step: 1, callId: 'c1', message: { content: [{ isError: false }] } } })
  assert.equal(result[0].id, call[0].id)
  assert.equal(result[0].status, 'success')
  assert.equal(result[0].e - result[0].s, 500)
  assert.equal(result[0].label, call[0].label, 'closing a call does not rename its bar')
  assert.match(result[0].label, /bash/)
  assert.equal(result[0].meta.tool, 'bash', 'the opener\'s meta survives the closer')
})

test('a failing tool result is an error span, and its reason stays outside the model', () => {
  const t = track()
  project(t, { type: 'tool/call', seq: 1, time: 10, data: { callId: 'c9', name: 'read' } })
  const result = project(t, { type: 'tool/result', seq: 2, time: 20, data: { callId: 'c9', message: { content: [{ isError: true }] }, error: { name: 'ENOENT', code: 'ENOENT', reason: 'no such file' } } })
  assert.equal(result[0].status, 'error')
  assert.equal(result[0].meta.error, 'ENOENT')
})

test('every unmapped event still lands, under its own name', () => {
  const t = track()
  const rows = project(t, { type: 'someplugin/whatever', seq: 7, time: 42, data: {} })
  assert.equal(rows.length, 1)
  assert.equal(rows[0].label, 'someplugin/whatever')
  assert.equal(rows[0].s, 42)
  assert.equal(rows[0].e, 42, 'an instant, drawn 3px wide by the timeline')
  assert.equal(rows[0].meta.ev, 'someplugin/whatever')
})

test('plumbing is deliberately not drawn, and a close with no open is an instant', () => {
  const t = track()
  assert.deepEqual(project(t, { type: 'session/end-seed', seq: 1, time: 1, data: {} }), [])
  assert.deepEqual(project(t, { type: 'session-log-deepseek/delivery-accepted', seq: 2, time: 1, data: {} }), [])
  const loud = createTrack(sessionInfo(session), { verbose: true })
  assert.equal(project(loud, { type: 'session/end-seed', seq: 1, time: 1, data: {} }).length, 1,
    'BINA_TIMELINE_VERBOSE brings the plumbing back')
  const late = project(t, { type: 'turn/end', seq: 2, time: 99, data: { turn: 4, reason: { kind: 'completed' } } })
  assert.equal(late.length, 1)
  assert.equal(late[0].s, 99, 'no invented start: the projection was not watching when it began')
  assert.equal(late[0].e, 99)
})

test('a subagent session gets its own row, and disposal closes what is open', () => {
  const t = createTrack(sessionInfo(subagent))
  const rows = project(t, { type: 'step/start', seq: 1, time: 10, data: { turn: 1, step: 1 } })
  assert.match(rows[0].svc, /^תת-סוכן /)
  assert.equal(rows[0].meta.parent_session, session.id)
  const closed = closeAll(t, 50)
  assert.equal(closed[0].status, 'canceled')
  assert.equal(closed[0].e, 50)
})

test('the ledger folds a span by id and answers both questions', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'bina-timeline-'))
  try {
    const ledger = new Ledger({ dir, keepDays: 14 })
    await ledger.start()
    const t = track()
    ledger.write(project(t, { type: 'turn/start', seq: 1, time: 1000, data: { turn: 1 } }), 1000)
    ledger.write(project(t, { type: 'turn/end', seq: 2, time: 3000, data: { turn: 1, reason: { kind: 'completed' } } }), 3000)
    ledger.write(project(t, { type: 'someplugin/whatever', seq: 3, time: 4000, data: {} }), 4000)
    await ledger.flush()

    const window = await readSpans({ dir, hours: 24, now: 10_000 })
    assert.equal(window.spans.length, 2, 'the turn is one span with its final state, plus the instant')
    const turn = window.spans.find((s) => s.id.endsWith(':turn:1'))
    assert.equal(turn.status, 'success')
    assert.equal(turn.e, 3000)
    assert.equal(turn.s, 1000)

    const delta = await readSpans({ dir, since: 3500, now: 10_000 })
    assert.equal(delta.spans.length, 1, 'only what moved after the cursor')

    const status = await ledgerStatus(dir)
    assert.equal(status.available, true)
    assert.ok(status.bytes > 0)

    // Rotation: a span whose open landed in one hour file and whose close in the NEXT still folds
    // to one span, and the legacy day-file naming is read alongside the hour files.
    const HOUR = 3600 * 1000
    const base = Date.UTC(2026, 8, 30, 10, 59, 30)
    ledger.write([{ id: 'rot:1', svc: 'row', svcid: 'row', label: 'נפתח', status: 'running', s: base, e: null, meta: {} }], base)
    ledger.write([{ id: 'rot:1', svc: 'row', svcid: 'row', label: 'נסגר', status: 'success', s: base, e: base + 90_000, meta: {} }], base + 90_000)
    await ledger.flush()
    const rot = await readSpans({ dir, hours: 48, now: base + 5 * HOUR })
    const span = rot.spans.find((x) => x.id === 'rot:1')
    assert.ok(span, 'a span spanning two hour files is served once')
    assert.equal(span.status, 'success')
    assert.equal(span.e, base + 90_000)

    // The reader is incremental: a second append must be picked up WITHOUT re-parsing the file,
    // and a span re-emitted must fold onto its previous version rather than duplicate.
    ledger.write(project(t, { type: 'tool/call', seq: 5, time: 6000, data: { callId: 'c1', name: 'bash', arguments: '{"command":"ls"}' } }), 6000)
    await ledger.flush()
    const grown = await readSpans({ dir, hours: 24, now: 10_000 })
    assert.equal(grown.spans.length, 3, 'the appended tool call joined the same fold')
    ledger.write(project(t, { type: 'tool/result', seq: 6, time: 7000, data: { callId: 'c1', message: { content: [{ isError: false }] } } }), 7000)
    await ledger.flush()
    const closed = await readSpans({ dir, since: 6500, now: 10_000 })
    assert.equal(closed.spans.length, 1)
    assert.equal(closed.spans[0].status, 'success', 'the delta read folded the close onto the open row')
    assert.equal(closed.spans[0].e, 7000)

    // A span left open by a process that is gone must not stay "running" for ever.
    const orphan = new Ledger({ dir })
    await orphan.start()
    orphan.write(project(t, { type: 'step/start', seq: 4, time: 5000, data: { turn: 2, step: 1 } }), 5000)
    await orphan.flush()
    const later = await readSpans({ dir, hours: 24, now: 5000 + 13 * 3600 * 1000 })
    const stale = later.spans.find((s) => s.status === 'crashed')
    assert.ok(stale, 'the orphaned step is reported as crashed, not as still running')
    assert.equal(stale.e, 5000, 'it ends at the last moment anything was written about it')
    const fresh = await readSpans({ dir, hours: 24, now: 5000 + 60_000 })
    assert.equal(fresh.spans.find((s) => s.id === stale.id).status, 'running', 'a live span is left alone')
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
})
