#!/usr/bin/env node
/* readiness-selftest — the words a card says about another office, executed.

   `static/readiness.js` is the whole of what a person reads on a linked office's card about whether
   it can OPEN what this one sends it. Three things must hold, and each has failed somewhere before in
   this office's screens:

     · every state has a WORD — a missing one renders "undefined" next to another office's name,
       which is worse than saying nothing;
     · the colour follows the reason: green only for "it has the code", amber for "an update there",
       red for "the link or the sharing" — a red pill over a healthy link is what sends an owner to
       debug a tunnel that works;
     · the office's own words are ESCAPED (a label from the far side is data, not markup).

       node apps/dgo-extend/tests/readiness-selftest.mjs

   Non-zero exit on the first broken promise. Contract test: it says nothing about pixels. */
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const require = createRequire(import.meta.url);
const R = require(join(ROOT, "apps/dgo-extend/static/readiness.js"));

let fails = 0;
function ok(name, cond, detail) {
  if (cond) { console.log(`ok    ${name}`); return; }
  fails++;
  console.log(`FAIL  ${name}${detail ? `  — ${detail}` : ""}`);
}

// ── every state has a word, and only "ok" is green ───────────────────────────────────────────────
for (const [state, word] of [["ok", "נפתח במלואו"], ["old", "דורש עדכון אצלה"],
                             ["down", "לא עונה"], ["none", "לא משותף"]]) {
  ok(`${state}: has a word`, R.word(state) === word, R.word(state));
  ok(`${state}: a colour`, ["ok", "warn", "bad"].includes(R.cls(state)), R.cls(state));
}
ok("only ok is green", R.cls("ok") === "ok" && R.cls("old") !== "ok" &&
   R.cls("down") !== "ok" && R.cls("none") !== "ok");
ok("an update is amber, not red (the link is fine)", R.cls("old") === "warn");
ok("a dead link and an unshared app are red", R.cls("down") === "bad" && R.cls("none") === "bad");

// ── a state nobody planned for renders as a word, never as "undefined" ───────────────────────────
const unknown = R.cell({ console: "brand-new-state", terminal: undefined }, String);
ok("an unknown state renders no 'undefined'", !/undefined/.test(unknown), unknown);
ok("…and says something", /קונסול: /.test(unknown) && /טרמינל: /.test(unknown));

// ── the two pills carry their own names (a person must know which is which) ─────────────────────
const good = R.cell({ console: "ok", terminal: "old" }, String);
ok("the console pill names the console", /קונסול: נפתח במלואו/.test(good), good);
ok("the terminal pill names the terminal", /טרמינל: דורש עדכון אצלה/.test(good), good);
ok("the console pill is green and the terminal amber",
   /pill ok/.test(good) && /pill warn/.test(good), good);

// ── escaping: the far side's text is data ───────────────────────────────────────────────────────
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const evil = R.cell({ console: "ok", terminal: "ok" }, (s) => esc("<" + s + ">"));
ok("the words are passed through the caller's escaping", evil.includes("&lt;") && !evil.includes("<<"),
   evil);

console.log();
if (fails) {
  console.log(`${fails} FAILED`);
  process.exit(1);
}
console.log("readiness-selftest: all checks passed");
