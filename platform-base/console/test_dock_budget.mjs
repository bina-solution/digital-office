#!/usr/bin/env node
/* test_dock_budget.mjs — the dock's capacity arithmetic, without a browser.
 *
 *     node platform-base/console/test_dock_budget.mjs
 *
 * The bug this guards (`issues/console-desktop-dock-overflows-its-pill-and-hides-17-apps.yaml`) was
 * a *number* problem — 2189px of tiles against a 1254px pill — so it is provable without rendering:
 * what has to hold is that the tiles the dock may draw FIT, at every width, for every count. The
 * measurement against a live console is `scripts/ui-coverage/dock-fit.py`; this is the part of it
 * that can run anywhere, in a second.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(HERE, "static/dock-budget.js"), "utf8");
const win = {};
new Function("window", "globalThis", src)(win, win);
const { DOCK, resolveDock, dockRoom } = win.BinaDockBudget;

let bad = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) bad++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : `\n        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`}`);
};

/** width of a row of `n` tiles, plus the divider the dock always draws */
const width = (n) => n * DOCK.tile + (n - 1) * DOCK.gap + DOCK.pad + DOCK.sep;

// ── the arithmetic the design specifies ────────────────────────────────────────────────────────
// available = viewport - 40 (the pill's own `max-width: calc(100vw - 40px)`)
const avail = (vw) => vw - 40;
check("1294 · 40 tiles → 22 slots, a door is needed",
  resolveDock({ available: avail(1294), count: 40 }), { slots: 22, showMore: true });
check("1440 · 40 tiles → 25 slots, a door is needed",
  resolveDock({ available: avail(1440), count: 40 }), { slots: 25, showMore: true });
check("1920 · 40 tiles → 34 slots, a door is needed",
  resolveDock({ available: avail(1920), count: 40 }), { slots: 34, showMore: true });
check("2560 · 40 tiles fit — today's good behaviour, no door",
  resolveDock({ available: avail(2560), count: 40 }), { slots: 41, showMore: false });

// ── the property that makes the bug impossible, at every width and count ───────────────────────
for (let vw = 1024; vw <= 4000; vw += 7) {
  for (const count of [0, 1, 2, 3, 17, 40, 41, 80, 240]) {
    const b = resolveDock({ available: avail(vw), count });
    // what the dock actually draws: the app tiles + the desk's own 2 + the door when there is one
    const fixed = 2;
    const room = b.showMore ? dockRoom(b, b.slots, fixed) : count - fixed;
    const drawn = Math.max(0, room) + fixed + (b.showMore && count > fixed ? 1 : 0);
    if (drawn > b.slots || width(b.slots) > avail(vw) + 1) {
      bad++;
      console.log(`FAIL  ${vw}px · ${count} tiles: draws ${drawn} into ${b.slots} slots (${width(b.slots)}px of ${avail(vw)}px)`);
    }
  }
}
console.log(`PASS  every width 1024–4000 × counts 0…240: the row fits its slots`);

// ── the door is never drawn for nothing, and never becomes the whole dock ──────────────────────
check("a dock that fits everything draws no door",
  resolveDock({ available: avail(2560), count: 30 }).showMore, false);
check("the floor keeps 3 slots even on an absurd width",
  resolveDock({ available: 10, count: 40 }).slots, 3);
check("with the floor reached, at least one app tile is still drawn",
  dockRoom(resolveDock({ available: 10, count: 40 }), 3, 2), 1);
check("count 0 is a valid dock (nothing to show, nothing to hide)",
  resolveDock({ available: avail(1294), count: 0 }), { slots: 3, showMore: false });

console.log(bad ? `\n${bad} failing` : "\n0 failing");
process.exit(bad ? 1 : 0);
