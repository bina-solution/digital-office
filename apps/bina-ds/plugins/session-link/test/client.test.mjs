// session-link — the two directions of the office's embed-route contract, tested against the module
// the browser really loads (lib/client.js), in a fake page: a module loader, a location, a history
// and a parent frame. Nothing here re-implements the plugin; the assertions are about what the
// plugin DOES with the harness's `sessions` service, which is the half that can be wrong silently.
//
// The real browser half of the proof is the live console (see the work item): this suite is what
// runs on every change, the office included.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const CLIENT = path.join(HERE, '..', 'lib', 'client.js')
const MANIFEST = path.join(HERE, '..', 'package.json')
let generation = 0

/** The harness's session list, as the plugin sees it: a snapshot store with a phase and a current. */
function listStore({ ids = [], current, phase = 'pending' } = {}) {
  let snapshot = { ids, byId: Object.fromEntries(ids.map((id) => [id, { id }])), current, phase }
  const listeners = new Set()
  return {
    getSnapshot: () => snapshot,
    subscribe: (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    /** A host frame: a new snapshot, then every subscriber. */
    publish(next) {
      snapshot = { ...snapshot, ...next }
      for (const listener of [...listeners]) listener()
    },
  }
}

/** A page: what the plugin reads (location) and what it writes (history, the parent frame). */
function page({ url = 'http://console.localhost:8080/a/bina/', embedded = true } = {}) {
  const messages = []
  const replaceState = []
  const parent = embedded
    ? { postMessage: (message, origin) => messages.push({ message, origin }) }
    : undefined
  const location = { href: url, origin: new URL(url).origin }
  return {
    messages,
    replaceState,
    global() {
      globalThis.location = location
      globalThis.parent = embedded ? parent : globalThis
      globalThis.history = { replaceState: (state, title, href) => replaceState.push(href) }
    },
  }
}

/** Load lib/client.js the way the browser does, and hand back the plugin it registers. */
async function plugin() {
  const registrations = []
  globalThis.window = { __ModuleLoader__: { load: (registration) => registrations.push(registration) } }
  generation += 1
  await import(`${CLIENT}?generation=${generation}`)
  const [registration] = registrations
  assert.equal(registration.id, '@bina/dsh-client-session-link')
  return registration.factory(() => {
    throw new Error('the plugin must not require anything: it uses the services it declares')
  })
}

/** Apply the plugin to one fake client context and hand back what it did. */
async function mount(options) {
  const harness = page(options)
  harness.global()
  const store = listStore(options)
  const opened = []
  const disposers = []
  const sessions = {
    list: store,
    open(id) {
      if (store.getSnapshot().ids.indexOf(id) < 0) throw new Error(`unknown session ${id}`)
      opened.push(id)
      store.publish({ current: id })
    },
  }
  const ctx = {
    sessions,
    effect: (fn) => {
      disposers.push(fn())
    },
  }
  const loaded = await plugin()
  assert.deepEqual(loaded.inject, ['sessions'])
  loaded.apply(ctx)
  return { store, opened, harness, dispose: () => disposers.forEach((fn) => fn()) }
}

test('an arriving id is opened once, and the page names it in its own URL', async () => {
  const m = await mount({ ids: ['session-a', 'session-b'], current: 'session-a', phase: 'ready', url: 'http://console.localhost:8080/a/bina/?s=session-b' })
  assert.deepEqual(m.opened, ['session-b'])
  // The URL it was opened with already says it: nothing to rewrite…
  assert.deepEqual(m.harness.replaceState, [])
  // …and nothing is POSTED anywhere: the shell reads this page's URL itself (that is the point of
  // the shrink — one writer of one fact).
  assert.deepEqual(m.harness.messages, [])
})

test('nothing is opened and nothing is written before the first successful pull', async () => {
  const m = await mount({ ids: ['session-b'], phase: 'pending', url: 'http://console.localhost:8080/a/bina/?s=session-b' })
  assert.deepEqual(m.opened, [])
  assert.deepEqual(m.harness.replaceState, [])
  // …and the ask still lands when the list arrives, without being asked twice.
  m.store.publish({ phase: 'ready' })
  assert.deepEqual(m.opened, ['session-b'])
  assert.deepEqual(m.harness.messages, [])
})

test('an ask is answered against the first complete list and never re-armed', async () => {
  // The id is not in the pull (it was archived, or never existed): the reader keeps what is open,
  // and a later live increment that happens to carry the id does not yank the screen.
  const m = await mount({ ids: [], phase: 'ready', current: undefined, url: 'http://console.localhost:8080/a/bina/?s=session-a' })
  assert.deepEqual(m.harness.replaceState, ['http://console.localhost:8080/a/bina/'])
  m.store.publish({ ids: ['session-a'] })
  assert.deepEqual(m.opened, [])
  assert.deepEqual(m.harness.replaceState, ['http://console.localhost:8080/a/bina/'])
})

test('an id the list does not carry never opens, and the reader keeps the conversation that was open', async () => {
  const m = await mount({ ids: ['session-a'], current: 'session-a', phase: 'ready', url: 'http://console.localhost:8080/a/bina/?s=session-gone' })
  assert.deepEqual(m.opened, [])
  assert.deepEqual(m.harness.replaceState, ['http://console.localhost:8080/a/bina/?s=session-a'])
})

test('every change of the open conversation is written once, and no route twice', async () => {
  const m = await mount({ ids: ['session-a', 'session-b'], current: 'session-a', phase: 'ready' })
  assert.deepEqual(m.harness.replaceState, ['http://console.localhost:8080/a/bina/?s=session-a'])
  m.store.publish({ current: 'session-b' })
  m.store.publish({ current: 'session-b' })
  m.store.publish({ current: 'session-a' })
  assert.deepEqual(m.harness.replaceState, ['http://console.localhost:8080/a/bina/?s=session-a',
                                            'http://console.localhost:8080/a/bina/?s=session-b',
                                            'http://console.localhost:8080/a/bina/?s=session-a'])
  assert.deepEqual(m.harness.messages, [])
})

test('an id the list carries IS opened, and the reader lands on it rather than on "nothing open"', async () => {
  const m = await mount({ ids: ['session-a'], phase: 'ready', url: 'http://console.localhost:8080/a/bina/?s=session-a' })
  assert.deepEqual(m.opened, ['session-a'])
  assert.deepEqual(m.harness.replaceState, [])
  assert.deepEqual(m.harness.messages, [])
})

test('no conversation at all is the shell route "/", and the page\'s own query is cleared', async () => {
  const m = await mount({ ids: ['session-a'], phase: 'ready', current: undefined, url: 'http://console.localhost:8080/a/bina/?token=xyz' })
  assert.deepEqual(m.harness.replaceState, ['http://console.localhost:8080/a/bina/'])
})

test('a page with no query writes the open conversation into its own address bar', async () => {
  const m = await mount({ ids: ['session-a'], phase: 'ready', url: 'http://console.localhost:8080/a/bina/' })
  // Boot: the list is complete and nothing is open — the page's own URL says so.
  assert.deepEqual(m.harness.replaceState, [])
  m.store.publish({ current: 'session-a' })
  assert.deepEqual(m.harness.replaceState, ['http://console.localhost:8080/a/bina/?s=session-a'])
  assert.deepEqual(m.harness.messages, [])
})

test('a page that stands alone still names its own conversation', async () => {
  const m = await mount({ ids: ['session-a'], current: 'session-a', phase: 'ready', url: 'https://bina.localhost:8080/', embedded: false })
  assert.deepEqual(m.harness.messages, [])
  assert.deepEqual(m.harness.replaceState, ['https://bina.localhost:8080/?s=session-a'])
})

test('the reader is the query `s`, and an empty one is no ask at all', async () => {
  const empty = await mount({ ids: ['session-a'], current: 'session-a', phase: 'ready', url: 'http://console.localhost:8080/a/bina/?s=' })
  assert.deepEqual(empty.opened, [])
  const other = await mount({ ids: ['session-a'], current: 'session-a', phase: 'ready', url: 'http://console.localhost:8080/a/bina/?token=xyz' })
  assert.deepEqual(other.opened, [])
  assert.deepEqual(other.harness.replaceState, ['http://console.localhost:8080/a/bina/?s=session-a'])
})

test('teardown unsubscribes: a disposed plugin is silent', async () => {
  const m = await mount({ ids: ['session-a'], current: 'session-a', phase: 'ready' })
  const seen = m.harness.messages.length
  m.dispose()
  m.store.publish({ current: undefined })
  assert.equal(m.harness.messages.length, seen)
})

test('the plugin declares the session controller as its load-order dependency', async () => {
  const manifest = JSON.parse(await readFile(MANIFEST, 'utf8'))
  assert.equal(manifest.dsh.client.platform, 'web')
  assert.deepEqual(manifest.dsh.client.inject, ['@deepseek-ai/dsh-api-session-controller'])
  assert.equal(manifest.exports['./client'], './lib/client.js')
})
