// office-links — a link to the office, clicked inside the agent's own page, tested against the
// module the browser really loads (lib/client.js), in a fake page: a window, a document, a location
// and the loader the harness calls. Nothing here re-implements the plugin; the assertions are about
// what it DOES — which links it claims, and that it moves the TOP window (the desktop) rather than
// letting the harness's `target="_blank"` open a tab.
//
// Two reasons this file exists, both from 2026-10-13 (ui2-060):
//   • the plugin was right and loaded nowhere: inside the console tile the harness's client bundles
//     are addressed from the ROOT (`/plugins/??…`), the console's catch-all answered them with
//     index.html, and every plugin — this one among them — silently did not load. The console now
//     forwards such a path to the app whose page asked for it;
//   • the usual link is to the office the person is ALREADY in (the agent writes links to its own
//     office), and a link with this page's own origin was skipped as "the harness's routing" — so
//     the harness's `target="_blank"` opened a new tab for a link to the office in front of them.
//
// The live half of the proof is the office's own browser; this suite is what runs on every change:
//   node --test apps/bina-ds/plugins/office-links/test/client.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const CLIENT = path.join(HERE, '..', 'lib', 'client.js')

/** Load lib/client.js as the browser does, with one fake page under it, and return its module. */
async function load({ hostname, origin, referrer = '', ancestors = [] }) {
  const listeners = new Map()
  let loaded = null
  const top = { location: { href: origin + '/' } }
  const window = {
    location: { hostname, origin, href: origin + '/', ancestorOrigins: ancestors },
    top,
    addEventListener: (type, fn) => listeners.set(type, fn),
    removeEventListener: (type) => listeners.delete(type),
    __ModuleLoader__: { load: ({ factory }) => { loaded = factory() } },
  }
  const document = { referrer, addEventListener: () => {}, removeEventListener: () => {} }
  globalThis.window = window
  globalThis.location = window.location
  globalThis.document = document
  await import(pathToFileURL(CLIENT).href + '?v=' + Math.random())
  loaded.apply({ effect: (fn) => { fn(); return () => {} } })
  return { top, page: window.location, click: (ev) => listeners.get('click')(ev) }
}

/** A click on one anchor, as the plugin sees it: a target that can find its own `a[href]`. */
function clickOn(href, { metaKey = false, ctrlKey = false, button = 0 } = {}) {
  const anchor = { href, closest: (sel) => (sel === 'a[href]' ? anchor : null) }
  return {
    target: anchor, button, metaKey, ctrlKey, shiftKey: false, altKey: false,
    defaultPrevented: false, stopped: false,
    preventDefault() { this.defaultPrevented = true },
    stopPropagation() { this.stopped = true },
  }
}

const OFFICE = { hostname: 'console.staging.digital-office.co.il', origin: 'https://console.staging.digital-office.co.il' }
const EMBED = OFFICE.origin + '/a/bina/'

test('the office\'s OWN console route is claimed — this is the link the agent posts', async () => {
  const p = await load({ ...OFFICE, referrer: EMBED, ancestors: [OFFICE.origin] })
  const ev = clickOn(OFFICE.origin + '/#/m/project-pln/projects/7/issues/9')
  p.click(ev)
  assert.equal(ev.defaultPrevented, true, 'a new tab here is the owner\'s complaint')
  assert.equal(ev.stopped, true, 'the harness draws its own handler on the link — the click must stop here')
  assert.equal(p.top.location.href, OFFICE.origin + '/#/m/project-pln/projects/7/issues/9',
    'the TOP window (the desktop) is what moves — the desktop opens the window, no tab')
})

test('a console reached by a name with NO SUFFIX is still the office in front of the person', async () => {
  // inside the office network the console answers on `console:8000`; the hostname rules cannot match
  // a name with no suffix, and the link is still a route of the console this page is embedded in.
  const bare = { hostname: 'console', origin: 'http://console:8000' }
  const p = await load({ ...bare, referrer: bare.origin + '/a/bina/', ancestors: [bare.origin] })
  const ev = clickOn(bare.origin + '/#/m/machine')
  p.click(ev)
  assert.equal(ev.defaultPrevented, true)
  assert.equal(p.top.location.href, bare.origin + '/#/m/machine')
})

test('a sibling office\'s console route is claimed and moved to THIS console', async () => {
  // the page is embedded in the READER's console (that is what `ancestorOrigins` says), and the link
  // was written by the office that owns the work item — a sibling of this one.
  const p = await load({ ...OFFICE, referrer: EMBED, ancestors: [OFFICE.origin] })
  const ev = clickOn('https://console.hp-laptop.staging.digital-office.co.il/#/m/project-pln/projects/7')
  p.click(ev)
  assert.equal(ev.defaultPrevented, true)
  assert.equal(p.top.location.href, OFFICE.origin + '/#/m/project-pln/projects/7',
    'the office in front of the person is the one that changes route')
})

test('a `*.localhost` office is an office', async () => {
  const p = await load({ hostname: 'bina.localhost', origin: 'http://bina.localhost:8080', referrer: 'http://console.localhost:8080/a/bina/', ancestors: ['http://console.localhost:8080'] })
  const ev = clickOn('http://console.localhost:8080/#/m/drive/trash')
  p.click(ev)
  assert.equal(ev.defaultPrevented, true)
  assert.equal(p.top.location.href, 'http://console.localhost:8080/#/m/drive/trash')
})

test('the harness\'s own paths are its routing, not ours', async () => {
  const p = await load({ ...OFFICE, referrer: EMBED, ancestors: [OFFICE.origin] })
  const ev = clickOn(OFFICE.origin + '/a/bina/#/m/drive/trash')
  p.click(ev)
  assert.equal(ev.defaultPrevented, false)
  assert.equal(p.top.location.href, OFFICE.origin + '/')
})

test('a link that is not the office is left exactly as the harness drew it', async () => {
  const p = await load({ ...OFFICE, referrer: EMBED, ancestors: [OFFICE.origin] })
  const ev = clickOn('https://example.com/article')
  p.click(ev)
  assert.equal(ev.defaultPrevented, false, 'a source on the web is not ours to take')
  assert.equal(p.top.location.href, OFFICE.origin + '/')
})

test('an office on another domain is left alone (the naming rule, said rather than assumed)', async () => {
  const p = await load({ ...OFFICE, referrer: EMBED, ancestors: [OFFICE.origin] })
  const ev = clickOn('https://console.other-office.co.il/#/m/project-pln/projects/7')
  p.click(ev)
  assert.equal(ev.defaultPrevented, false, 'offices are named as siblings under one suffix, or *.localhost')
})

test('a click the person made into a new tab on purpose is not taken', async () => {
  const p = await load({ ...OFFICE, referrer: EMBED, ancestors: [OFFICE.origin] })
  for (const mod of [{ metaKey: true }, { ctrlKey: true }]) {
    const ev = clickOn(OFFICE.origin + '/#/m/drive/trash', mod)
    p.click(ev)
    assert.equal(ev.defaultPrevented, false)
    assert.equal(p.top.location.href, OFFICE.origin + '/')
  }
})
