/**
 * office-shell-env's own rules, tested with a stand-in registry: what it declares, what an agent's shell call
 * receives, and that nothing else crosses the harness's scrub.
 *
 *   node --test apps/bina-ds/plugins/office-shell-env/test/
 */

import test from 'node:test'
import assert from 'node:assert/strict'

import { FORWARDED, apply, inject, name, values } from '../lib/index.js'

function registered(env) {
  const saved = { ...process.env }
  Object.assign(process.env, env)
  const calls = []
  apply({ shellEnv: { register: (c) => calls.push(c) } })
  return { calls, restore: () => { for (const k of Object.keys(process.env)) if (!(k in saved)) delete process.env[k]; Object.assign(process.env, saved) } }
}

test('it is a shell-env contributor, by name', () => {
  assert.equal(name, '@bina/dsh-office-shell-env')
  assert.deepEqual(inject, ['shellEnv'])
})

test('it declares exactly the two scoped tokens, each from the container variable of that name', () => {
  assert.deepEqual(Object.keys(FORWARDED).sort(), ['DSH_CHAT_READ_TOKEN', 'DSH_COMPUTERS_EXEC_TOKEN'])
  assert.equal(FORWARDED.DSH_CHAT_READ_TOKEN.from, 'CHAT_READ_TOKEN')
  assert.equal(FORWARDED.DSH_COMPUTERS_EXEC_TOKEN.from, 'COMPUTERS_EXEC_TOKEN')
  for (const key of Object.keys(FORWARDED)) assert.match(key, /^DSH_[A-Z0-9_]+$/)
  assert.ok(!Object.values(FORWARDED).some((v) => v.from === 'CHAT_API_TOKEN'), "never chat's token that opens every route")
})

test("an agent's shell call gets the set values; a harness call, and an unset or blank value, get nothing", () => {
  const { calls, restore } = registered({ CHAT_READ_TOKEN: 'r-1', COMPUTERS_EXEC_TOKEN: '  ', CHAT_API_TOKEN: 'full-2' })
  try {
    assert.equal(calls.length, 1)
    const c = calls[0]
    assert.equal(c.name, 'bina:office-service-tokens')
    assert.deepEqual(Object.keys(c.variables).sort(), ['DSH_CHAT_READ_TOKEN', 'DSH_COMPUTERS_EXEC_TOKEN'])
    for (const v of Object.values(c.variables)) assert.ok(typeof v.description === 'string' && v.description.length > 10)
    assert.deepEqual(c.resolve({ agent: { id: 'azaria' } }), { DSH_CHAT_READ_TOKEN: 'r-1' })
    assert.deepEqual(c.resolve({}), {})
    assert.deepEqual(c.resolve(undefined), {})
  } finally {
    restore()
  }
})

test('values() hands on only declared names, whatever else the environment holds', () => {
  const out = values({ CHAT_READ_TOKEN: 'a', COMPUTERS_EXEC_TOKEN: 'b', CHAT_API_TOKEN: 'c', DEEPSEEK_API_KEY: 'd' })
  assert.deepEqual(out, { DSH_CHAT_READ_TOKEN: 'a', DSH_COMPUTERS_EXEC_TOKEN: 'b' })
  assert.deepEqual(values({}), {})
})
