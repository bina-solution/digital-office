import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import { apply, inject, name } from '../lib/index.js'

/** A context with just the three services the plugin injects, wired by hand. */
function makeCtx({ goal, blockThrows = false, editThrows = false } = {}) {
  const handlers = new Map()
  const blocked = []
  const edited = []
  const state = { goal }
  const agent = { id: 'agent-1', session: { id: 'session-1' } }
  const ctx = {
    logger: { warnings: [], warn(line) { this.warnings.push(line) } },
    agents: { get: (id) => (id === 'session-1' || id === 'agent-1' ? agent : undefined) },
    goals: {
      get: () => state.goal,
      block: (_agent, ref, reason) => {
        if (blockThrows) throw new Error('registry said no')
        blocked.push({ ref, reason })
        state.goal = { ...state.goal, phase: 'blocked', blockedReason: reason }
      },
      edit: (_agent, ref, request) => {
        if (editThrows) throw new Error('registry said no')
        edited.push({ ref, request })
        state.goal = { ...state.goal, revision: ref.revision + 1, ...request }
      },
    },
    on: (event, handler) => {
      const list = handlers.get(event) ?? []
      list.push(handler)
      handlers.set(event, list)
    },
    effect: (generator) => {
      const iterator = generator()
      iterator.next()
    },
  }
  apply(ctx, { maxGoalRounds: 12 })
  const emit = (event, ...args) => {
    for (const handler of handlers.get(event) ?? []) handler(...args)
  }
  const session = { id: 'session-1' }
  return { ctx, agent, state, blocked, edited, emit, session, handlers }
}

/** One automatic goal round: start, admit the round message, then whatever it did, then end. */
function round(ctx, { goalId = 'goal-1', revision = 1, round: n = 1, toolCalls = 0 } = {}) {
  const { emit, session } = ctx
  emit('session/event', session, { type: 'turn/start', data: {} })
  emit('session/event', session, {
    type: 'user/message',
    data: { source: { kind: 'goal', goalId, revision, round: n } },
  })
  for (let i = 0; i < toolCalls; i += 1) {
    emit('session/event', session, { type: 'tool/call', data: { name: 'bash' } })
  }
  emit('session/event', session, { type: 'turn/end', data: { reason: { kind: 'stop' } } })
}

const activeGoal = (over = {}) => ({
  id: 'goal-1',
  revision: 1,
  phase: 'active',
  activation: 'armed',
  maxGoalRounds: 12,
  roundsStarted: 3,
  ...over,
})

test('a goal round that made no tool call gets no next round', () => {
  const ctx = makeCtx({ goal: activeGoal() })
  round(ctx)
  assert.equal(ctx.blocked.length, 1)
  assert.equal(ctx.blocked[0].reason.code, 'no-progress')
  assert.match(ctx.blocked[0].reason.message, /בלי אף קריאת כלי/)
  assert.deepEqual(ctx.blocked[0].ref, { id: 'goal-1', revision: 1 })
})

test('a goal round that did work continues', () => {
  const ctx = makeCtx({ goal: activeGoal() })
  round(ctx, { toolCalls: 1 })
  assert.equal(ctx.blocked.length, 0)
})

test('a human turn with no tool call is left alone', () => {
  const ctx = makeCtx({ goal: activeGoal() })
  const { emit, session } = ctx
  emit('session/event', session, { type: 'turn/start', data: {} })
  emit('session/event', session, { type: 'user/message', data: { source: { kind: 'user' } } })
  emit('session/event', session, { type: 'turn/end', data: { reason: { kind: 'stop' } } })
  assert.equal(ctx.blocked.length, 0)
})

test('a stale round of another revision cannot block the live goal', () => {
  const ctx = makeCtx({ goal: activeGoal({ revision: 7 }) })
  round(ctx, { revision: 6 })
  assert.equal(ctx.blocked.length, 0)
})

test('an already terminal goal is never blocked again', () => {
  const ctx = makeCtx({ goal: activeGoal({ phase: 'blocked' }) })
  round(ctx)
  assert.equal(ctx.blocked.length, 0)
})

test('a goal asking 400 rounds is clamped to the office ceiling', () => {
  const ctx = makeCtx({ goal: activeGoal({ maxGoalRounds: 400 }) })
  ctx.emit('goal/changed', { agent: ctx.agent, change: { operation: 'create' } })
  assert.equal(ctx.edited.length, 1)
  assert.deepEqual(ctx.edited[0].request, { maxGoalRounds: 12 })
})

test('a goal inside the ceiling is not edited', () => {
  const ctx = makeCtx({ goal: activeGoal({ maxGoalRounds: 12 }) })
  ctx.emit('goal/changed', { agent: ctx.agent, change: { operation: 'create' } })
  assert.equal(ctx.edited.length, 0)
})

test('a completed goal is not edited', () => {
  const ctx = makeCtx({ goal: activeGoal({ phase: 'complete', maxGoalRounds: 400 }) })
  ctx.emit('goal/changed', { agent: ctx.agent, change: { operation: 'edit' } })
  assert.equal(ctx.edited.length, 0)
})

test('a registry that refuses is a warning, never a throw on the turn path', () => {
  const ctx = makeCtx({ goal: activeGoal(), blockThrows: true })
  assert.doesNotThrow(() => round(ctx))
  assert.ok(ctx.ctx.logger.warnings.some((line) => line.includes('could not block')))
})

test('a refused clamp is a warning, never a throw', () => {
  const ctx = makeCtx({ goal: activeGoal({ maxGoalRounds: 400 }), editThrows: true })
  assert.doesNotThrow(() =>
    ctx.emit('goal/changed', { agent: ctx.agent, change: { operation: 'create' } }),
  )
  assert.ok(ctx.ctx.logger.warnings.some((line) => line.includes('could not clamp')))
})

test('the plugin names the services it needs', () => {
  assert.deepEqual(inject, ['agents', 'goals'])
  assert.equal(name, '@bina/dsh-goal-guard')
})
