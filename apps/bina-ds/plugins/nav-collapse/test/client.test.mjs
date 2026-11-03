// nav-collapse — the fold-away state of the agent's own navigation, tested against the module the
// browser really loads (lib/client.js), in a fake page: a document, a root element, a body, storage
// and a MutationObserver. Nothing here re-implements the plugin; the assertions are about what it
// DOES — which attribute it sets, what it persists, when it refuses to act, and that its stylesheet
// names the harness's columns by their readable suffixes.
//
// The live half of the proof is the console and the app itself; this suite is what runs on every
// change.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const CLIENT = path.join(HERE, '..', 'lib', 'client.js')

/** One element: as much of it as the plugin touches. */
function element(tag) {
  const attrs = new Map()
  const listeners = new Map()
  const kids = []
  const el = {
    tagName: String(tag).toUpperCase(),
    id: '', title: '', textContent: '', className: '', type: '', innerHTML: '',
    style: {
      props: new Map(),
      setProperty(name, value) { this.props.set(name, String(value)) },
      getPropertyValue(name) { return this.props.has(name) ? this.props.get(name) : '' },
      gridTemplateColumns: '',
    },
    children: kids, parentNode: null, previousSibling: null,
    removed: false,
    remove() { this.removed = true; if (this.parentNode) this.parentNode.children.splice(this.parentNode.children.indexOf(this), 1) },
    appendChild(child) { spill(child, this); return child },
    insertBefore(child, ref) { spill(child, this); kids.splice(Math.max(0, kids.indexOf(ref)), 0, child); return child },
    querySelector(sel) {
      // `[class*="token"]` is the form the component matches CSS-module suffixes with; a plain class
      // name is the other. The stub answers both, so the placement rule can be tested as written.
      const attr = String(sel).match(/\[class\*="([^"]+)"\]/)
      const tag = /^[a-z]+$/.test(String(sel))
      const want = attr ? attr[1] : String(sel).replace(/^[a-z]*/, "").replace(/^\./, "")
      const hit = (c) => attr ? String(c.className).includes(want)
                  : tag ? c.tagName === String(sel).toUpperCase()
                  : String(c.className).split(/\s+/).includes(want)
      const walk = (n) => { for (const c of n.children) { if (hit(c)) return c; const deeper = walk(c); if (deeper) return deeper } return null }
      return walk(this)
    },
    closest(sel) {
      const wants = String(sel).split(",").map((x) => x.trim().replace(/^[a-z]*\[class\*="/, "").replace(/"\]$/, ""))
      let node = this
      while (node) {
        const classes = String(node.className || "").split(/\s+/)
        if (wants.some((w) => w && classes.some((c) => c.includes(w)))) return node
        node = node.parentNode
      }
      return null
    },
    setAttribute(name, value) { attrs.set(name, String(value)) },
    getAttribute(name) { return attrs.has(name) ? attrs.get(name) : null },
    hasAttribute(name) { return attrs.has(name) },
    removeAttribute(name) { attrs.delete(name) },
    get parentElement() { return this.parentNode },
    get firstChild() { return this.children[0] || null },
    get firstElementChild() { return this.children[0] || null },
    toggleAttribute(name, on) {
      const want = on === undefined ? !attrs.has(name) : Boolean(on)
      if (want) attrs.set(name, '')
      else attrs.delete(name)
      return want
    },
    addEventListener(type, fn) {
      if (!listeners.has(type)) listeners.set(type, [])
      listeners.get(type).push(fn)
    },
    removeEventListener(type, fn) {
      const list = listeners.get(type) || []
      const at = list.indexOf(fn)
      if (at >= 0) list.splice(at, 1)
    },
    dispatch(type, event = {}) {
      let seen = false
      for (const fn of listeners.get(type) || []) { seen = true; fn({ preventDefault() {}, ...event }) }
      return seen
    },
  }
  return el
}

/** Adopt a child: remember who its parent is (the plugin walks up, and inserts a sibling). */
function spill(child, parent) {
  child.parentNode = parent
  child.previousSibling = parent.children.length ? parent.children[parent.children.length - 1] : null
  parent.children.push(child)
  return parent
}

/** A page: what the plugin reads (document, storage) and what it writes (the root's attributes). */
function page({ stored = null, shellFocused = false, withBody = true, width = 1440 } = {}) {
  const root = element('html')
  const head = element('head')
  const body = withBody ? element('body') : undefined
  const doc = element('document')
  doc.head = head
  doc.body = body
  doc.documentElement = root
  doc.getElementById = (id) => head.children.find((child) => child.id === id)
  doc.createElement = (tag) => element(tag)
  doc.querySelector = (sel) => (body ? body.querySelector(sel) : null)
  doc.querySelectorAll = (sel) => {
    const found = []
    const walk = (n) => { for (const c of n.children) { if (sel === "button" && c.tagName === "BUTTON") found.push(c); walk(c) } }
    if (body) walk(body)
    return found
  }
  // the app's own control: the conversation header's way into a hidden side
  const anchor = element("button")
  anchor.className = "app_iconButton"
  anchor.setAttribute("aria-label", "פיחת סרגל שמאל")   // the office's own words, as they are today
  anchor.innerHTML = '<svg viewBox="0 0 24 24"><path d="M9 3v18"/></svg>'
  const header = element("div")
  if (body) { spill(header, body); spill(anchor, header) }
  // …and the REAL hooks the placement is written against (ui-conversation / ui-layout CSS-module
  // suffixes, read off the pinned build): the conversation's column, its header row, the title
  // cluster the twin must stand immediately before, and the seat the app's own button sits in.
  let frame = null
  const parts = {}                                     // the sessions menu's own elements (below)
  if (body) {
    frame = element("div"); frame.className = "pI_x6G_frame"
    frame.setAttribute("data-sidebar-collapsed", "")   // the panel starts closed, as it does on a phone
    // `ui-layout` writes the three tracks inline; the narrow state is decided from the width, and
    // the sheet keeps the width the harness computed for the sidebar
    frame.style.gridTemplateColumns = "280px minmax(0, 1fr) 0px"
    spill(frame, body)
    const centre = element("div"); centre.className = "wSkVaW_centerCol"
    const row = element("div"); row.className = "wSkVaW_header"
    const corner = element("div"); corner.className = "wSkVaW_headerCorner"
    const title = element("div"); title.className = "wSkVaW_titleCluster"
    title.textContent = "אפשרות מצב מסך מלא ושיפור"
    // the seat's own button — what the app draws there while the panel is hidden, and the thing the
    // twin copies its classes and glyph from
    const seatBtn = element("button")
    seatBtn.className = "wSkVaW_iconButton"
    seatBtn.setAttribute("aria-label", "פתיחת סרגל שמאל")
    seatBtn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M15 3v18"/></svg>'
    spill(centre, frame); spill(row, centre); spill(title, row); spill(corner, row); spill(seatBtn, corner)

    // …and the sessions menu the sheet draws over the conversation: the app's own rows, in the shape
    // they were READ off the live app (2026-10-14) — a `_sessionRow`, its `_rowActions` cluster with
    // the «פעולות …» button and the per-workspace new-conversation door, and the header's own
    // `_newSession` button. What counts as "a choice" is decided from these, so they are the fixture.
    const sidebar = element("div"); sidebar.className = "hHd-Xa_sidebarCol"
    const sessionRow = element("div"); sessionRow.className = "YDXeBa_sessionRow"
    sessionRow.setAttribute("role", "treeitem"); sessionRow.textContent = "שיחה קודמת"
    const rowActions = element("div"); rowActions.className = "YDXeBa_rowActions"
    const rowOverflow = element("button"); rowOverflow.className = "YDXeBa_iconButton"
    rowOverflow.setAttribute("aria-label", "פעולות לשיחה שיחה קודמת")
    const rowNew = element("button"); rowNew.className = "YDXeBa_iconButton"
    rowNew.setAttribute("aria-label", "שיחה חדשה בהלשכה הדיגיטלית")
    const newDoor = element("button"); newDoor.className = "hHd-Xa_newSession"
    newDoor.textContent = "שיחה חדשה"
    spill(sidebar, frame); spill(sessionRow, sidebar); spill(rowActions, sessionRow)
    spill(rowOverflow, rowActions); spill(rowNew, rowActions); spill(newDoor, sidebar)
    Object.assign(parts, { sidebar, sessionRow, rowOverflow, rowNew, newDoor })
  }

  const observers = []
  class FakeObserver {
    constructor(callback) { this.callback = callback; observers.push(this) }
    observe(target) { this.target = target }
    disconnect() { this.disconnected = true }
    trigger() { this.callback([]) }
  }

  const store = new Map(stored === null ? [] : [['dsh.navCollapsed', stored]])
  const listeners = new Map()
  const p = {
    document: doc,
    innerWidth: width,
    localStorage: {
      getItem: (key) => (store.has(key) ? store.get(key) : null),
      setItem: (key, value) => store.set(key, String(value)),
    },
    MutationObserver: FakeObserver,
    addEventListener: (type, fn) => { if (!listeners.has(type)) listeners.set(type, []); listeners.get(type).push(fn) },
    removeEventListener: (type, fn) => {
      const list = listeners.get(type) || []
      const at = list.indexOf(fn)
      if (at >= 0) list.splice(at, 1)
    },
    listeners,
    resize: () => (listeners.get('resize') || []).forEach((fn) => fn({})),
    warnings: [],
    observers,
    store,
    root,
    frame,
    // a scheduler the test drives: the plugin asks the page to defer one close, and the assert says
    // what that close did — a real `setTimeout` would make the suite sleep to find out
    timers: [],
    setTimeout(fn) { this.timers.push(fn); return this.timers.length },
    flush() { while (this.timers.length) this.timers.shift()() },
    ...parts,
  }
  p.console = { warn: (...args) => p.warnings.push(args) }
  if (shellFocused) root.setAttribute('data-shell-focus', '')
  return p
}

/** Load lib/client.js the way the harness's own loader does, and mount it on a fake page. */
async function mount(p, ctx = {}) {
  const source = await readFile(CLIENT, 'utf8')
  // The loader KEEPS the module object the factory returns — so does this, and that is the whole
  // point: the plugin's own later writes (`exports._…`) land on the object the host holds, which a
  // copy of the first keys would not show.
  let moduleExports
  const fakeWindow = { __ModuleLoader__: { load: ({ factory }) => { moduleExports = factory(() => ({})) } } }
  const globals = Object.assign(Object.create(null), p, { window: fakeWindow })
  new Function('window', 'globalThis', source)(fakeWindow, globals)
  p.globals = globals                     // the page the plugin really reads (its `innerWidth`)
  if (ctx !== null) moduleExports.apply(ctx)
  return { exports: moduleExports, p }
}

const stylesheet = (p) => p.document.head.children.find((c) => c.id === 'bina-nav-collapse-css')

const collapsed = (p) => p.root.hasAttribute('data-bina-compact')

// ── the narrow frame's sheet (agt-013) ──────────────────────────────────────────────────────────
const over = (p) => p.root.hasAttribute('data-bina-menu-over')
const sheetWidth = (p) => p.root.style.getPropertyValue('--bina-menu-w')
const scrimOf = (p) => p.frame.children.find((c) => c.className === 'bina-menu-scrim')
const openPanel = (p) => p.frame.removeAttribute('data-sidebar-collapsed')

test('on a NARROW frame the open menu is a sheet OVER the conversation, never a column beside it', async () => {
  const p = page({ width: 390 })
  await mount(p, { layout: { toggleSidebar() {} } })
  assert.equal(over(p), false, 'the rail is not a sheet')
  openPanel(p)
  p.observers.forEach((o) => o.trigger())
  assert.equal(over(p), true, 'the menu open on a phone is the sheet state')
  const scrim = scrimOf(p)
  assert.ok(scrim, 'and a tap outside it has something to land on')
  assert.equal(scrim.parentNode, p.frame, 'drawn inside the frame the sheet covers')
  assert.equal(sheetWidth(p), '280px', 'the sheet keeps the width the harness computed for it')
  const text = stylesheet(p).textContent
  assert.match(text, /html\[data-bina-menu-over\] \[class\*="_frame"\]\{grid-template-columns:0 minmax\(0,1fr\) 0!important\}/)
  assert.match(text, /\[class\*="_centerCol"\]\{grid-column:2!important/, 'the centre is PINNED to the middle track')
  assert.match(text, /\[class\*="_sidebarCol"\]\{\s*position:absolute!important;inset-block:0;inset-inline-start:0;/)
  assert.match(text, /width:var\(--bina-menu-w,300px\)/)
  assert.doesNotMatch(text, /_sidebarCol"\]\{display:none/)
})

test('a WIDE frame keeps the menu as the column it always was', async () => {
  const p = page({ width: 1440 })
  await mount(p, { layout: { toggleSidebar() {} } })
  openPanel(p)
  p.observers.forEach((o) => o.trigger())
  assert.equal(over(p), false)
  assert.equal(scrimOf(p), undefined, 'no scrim over a desktop conversation')
})

test('the rail of a narrow frame is not a sheet, and neither is a folded page', async () => {
  const rail = page({ width: 390 })
  await mount(rail, { layout: { toggleSidebar() {} } })
  rail.observers.forEach((o) => o.trigger())
  assert.equal(over(rail), false, 'a 56px rail is a column, and it is drawn as one')

  const folded = page({ width: 390, stored: '1' })
  await mount(folded, { layout: { toggleSidebar() {} } })
  openPanel(folded)
  folded.observers.forEach((o) => o.trigger())
  assert.equal(over(folded), false, 'while the page is folded away there is nothing to lay a sheet over')
})

test('tapping outside the sheet closes the panel — through the layout’s own toggle', async () => {
  const calls = []
  const p = page({ width: 390 })
  await mount(p, { layout: { toggleSidebar: () => {
    p.frame.toggleAttribute('data-sidebar-collapsed', true)
    calls.push('toggleSidebar')
  } } })
  openPanel(p)
  p.observers.forEach((o) => o.trigger())
  assert.ok(scrimOf(p))
  scrimOf(p).dispatch('click', { stopPropagation() {} })
  assert.deepEqual(calls, ['toggleSidebar'], 'the frame stays the one owner of “is the panel open”')
  p.observers.forEach((o) => o.trigger())                    // …and it now says: closed
  assert.equal(over(p), false, 'the sheet is gone once the frame says the panel is')
  assert.equal(scrimOf(p), undefined)
})

// ── a choice inside the menu (DGO-552) ──────────────────────────────────────────────────────────
// The owner, 2026-10-13: «במובייל בחירה בתפריט השיחות — «שיחה חדשה» או שיחה קיימת — לא סוגרת את
// התפריט». The scrim closes the sheet from outside it; these are the taps from inside.
test('choosing a session closes the sheet — the tap means “show me that”', async () => {
  const calls = []
  const p = page({ width: 390 })
  await mount(p, { layout: { toggleSidebar: () => calls.push('toggleSidebar') } })
  openPanel(p)
  p.observers.forEach((o) => o.trigger())
  assert.equal(over(p), true, 'the sheet is drawn over the conversation')
  p.document.dispatch('click', { target: p.sessionRow })
  assert.deepEqual(calls, [], 'the app answers the tap first — the close is deferred, never blind')
  p.flush()
  assert.deepEqual(calls, ['toggleSidebar'], 'and then the panel closes through its own face')
})

test('…and so does either door to a new conversation', async () => {
  const calls = []
  const p = page({ width: 390 })
  await mount(p, { layout: { toggleSidebar: () => calls.push('toggleSidebar') } })
  openPanel(p)
  p.observers.forEach((o) => o.trigger())
  p.document.dispatch('click', { target: p.newDoor })
  p.flush()
  assert.deepEqual(calls, ['toggleSidebar'], 'the sidebar header’s own «שיחה חדשה»')
  p.document.dispatch('click', { target: p.rowNew })
  p.flush()
  assert.deepEqual(calls, ['toggleSidebar', 'toggleSidebar'], '…and the one inside a workspace’s row')
})

test('the row’s own «פעולות» cluster is NOT a choice: it manages the list the sheet is showing', async () => {
  const calls = []
  const p = page({ width: 390 })
  await mount(p, { layout: { toggleSidebar: () => calls.push('toggleSidebar') } })
  openPanel(p)
  p.observers.forEach((o) => o.trigger())
  p.document.dispatch('click', { target: p.rowOverflow })
  p.flush()
  assert.deepEqual(calls, [], 'opening a row’s menu must not close the sheet under it')
})

test('a session tap on a WIDE frame leaves the panel where it is — a column is not a sheet', async () => {
  const calls = []
  const p = page({ width: 1440 })
  await mount(p, { layout: { toggleSidebar: () => calls.push('toggleSidebar') } })
  openPanel(p)
  p.observers.forEach((o) => o.trigger())
  assert.equal(over(p), false)
  p.document.dispatch('click', { target: p.sessionRow })
  p.flush()
  assert.deepEqual(calls, [])
})

test('a panel the app folded for itself is left folded — the ask comes after the app answered', async () => {
  const calls = []
  const p = page({ width: 390 })
  await mount(p, { layout: { toggleSidebar: () => calls.push('toggleSidebar') } })
  openPanel(p)
  p.observers.forEach((o) => o.trigger())
  p.document.dispatch('click', { target: p.sessionRow })
  p.frame.setAttribute('data-sidebar-collapsed', '')     // the harness folds it, as it does on a navigation
  p.observers.forEach((o) => o.trigger())                // (the frame's own watcher is what notices)
  p.flush()
  assert.deepEqual(calls, [], 'a blind toggle here would have REOPENED the panel it just folded')
  assert.equal(over(p), false)
})

test('the choice listener goes with the plugin', async () => {
  const calls = []
  const cleanups = []
  const p = page({ width: 390 })
  await mount(p, { layout: { toggleSidebar: () => calls.push('toggleSidebar') },
                   effect: (fn) => cleanups.push(fn()) })
  openPanel(p)
  p.observers.forEach((o) => o.trigger())
  cleanups[0]()
  p.document.dispatch('click', { target: p.sessionRow })
  p.flush()
  assert.deepEqual(calls, [], 'an unmounted plugin closes nobody’s menu')
})

test('turning the phone (a resize) is followed, and leaving the width drops the sheet', async () => {  const p = page({ width: 390 })
  await mount(p, { layout: { toggleSidebar() {} } })
  openPanel(p)
  p.resize()
  assert.equal(over(p), true)
  p.globals.innerWidth = 1440                                  // a tablet, or the same page on a desktop
  p.resize()
  assert.equal(over(p), false)
  assert.equal(scrimOf(p), undefined)
})

test('unmounting takes the sheet and its scrim with it', async () => {
  const p = page({ width: 390 })
  const cleanups = []
  await mount(p, { layout: { toggleSidebar() {} }, effect: (fn) => cleanups.push(fn()) })
  openPanel(p)
  p.observers.forEach((o) => o.trigger())
  const scrim = scrimOf(p)
  assert.ok(scrim)
  cleanups[0]()
  assert.equal(scrim.removed, true)
  assert.equal(over(p), false)
})

test('the module is a plugin: an apply, and the one service it needs', async () => {
  const { exports } = await mount(page(), { layout: { toggleSidebar() {} } })
  assert.equal(typeof exports.apply, 'function')
  assert.deepEqual(exports.inject, ["layout"], 'the frame’s panel face must be asked for by name')
})

test('nothing is folded until somebody asks', async () => {
  const { p } = await mount(page())
  assert.equal(collapsed(p), false)
})

test('the stylesheet is installed once, and names the columns by their readable suffixes', async () => {
  const { p } = await mount(page())
  assert.equal(p.document.head.children.filter((c) => c.id === 'bina-nav-collapse-css').length, 1)
  const text = stylesheet(p).textContent
  assert.match(text, /\[class\*="_frame"\]/)                                  // the grid
  assert.match(text, /\[class\*="_sidebarCol"\]/)                             // the menu
  assert.match(text, /\[class\*="_rightbarCol"\]/)                            // the side panel
  assert.match(text, /\[class\*="_handle"\]/)                                 // …the drag handles go too
  assert.match(text, /grid-template-columns:0 minmax\(0,1fr\) 0!important/)   // no column, no rail
  // the trap this suite exists for: a column hidden with display:none leaves the grid, the centre
  // takes the zero-width track, and the conversation is 0px wide in a frame that looks right
  assert.match(text, /\[class\*="_sidebarCol"\],\[class\*="_rightbarCol"\]\{visibility:hidden!important/)
  assert.doesNotMatch(text, /_sidebarCol"\]\{display:none/)
})

test('the remembered choice folds the frame, and leaving it is remembered too', async () => {
  const { exports, p } = await mount(page({ stored: '1' }))
  if (p.warnings.length) console.log('PLUGIN WARNINGS:', p.warnings.map(String))
  assert.equal(collapsed(p), true)
  exports._setByUser(false)
  assert.equal(collapsed(p), false)
  assert.equal(p.store.get('dsh.navCollapsed'), '0')
})

test('it stands in the CONVERSATION’s row, immediately before the session’s name', async () => {
  const { p } = await mount(page(), { layout: { toggleSidebar() {} } })
  const title = p.document.querySelector('[class*="_titleCluster"]')
  const twin = p.document.querySelectorAll('button').find((b) => b.className.includes('bina-nav-fold'))
  assert.ok(twin, 'the twin exists')
  const row = title.parentNode
  assert.equal(row.children[row.children.indexOf(title) - 1], twin,
    'it is the element right before the session’s name')
  assert.equal(twin.parentNode, row, 'in that very row')
  assert.equal(twin.parentNode.className.includes('header'), true, '…the header row, not the rail')
})

test('the other panel’s control leads the row, wearing the app’s classes and its glyph', async () => {
  const calls = []
  let panelOpen = false
  const { p } = await mount(page(), { layout: { toggleSidebar: () => {
    panelOpen = !panelOpen
    const frame = p.document.querySelector('[class*="_frame"]')
    if (panelOpen) frame.removeAttribute('data-sidebar-collapsed')
    else frame.setAttribute('data-sidebar-collapsed', '')
    calls.push("toggleSidebar")
  } } })
  const anchor = p.document.querySelectorAll('button').find((b) => /סרגל/.test(b.getAttribute('aria-label') || ''))
  assert.ok(anchor, "the app's own header control is there to stand beside")
  const twin = p.document.querySelectorAll('button').find((b) => b.className.includes('bina-nav-fold'))
  assert.ok(twin && twin.className.includes('bina-nav-fold'), 'the twin is the app’s control, plus the fold')
  assert.equal(twin.className.includes('wSkVaW_iconButton'), true,
    '…wearing the app’s own classes (the header seat’s button), not a lookalike')
  const seatBtn = p.document.querySelector('[class*="_headerCorner"]').querySelector('button')
  assert.equal(twin.innerHTML, seatBtn.innerHTML, '…and its glyph, which the stylesheet mirrors')
  assert.match(twin.title, /פתיחת סרגל ימין/)
  twin.dispatch('click')
  assert.deepEqual(calls, ["toggleSidebar"], 'it is the RIGHT panel’s control: the layout’s own toggle')
  assert.equal(collapsed(p), false, 'opening the panel keeps the rail: he is navigating')
  twin.dispatch('click')
  assert.deepEqual(calls, ["toggleSidebar", "toggleSidebar"])
  assert.equal(collapsed(p), true, 'closing it hides the rail too: he gets the whole width back')
})

test('double-clicking it: closed → open → closed again, and the width comes back', async () => {
  const calls = []
  const { p } = await mount(page({ stored: '1' }), { layout: { toggleSidebar: () => {
    const frame = p.document.querySelector('[class*="_frame"]')
    const isClosed = frame.hasAttribute('data-sidebar-collapsed')
    if (isClosed) frame.removeAttribute('data-sidebar-collapsed')
    else frame.setAttribute('data-sidebar-collapsed', '')
    calls.push('t')
  } } })
  const twin = p.document.querySelectorAll('button').find((b) => b.className.includes('bina-nav-fold'))
  assert.equal(collapsed(p), true, 'starts at full width')
  twin.dispatch('click')                       // frame says the panel is collapsed → open it
  assert.deepEqual(calls, ['t'])
  assert.equal(collapsed(p), false, 'the rail is back, and the panel was asked to open')
  twin.dispatch('click')                       // …now the frame will say it is open → close + hide the rail
  assert.equal(collapsed(p), true)
})

test('…and if that action is ever unavailable, the button still does the neighbouring thing', async () => {
  const { p } = await mount(page())          // no layout service in the host, as a stripped build would be
  const twin = p.document.querySelectorAll('button').find((b) => b.className.includes('bina-nav-fold'))
  twin.dispatch('click')
  assert.equal(collapsed(p), true, 'the office fold, rather than a dead control')
})

test('Shift+Cmd/Ctrl+B folds and unfolds, and nothing else does', async () => {
  const { p } = await mount(page())
  assert.equal(p.document.dispatch('keydown', { shiftKey: true, metaKey: true, key: 'b' }), true)
  assert.equal(collapsed(p), true)
  p.document.dispatch('keydown', { shiftKey: true, ctrlKey: true, key: 'B' })
  assert.equal(collapsed(p), false)
  p.document.dispatch('keydown', { key: 'b' })                        // no modifiers
  p.document.dispatch('keydown', { shiftKey: true, key: 'b' })         // no meta/ctrl
  p.document.dispatch('keydown', { shiftKey: true, metaKey: true, key: 'k' })
  assert.equal(collapsed(p), false, 'nothing else toggles it')
})

test('the console’s full screen folds this page with it, and its exit gives it back', async () => {
  const { p } = await mount(page({ stored: '0' }))
  assert.equal(collapsed(p), false)
  p.root.setAttribute('data-shell-focus', '')          // the console enters full screen
  p.observers.forEach((o) => o.trigger())
  assert.equal(collapsed(p), true)
  p.root.removeAttribute('data-shell-focus')           // …and leaves it
  p.observers.forEach((o) => o.trigger())
  assert.equal(collapsed(p), false)
})

test('a page that chose the fold keeps it after the shell’s full screen ends', async () => {
  const { p } = await mount(page({ stored: '1' }))
  p.root.setAttribute('data-shell-focus', '')
  p.observers.forEach((o) => o.trigger())
  assert.equal(collapsed(p), true)
  p.root.removeAttribute('data-shell-focus')
  p.observers.forEach((o) => o.trigger())
  assert.equal(collapsed(p), true, 'the person’s own choice outlives the shell’s state')
})

test('the glyph is the app’s own, mirrored — and nothing floats over the transcript', async () => {
  const { p } = await mount(page())
  const text = stylesheet(p).textContent
  assert.ok(text.includes('.bina-nav-fold svg{transform:scaleX(-1)!important}'), 'the icon is flipped, not replaced')
  assert.equal(text.includes('.bina-nav-handle'), false, 'the floating circle is gone')
  assert.equal(p.document.body.children.some((c) => c.className.includes('bina-nav-handle')), false)
})

test('while the shell decides, the page hides its own twin and does not fight it', async () => {
  const { p } = await mount(page({ shellFocused: true }))
  assert.ok(stylesheet(p).textContent.includes('html[data-shell-focus] .bina-nav-fold{display:none!important}'))
  assert.equal(collapsed(p), true)
  p.document.dispatch('keydown', { shiftKey: true, metaKey: true, key: 'b' })
  assert.equal(collapsed(p), true, 'the key is inert while the shell is in full screen')
})

test('storage that refuses is not a reason to fail', async () => {
  const p = page()
  p.localStorage = {
    getItem() { throw new Error('private mode') },
    setItem() { throw new Error('private mode') },
  }
  const { exports } = await mount(p)
  exports._setByUser(true)
  assert.equal(collapsed(p), true)
  exports._setByUser(false)
  assert.equal(collapsed(p), false)
  assert.deepEqual(p.warnings, [])
})

test('a page without a body is not a reason to fail', async () => {
  const p = page({ withBody: false })
  const { exports } = await mount(p, null)
  exports.apply({})              // must not throw
  assert.deepEqual(p.warnings, [])
})

test('unmounting takes the handle, the key and the observer with it', async () => {
  const p = page({ stored: '1' })
  const cleanups = []
  const { p: mounted } = await mount(p, { effect: (fn) => cleanups.push(fn()) })
  const button = mounted.document.querySelectorAll('button').find((b) => b.className.includes('bina-nav-fold'))
  assert.ok(button, 'the twin exists before unmounting')
  assert.equal(cleanups.length, 1)
  assert.equal(typeof cleanups[0], 'function')
  cleanups[0]()                                    // the harness unmounts the plugin
  assert.equal(button.removed, true)
  assert.equal(p.observers.every((o) => o.disconnected), true)
  assert.equal(p.document.dispatch('keydown', { shiftKey: true, metaKey: true, key: 'b' }), false)
})
