#!/usr/bin/env node
/* test_power_settings.mjs — the "חשמל ושינה" card draws every answer the machine service can send.
 *
 *     node platform-base/console/test_power_settings.mjs [path-to-power-settings.js]
 *
 * DGO-520. The card in הגדרות מסוף showed the owner this: «שירות «מכונה»: Cannot read properties of
 * undefined (reading 'grant')» — a JavaScript message wearing another service's name. Two faults made
 * one sentence:
 *
 *   · the single-use lid permission is a macOS fact (`status.lid_permission`, `status.setup`), and the
 *     callout drew itself when `!s.lid_permission` — which is true both for a Mac that REFUSED the
 *     permission and for a status that does not report one at all, as every status from this Windows
 *     office does. It then read `s.setup.grant` off a status that has no agent, and threw;
 *   · `load()` held the whole body in one try, so that throw landed in the catch that names the
 *     MACHINE service, and the owner was told the machine had said it.
 *
 * So the cases below are the payloads the office actually serves: this host's own (no agent, no
 * permission, no setup), a Mac that refused the permission, a Mac that granted it, and a Mac whose
 * status is older than the field. A gate did not catch this class before; this is that gate.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..");
const SRC = process.argv[2] || path.join(REPO, "platform-base/console/static/power-settings.js");

let bad = 0;
const check = (name, ok, detail) => {
  if (!ok) bad++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok || !detail ? "" : `\n        ${detail}`}`);
};

// ── a DOM, to the depth this card uses: `innerHTML`, one `.pw-body` lookup, and the wiring pass ──
function element(tag) {
  const kids = [];
  const self = { children: kids };
  const node = {
    tagName: tag, className: "", dataset: {}, style: {}, textContent: "",
    isConnected: true, attrs: {}, _html: "",
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); },
    appendChild(c) { kids.push(c); return c; },
    querySelector(sel) {
      // `render()` looks up the element it may draw into; every other lookup is the wiring pass, which
      // finds nothing and therefore attaches nothing — the card is HTML, and the test reads the HTML.
      if (sel === ".pw-body") { this._body = this._body || element("div"); return this._body; }
      return null;
    },
    querySelectorAll() { return []; },
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k] ?? null; },
    addEventListener() {}, removeEventListener() {}, focus() {},
  };
  Object.assign(self, node);
  return self;
}
const documentShim = { createElement: element, head: element("head"), body: element("body"),
                       getElementById: () => null };

// the shell's own helpers, as this card receives them from app.js
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ago = (s) => (s == null ? "לא ידוע" : `${s} שניות`);
const when = (t) => String(t);
const guardHe = (r) => String(r);

/** Render the card against one payload, and let its own async load finish. */
async function renderCard(payload, { status = 200 } = {}) {
  const errors = [];
  const source = fs.readFileSync(SRC, "utf8");
  const host = element("div");
  const boot = new Function(
    "window", "document", "fetch", "setInterval", "clearInterval", "navigator", "console",
    "esc", "ago", "when", "guardHe",
    source + "\nreturn window.BinaPower;");
  const api = boot({}, documentShim, async () => ({ ok: status < 400, status, json: async () => payload }),
    () => 0, () => {}, {}, { error: (...a) => errors.push(a), warn() {}, log() {} },
    esc, ago, when, guardHe);
  api.render(host);
  for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0));
  // the card is the host's first child, and the element it may draw into is the one it looked up
  const card = host.children[0];
  const body = card && card._body;
  const html = body ? body.innerHTML : "";
  return { html, cardHtml: card ? card.innerHTML : "", errors, host, card };
}

const now = Math.floor(Date.now() / 1000);
const POLICY_RUN = { lock: { ac: "run", battery: "run" }, lid: { ac: "run", battery: "run" },
                     battery_floor: 20, thermal_guard: true };
const iso = (t) => new Date(t * 1000).toISOString();

/* THIS OFFICE, as /a/machine/api/power answers here (measured 2026-10-10): the Windows host holds the
   sleep itself, there is no power agent, and the status carries nothing about a lid, a permission or
   setup commands. */
const WINDOWS = {
  policy: POLICY_RUN, defaults: POLICY_RUN,
  status: { updated_at: now - 7, os: "windows", hold: true, holder_pid: 20100, holders: 1 },
  agent: "absent", age_s: 7, host_os: "windows", generated_at: iso(now),
};

/** A Mac's status, in the shape packaging/macos/power-agent.py writes it. */
const macStatus = (extra = {}) => ({
  version: 1, platform: "macos", host: "MacBook", updated_at: now - 5, agent_pid: 4312,
  engine_running: true, power: { source: "ac", percent: 88 }, lid: { closed: false, causes_sleep: true },
  screen_locked: false, thermal: { state: "nominal", name: "nominal" },
  sleep_disabled: false, caffeinated: true, lid_permission: true,
  effective: { lock: "run", lid: "run", source: "ac", guards: [] },
  wanted: { lock: "run", lid: "run" }, notes: [],
  events: [{ at: now - 600, kind: "Wake", cause: "lid-opened", on: "ac" }], asleep_last_24h_h: 0.4,
  setup: { grant: "./bbox engine power grant", revoke: "./bbox engine power revoke" },
  ...extra,
});
const MAC = (status) => ({ policy: POLICY_RUN, defaults: POLICY_RUN, status, agent: "running",
                           age_s: 5, host_os: "macos", generated_at: iso(now) });

const run = async () => {
  // 1 — this office. Nothing here may be called the machine's fault, and nothing may stay «טוען…».
  const win = await renderCard(WINDOWS);
  check("a host with no power agent draws the card",
    win.cardHtml.includes("חשמל ושינה") && win.html.length > 200, win.html.slice(0, 200));
  check("…and never as the machine service's sentence",
    !win.html.includes("שירות «מכונה»") && !/Cannot read|undefined|not defined/.test(win.html),
    win.html.match(/שירות «מכונה»[^<]*/)?.[0] || win.html.slice(0, 200));
  check("…not left on «טוען את מצב המחשב…»", !win.html.includes("טוען את מצב המחשב"), win.html.slice(0, 160));
  check("…with no permission callout to ask for", !win.html.includes("הרשאה חד-פעמית"));
  check("…and nothing logged as a draw fault", win.errors.length === 0,
    win.errors.map((e) => String(e[1] && e[1].message)).join(" | "));
  check("the Windows host is told what is true here", win.html.includes("Windows"), win.html.slice(0, 400));

  // 2 — a Mac that REFUSED the permission: the callout is the whole point of the field, and it names
  // the command to run. The fix must not have deleted the feature.
  const refused = await renderCard(MAC(macStatus({ lid_permission: false })));
  check("a Mac that refused the permission is asked for it",
    refused.html.includes("הרשאה חד-פעמית") && refused.html.includes("./bbox engine power grant"),
    refused.html.slice(0, 200));
  check("…and that is not a draw fault either", refused.errors.length === 0);

  // 3 — a Mac that granted it: nothing to ask for.
  const granted = await renderCard(MAC(macStatus({ lid_permission: true })));
  check("a Mac that granted the permission is not asked again", !granted.html.includes("הרשאה חד-פעמית"));

  // 4 — the status of an older agent: no setup commands, permission not reported. Neither a refusal
  // nor a reason to throw.
  const older = macStatus({ lid_permission: false, setup: undefined });
  const noSetup = await renderCard(MAC(older));
  check("a status without setup commands draws, and asks for nothing",
    !/Cannot read|undefined/.test(noSetup.html) && !noSetup.html.includes("הרשאה חד-פעמית") &&
    noSetup.errors.length === 0, noSetup.html.slice(0, 200));

  // 5 — a request that genuinely failed: THAT is the machine service's sentence, and it stays.
  const failed = await renderCard({}, { status: 503 });
  check("a failed request is still named as the machine's",
    failed.html.includes("לא ניתן לקרוא את מצב החשמל") && failed.html.includes("שירות «מכונה»"),
    failed.html.slice(0, 200));

  console.log(bad ? `\n${bad} failing` : "\n0 failing");
  process.exit(bad ? 1 : 0);
};
await run();
