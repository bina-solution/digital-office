/**
 * The vault source's own rules, tested without a vault: what a stored value means, what one lease's
 * environment yields for a reference, and how long a lease is reused. The harness-side behaviour
 * (`resolve`/`describe`) is a thin layer over these, and the app's acceptance run
 * (`/tmp/vault-key-acceptance.mjs` in the built image) exercises the real service.
 *
 *   node --test apps/bina-ds/plugins/vault-key/test/
 */

import test from 'node:test'
import assert from 'node:assert/strict'

import { VaultSource, isPlaceholder, secretFrom, vaultBindingFor, vaultConnectionOf } from '../lib/vault.mjs'

test('a literal key is not a binding', () => {
  assert.equal(vaultConnectionOf('sk-ebea1234'), undefined)
  assert.equal(vaultConnectionOf(''), undefined)
  assert.equal(vaultConnectionOf(undefined), undefined)
  assert.equal(vaultConnectionOf(42), undefined)
})

test('a binding names one connection and nothing else', () => {
  assert.equal(vaultConnectionOf('vault:deepseek-key'), 'deepseek-key')
  assert.equal(vaultConnectionOf('  vault:n8n-postgres '), undefined, 'whitespace is not a binding')
  assert.equal(vaultConnectionOf('vault:'), undefined)
  assert.equal(vaultConnectionOf('vault:DeepSeek'), undefined, 'connection ids are lowercase')
  assert.equal(vaultConnectionOf('vault:../etc/passwd'), undefined, 'a binding cannot be a path')
  assert.equal(vaultBindingFor('deepseek-key'), 'vault:deepseek-key')
  assert.throws(() => vaultBindingFor('not a connection'), TypeError)
})

test('a lease yields the value the reference names', () => {
  assert.equal(secretFrom({ DEEPSEEK_API_KEY: 'sk-1' }, 'DEEPSEEK_API_KEY'), 'sk-1')
  assert.equal(secretFrom({ OTHER: 'x' }, 'DEEPSEEK_API_KEY'), 'x', 'one field answers any reference')
  assert.equal(secretFrom({ A: 'x', B: 'y' }, 'A'), 'x')
  assert.equal(secretFrom({ A: 'x', B: 'y' }, 'C'), undefined, 'two fields and no match = no answer')
  assert.equal(secretFrom({ DEEPSEEK_API_KEY: '' }, 'DEEPSEEK_API_KEY'), undefined, 'an empty value is absent')
  assert.equal(secretFrom({}, 'DEEPSEEK_API_KEY'), undefined)
  assert.equal(secretFrom(undefined, 'DEEPSEEK_API_KEY'), undefined)
})

/** A VaultSource whose transport is a test double. */
function source(answers, { cacheSeconds = 30 } = {}) {
  const calls = []
  const vault = new VaultSource({ url: 'http://vault.test', service: 'bina-ds', cacheSeconds, timeoutMs: 500 })
  vault.fetchLease = async (connection) => {
    calls.push(connection)
    const answer = typeof answers === 'function' ? answers(connection, calls.length) : answers
    return answer
  }
  return { vault, calls }
}

test('a lease is reused for its lifetime, and asked again after it', async () => {
  const { vault, calls } = source({ ok: true, env: { DEEPSEEK_API_KEY: 'sk-1' } }, { cacheSeconds: 0 })
  assert.equal(await vault.secret('DEEPSEEK_API_KEY', 'deepseek-key'), 'sk-1')
  assert.deepEqual(calls, ['deepseek-key'])
  // cacheSeconds 0 means the next read is a new lease — a rotation reaches the next request.
  assert.equal(await vault.secret('DEEPSEEK_API_KEY', 'deepseek-key'), 'sk-1')
  assert.deepEqual(calls, ['deepseek-key', 'deepseek-key'])
})

test('a cached lease serves the second read without touching the vault', async () => {
  const { vault, calls } = source({ ok: true, env: { DEEPSEEK_API_KEY: 'sk-1' } })
  await vault.secret('DEEPSEEK_API_KEY', 'deepseek-key')
  await vault.secret('DEEPSEEK_API_KEY', 'deepseek-key')
  assert.deepEqual(calls, ['deepseek-key'])
})

test('a refused lease is an error, not "no key"', async () => {
  const reason = "'deepseek-key' is not in bina-ds's declared connections[]"
  const { vault } = source({ ok: false, reason })
  await assert.rejects(() => vault.secret('DEEPSEEK_API_KEY', 'deepseek-key'), /could not be read.*not in bina-ds/u)
  const state = await vault.state('deepseek-key')
  assert.equal(state.configured, false)
  assert.equal(state.reason, reason, 'the refusal the vault gave is kept, verbatim')
})

test('an empty connection reads as unconfigured and says nothing else', async () => {
  const { vault } = source({ ok: true, env: {} })
  assert.equal(await vault.secret('DEEPSEEK_API_KEY', 'deepseek-key'), undefined)
  assert.equal((await vault.state('deepseek-key')).configured, false)
})

test('concurrent reads share one lease', async () => {
  const { vault, calls } = source({ ok: true, env: { DEEPSEEK_API_KEY: 'sk-1' } })
  await Promise.all([
    vault.secret('DEEPSEEK_API_KEY', 'deepseek-key'),
    vault.secret('DEEPSEEK_API_KEY', 'deepseek-key'),
    vault.secret('DEEPSEEK_API_KEY', 'deepseek-key'),
  ])
  assert.deepEqual(calls, ['deepseek-key'])
})


test('a fill-me-in value is not a key', () => {
  assert.equal(secretFrom({ DEEPSEEK_API_KEY: 'sk-your-deepseek-api-key' }, 'DEEPSEEK_API_KEY'), undefined)
  assert.equal(secretFrom({ DEEPSEEK_API_KEY: 'change_me' }, 'DEEPSEEK_API_KEY'), undefined)
  assert.equal(secretFrom({ A: 'xxx', B: 'sk-real' }, 'A'), 'sk-real', 'the placeholder is skipped, not chosen')
  assert.equal(isPlaceholder('your-openai-key'), true)
  assert.equal(isPlaceholder('sk-REDACTED'), false)
})

test('a connection holding only a placeholder reads as unconfigured', async () => {
  const { vault } = source({ ok: true, env: { DEEPSEEK_API_KEY: 'sk-your-deepseek-api-key' } })
  assert.deepEqual(await vault.state('deepseek-key'), { configured: false })
  assert.equal(await vault.secret('DEEPSEEK_API_KEY', 'deepseek-key'), undefined)
})
