// The extension's recovery rule (worker-1.2.js recoverSession, DGO-571), run in node against a fake
// `chrome`: the worker is evaluated in a vm context whose globals are the fake, so the very functions
// Chrome would run are the ones asserted here. Run by test_handoff.py (skipped where node is absent):
//     node apps/browser42/test_worker.mjs
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import assert from "node:assert/strict";

const here = path.dirname(fileURLToPath(import.meta.url));
const source = readFileSync(path.join(here, "extension", "worker-1.2.js"), "utf8");
const noop = { addListener() {} };

function fakeChrome(state) {
  // state: { nextGroup, tabs: [{id, url, groupId, windowId}], groups: {id: {title, color}}, storage: {} }
  const tabOf = async (id) => {
    const tab = state.tabs.find(t => t.id === id);
    if (!tab) throw new Error(`No tab with id: ${id}`);
    return tab;
  };
  return {
    storage: { local: {
      async get(key) {
        if (key === null) return { ...state.storage };
        const out = {};
        for (const k of (Array.isArray(key) ? key : [key])) if (k in state.storage) out[k] = state.storage[k];
        return out;
      },
      async set(values) { Object.assign(state.storage, JSON.parse(JSON.stringify(values))); },
      async remove(keys) { for (const k of (Array.isArray(keys) ? keys : [keys])) delete state.storage[k]; },
    } },
    tabs: {
      get: tabOf,
      async query(q) { return state.tabs.filter(t => q.groupId === undefined || t.groupId === q.groupId); },
      async update(id, props) { const tab = await tabOf(id); Object.assign(tab, props); return tab; },
      async group({ tabIds, groupId }) {
        const id = groupId ?? state.nextGroup++;
        for (const tid of tabIds) (await tabOf(tid)).groupId = id;
        state.groups[id] = state.groups[id] || { title: "", color: "grey" };
        return id;
      },
      async remove() {}, async sendMessage() {},
      onUpdated: noop, onCreated: noop, onRemoved: noop,
    },
    tabGroups: {
      async get(id) { const g = state.groups[id]; if (!g) throw new Error(`No group with id: ${id}`); return { id, ...g }; },
      async update(id, props) { Object.assign(state.groups[id], props); return { id, ...state.groups[id] }; },
    },
    windows: { async update() {} },
    scripting: { async executeScript() {} },
    runtime: { onConnect: noop, onMessage: noop, onInstalled: noop, onStartup: noop,
               connect() { return { onMessage: noop, onDisconnect: noop, postMessage() {} }; } },
    alarms: { create() {}, onAlarm: noop },
    offscreen: { async hasDocument() { return true; }, async createDocument() {} },
  };
}

function worker(state) {
  const context = vm.createContext({ chrome: fakeChrome(state), crypto: { randomUUID: () => "uuid-new" }, setTimeout, console, URL });
  vm.runInContext(source, context, { filename: "worker-1.2.js" });
  return context;                       // top-level function declarations are the context's globals
}

const WA = "https://web.whatsapp.com/";
const stale = (tabId, extra = {}) => ({ tabId, groupId: 99, ownedTabIds: [tabId], lastUrl: WA, policy: "single", generation: "g-old", ...extra });
let cases = 0;

// A. Two restored groups on the SAME address: the group's name decides, the other group is untouched.
{
  const state = { nextGroup: 10,
    tabs: [{ id: 101, url: WA, groupId: 1, windowId: 1 }, { id: 102, url: WA, groupId: 2, windowId: 1 }],
    groups: { 1: { title: "wa-one", color: "cyan" }, 2: { title: "wa-two", color: "pink" } },
    storage: { "session_wa-one": stale(11), "session_wa-two": stale(12) } };
  const w = worker(state);
  const two = await w.frontSession({ slug: "wa-two", url: WA, label: "wa-two", color: "pink" });
  assert.deepEqual([two.ok, two.tabId, two.groupId, two.recovered], [true, 102, 2, true]);
  assert.equal(state.storage["owner_101"], undefined, "the other group's tab is not adopted");
  assert.equal(state.storage["session_wa-one"].tabId, 11, "the other session is not rewritten");
  assert.equal(state.storage["session_wa-two"].tabId, 102);
  const one = await w.frontSession({ slug: "wa-one", url: WA, label: "wa-one", color: "cyan" });
  assert.deepEqual([one.ok, one.tabId], [true, 101], "and the first group finds its own tab too");
  cases++;
}
// B. No names, two ownerless tabs at one address: ambiguous → lost, nothing adopted.
{
  const state = { nextGroup: 10,
    tabs: [{ id: 201, url: WA, groupId: -1, windowId: 1 }, { id: 202, url: WA, groupId: -1, windowId: 1 }],
    groups: {}, storage: { "session_wa-one": stale(11) } };
  const r = await worker(state).frontSession({ slug: "wa-one", url: WA, label: "wa-one" });
  assert.deepEqual([r.ok, r.error.code], [false, "tab_lost"]);
  assert.deepEqual([state.storage["owner_201"], state.storage["owner_202"], state.storage["session_wa-one"]], [undefined, undefined, undefined]);
  cases++;
}
// C. One ownerless tab at the address and no group: adopted, grouped under the slug, re-tagged, persisted.
{
  const state = { nextGroup: 10,
    tabs: [{ id: 301, url: WA, groupId: -1, windowId: 1 }, { id: 302, url: "https://mail.example/", groupId: -1, windowId: 1 }],
    groups: {}, storage: { "session_wa-one": stale(11) } };
  const r = await worker(state).frontSession({ slug: "wa-one", url: WA, label: "wa-one", color: "cyan" });
  assert.deepEqual([r.ok, r.tabId, r.recovered], [true, 301, true]);
  assert.equal(state.storage["owner_301"], "wa-one");
  assert.deepEqual(state.storage["session_wa-one"].ownedTabIds, [301]);
  assert.equal(state.storage["session_wa-one"].lastUrl, WA);
  assert.deepEqual(state.groups[r.groupId], { title: "wa-one", color: "cyan", collapsed: false });
  cases++;
}
// D. The only tab at the address sits in a group named for ANOTHER known session: never adopted.
{
  const state = { nextGroup: 10,
    tabs: [{ id: 401, url: WA, groupId: 1, windowId: 1 }], groups: { 1: { title: "wa-two", color: "pink" } },
    storage: { "session_wa-one": stale(11), "session_wa-two": stale(12) } };
  const r = await worker(state).frontSession({ slug: "wa-one", url: WA, label: "wa-one" });
  assert.equal(r.error.code, "tab_lost");
  assert.equal(state.storage["owner_401"], undefined);
  assert.equal(state.storage["session_wa-two"].tabId, 12);
  cases++;
}
// E. A restored group with a name of its own (not a session's) keeps that name and colour.
{
  const state = { nextGroup: 10,
    tabs: [{ id: 501, url: WA, groupId: 1, windowId: 1 }], groups: { 1: { title: "pairing", color: "green" } },
    storage: { "session_wa-one": stale(11) } };
  const r = await worker(state).frontSession({ slug: "wa-one", url: WA, label: "wa-one", color: "cyan" });
  assert.deepEqual([r.ok, r.tabId, r.groupId], [true, 501, 1]);
  assert.deepEqual(state.groups[1], { title: "pairing", color: "green", collapsed: false });
  cases++;
}
// F. A live, owned tab needs no recovery: the plain path, same window, no rewrite.
{
  const state = { nextGroup: 10,
    tabs: [{ id: 601, url: WA, groupId: 1, windowId: 1 }], groups: { 1: { title: "wa-one", color: "cyan" } },
    storage: { "session_wa-one": stale(601, { groupId: 1 }), "owner_601": "wa-one" } };
  const r = await worker(state).frontSession({ slug: "wa-one", url: WA, label: "wa-one" });
  assert.deepEqual([r.ok, r.tabId, r.recovered], [true, 601, false]);
  assert.equal(state.tabs[0].active, true);
  cases++;
}
console.log(`worker recoverSession rules: ${cases} cases ok`);
