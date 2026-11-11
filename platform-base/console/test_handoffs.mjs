#!/usr/bin/env node
/* test_handoffs.mjs — an app that needs a person in another app's screen gets him there, and back.
 *
 *     node platform-base/console/test_handoffs.mjs
 *
 * The failure this guards, measured 2026-11-04 (the owner, «זה לא עובד לא פותח לי שום דפדפן», DGO-1336):
 * he pressed «Continue with Google» in the HP's Claude tile on his phone, Google's account chooser opened
 * in the office browser's own display, and the screen in front of him went on showing «Sign In» — nothing
 * told it to change tiles. `decide` is the whole rule static/handoffs.js runs every few seconds.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const win = {};
new Function("window", fs.readFileSync(path.join(HERE, "static/handoffs.js"), "utf8"))(win);
const { decide } = win.BinaHandoffs;

let bad = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) bad++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : `\n        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`}`);
};

const CLAUDE = "bina-claude.hp-laptop", B42 = "browser42.hp-laptop";
const FROM = "#/m/" + CLAUDE, THERE = "#/m/" + B42 + "/handoff/claude-signin";
const h = (state, id = "e1", extra = {}) => ({ at: B42, for: CLAUDE, slug: "claude-signin", state, id, age: 3,
                                              sentence: state === "failed" ? "Google לא ענה" : "", ...extra });
const empty = { acted: [], trip: null };

// 1. A sign-in needed for the tile he is looking at: he is taken to the browser, once.
let r = decide([h("needed")], CLAUDE, FROM, empty);
check("needed for the tile in front → switch to the hand-off", r.action, { go: THERE });
const trip = r.memory;
r = decide([h("needed")], B42, THERE, trip);
check("…and while it is needed, nothing more", r.action, null);
r = decide([h("needed")], CLAUDE, FROM, { ...trip, trip: null });
check("a person who walked away from it is not pulled back (the episode is handled)", r.action, null);

// 2. Done while he is still there: back to where he came from.
r = decide([h("done")], B42, THERE, trip);
check("done while on the browser → back to the app", r.action, { back: FROM });
check("…and the trip is over", r.memory.trip, null);
r = decide([h("done")], "drive", "#/m/drive", trip);
check("done after he went elsewhere → he is left where he is", r.action, null);

// 3. Failed: back, and the sentence on top — or only the sentence when nobody was switched.
r = decide([h("failed")], B42, THERE, trip);
check("failed while on the browser → back, with the sentence", r.action, { back: FROM, say: "Google לא ענה" });
r = decide([h("failed", "e2")], CLAUDE, FROM, empty);
check("failed before any switch, for the tile in front → the sentence alone, once", r.action, { say: "Google לא ענה" });
r = decide([h("failed", "e2")], CLAUDE, FROM, r.memory);
check("…not twice", r.action, null);

// 4. Nobody is switched for somebody else's tile, and a record that is gone ends the trip quietly.
r = decide([h("needed")], "drive", "#/m/drive", empty);
check("needed for another tile → nothing", r.action, null);
r = decide([], B42, THERE, trip);
check("the record is gone → the trip ends, nothing moves", [r.action, r.memory.trip], [null, null]);

// 5. The app asked again (a new episode of the same slug replaced the record): the trip follows it.
r = decide([h("needed", "e9")], B42, THERE, trip);
check("a retry in the same place keeps the way back", [r.action, r.memory.trip && r.memory.trip.id], [null, "e9"]);
r = decide([h("done", "e9")], B42, THERE, r.memory);
check("…and its done still brings him back", r.action, { back: FROM });
// 5b. He walked back to the app while e1 was still needed, and pressed «Continue with Google» AGAIN (the
//     second reader's blocker): the new episode takes him to the browser again, with the way back he has now.
const walkedBack = decide([h("needed")], CLAUDE, FROM + "?again", trip);
check("walking back alone is respected — no new press, no switch", walkedBack.action, null);
r = decide([h("needed", "e2")], CLAUDE, FROM + "?again", walkedBack.memory);
check("a second press from the app tile switches him again", r.action, { go: THERE });
check("…remembering where he pressed it", r.memory.trip.from, FROM + "?again");
r = decide([h("done", "e2")], B42, THERE, r.memory);
check("…and its done brings him back there", r.action, { back: FROM + "?again" });

// 5c. A failure nobody was switched for is news only while it is fresh.
check("an old failure greets nobody in a tab opened later", decide([h("failed", "e7", { age: 400 })], CLAUDE, FROM, empty).action, null);

// 5d. THE DESKTOP (DGO-1434): the tiles in view are the address's tile first, then every open window. A
//     press inside a window on its own host moves neither the address nor the focus, so the address may
//     name another app while the Claude window is open and asking.
const DESK = ["drive", CLAUDE];
r = decide([h("needed", "d1")], DESK, "#/m/drive", empty);
check("desktop: needed for an open window the address does not name → switch to the hand-off", r.action, { go: THERE });
check("…and «back» is the asking app's own tile, not the address he happened to be on", r.memory.trip.from, FROM);
r = decide([h("done", "d1")], [B42, "drive", CLAUDE], THERE, r.memory);
check("desktop: done while the browser's window is open → back to the asking app", r.action, { back: FROM });
r = decide([h("needed", "d2")], ["drive"], "#/m/drive", empty);
check("desktop: needed for an app with no open window → nothing", r.action, null);
r = decide([h("needed", "d3")], ["", CLAUDE], "", empty);
check("desktop with no address at all (a window opened from the dock) → switch", r.action, { go: THERE });

// 5e. Where he WORKS decides «back», not what he can see (the second reader of DGO-1434): on the desktop the
//     browser's window stays open and in view, so the shell says the focused window as `front`.
const W1 = decide([h("needed", "w1")], { front: CLAUDE, seen: [CLAUDE, "drive"], addressed: "drive" }, "#/m/drive", empty);
check("desktop: needed for the focused window → switch", W1.action, { go: THERE });
check("…and «back» is the asking tile, the address having named another", W1.memory.trip.from, FROM);
r = decide([h("done", "w1")], { front: "drive", seen: ["drive", B42, CLAUDE], addressed: "drive" }, "#/m/drive", W1.memory);
check("desktop: done while he works in another window → nothing moves", r.action, null);
check("…but the trip ends, and says how (the marks on the windows go)", [r.memory.trip, r.ended && r.ended.how], [null, "done"]);
r = decide([h("done", "w1")], { front: B42, seen: [B42, CLAUDE], addressed: B42 }, THERE, W1.memory);
check("desktop: done while on the browser's window → back to the asking app", [r.action, r.ended && r.ended.how], [{ back: FROM }, "done"]);
r = decide([h("needed", "w2")], { front: CLAUDE, seen: [CLAUDE, B42], addressed: B42 }, THERE, W1.memory);
check("desktop: a second press from the app's window switches again, though the address still names the browser", r.action, { go: THERE });
check("…with the way back to the app's tile", r.memory.trip.from, FROM);
r = decide([h("needed", "p1")], { front: CLAUDE, seen: [], addressed: CLAUDE }, FROM + "/inner", empty);
check("phone (the shell's own input): back keeps the inner route he pressed from", [r.action, r.memory.trip.from], [{ go: THERE }, FROM + "/inner"]);
check("…and the trip carries the app's sentence for the way back", r.memory.trip.sentence, "");
r = decide([], B42, THERE, trip);
check("a record that is gone ends the trip, and says so", r.ended && r.ended.how, "gone");

// 5f. Another app asks while a trip still waits — an errand left open must never block every other app (the
//     second reader of DGO-1434): the newer ask wins, and the old trip ends as `replaced`.
const MAIL = "mail.hp-laptop";
const hm = (state, id) => ({ at: B42, for: MAIL, slug: "mail-signin", state, id, age: 1, sentence: "" });
const T1 = decide([h("needed", "s1")], CLAUDE, FROM, empty).memory;
r = decide([h("needed", "s1"), hm("needed", "m1")], { front: MAIL, seen: [MAIL, CLAUDE, B42], addressed: MAIL }, "#/m/" + MAIL, T1);
check("another app in view asks while the first trip waits → the new ask wins, the old trip is replaced",
      [r.action, r.ended && r.ended.how, r.ended && r.ended.trip.for, r.memory.trip && r.memory.trip.for],
      [{ go: "#/m/" + B42 + "/handoff/mail-signin" }, "replaced", CLAUDE, MAIL]);
r = decide([h("needed", "s1"), hm("needed", "m1")], { front: B42, seen: [B42], addressed: B42 }, THERE, T1);
check("…but an app he cannot see does not take him away", [r.action, r.ended], [null, null]);
r = decide([h("needed", "s1"), hm("needed", "m1")], { front: B42, seen: [B42, CLAUDE, MAIL], addressed: B42 }, THERE, T1);
check("…nor one that asks while he is working in the browser for the first (a window in view on a flank)", [r.action, r.ended], [null, null]);

// 6. What the list may not be.
check("no list → nothing", decide(null, CLAUDE, FROM, empty).action, null);
check("a record without an id is not an episode", decide([{ ...h("needed"), id: "" }], CLAUDE, FROM, empty).action, null);

// 7. THE PLACEMENT RULE (DGO-1434): the app keeps its side and gives up half, the browser takes the other
//    half, neither over the other — and neither centre in a flank, where desktop.js would shrink it.
const { beside } = win.BinaHandoffs;
const Z = { W: 1440, top: 48, bottom: 812 };
const edges = (q) => [q.cx - q.w / 2, q.cx + q.w / 2];
const L = beside({ cx: 400 }, Z), R = beside({ cx: 1100 }, Z);
check("an app on the left keeps the left half, the browser takes the right", [L.app.cx < Z.W / 2, L.bro.cx > Z.W / 2], [true, true]);
check("…the two never overlap, and both stay on the screen", [edges(L.app)[1] <= edges(L.bro)[0], edges(L.app)[0] >= 0, edges(L.bro)[1] <= Z.W], [true, true, true]);
check("an app on the right keeps the right half — the same two halves, mirrored", [R.app.cx, R.bro.cx], [L.bro.cx, L.app.cx]);
check("with no window that asked, the browser still gets its half", !!(beside(null, Z) || {}).bro, true);
for (const W of [1024, 1199, 1440, 1920, 2560]) {
  // desktop.js computeGeom: the flank is F wide on each side; a centre outside [F, W − F] is shrunk
  const F = Math.max(200, Math.round(W * (0.18 + 0.07 * Math.max(0, Math.min(1, (W - 1440) / 1120)))));
  const p = beside({ cx: 0 }, { W, top: 48, bottom: 800 });
  check(`at ${W}px both centres are in the focus zone, the halves apart`, [p.app.cx >= F, p.bro.cx <= W - F, edges(p.app)[1] <= edges(p.bro)[0]], [true, true, true]);
}
check("a zone that is not one → no placement", beside({ cx: 1 }, { W: 0, top: 0, bottom: 0 }), null);

if (bad) { console.log(`\n${bad} FAILED`); process.exit(1); }
console.log("\nall hand-off rules hold");
