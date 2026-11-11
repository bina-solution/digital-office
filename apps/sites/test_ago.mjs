#!/usr/bin/env node
/* test_ago.mjs — «לפני …» says one of a unit as one: «לפני דקה», never «לפני 1 דקות».
 *
 *     node apps/sites/test_ago.mjs
 *
 * Seen on Exampleu's «סבב אחרון» line (2026-11-09, DGO-1502): «איסוף לפני 1 דקות». `ago()` (static/app.js) glued the
 * count to the plural; it now goes through the screen's own `one()`, like every other count there.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DIR = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(DIR, "static", "app.js"), "utf8");
const grab = (re, what) => {
  const m = src.match(re);
  if (!m) { console.log(`FAIL  ${what} is not in static/app.js`); process.exit(1); }
  return m[0];
};
const ago = new Function("ts", [
  grab(/const num = [^\n]*\n/, "num"),
  grab(/const one = [^\n]*\n/, "one"),
  grab(/function ago\(ts\) \{[\s\S]*?\n\}/, "ago"),
  "return ago(ts);",
].join("\n"));

// One clock for the whole test: `ago()` reads Date.now() at each call, and a second that ticks over between it and
// `now` turned «119 s» into «120 s» (batch 39's proof, 2026-11-11: «got "לפני 2 דקות", want "לפני דקה"»).
const T = Date.now();
Date.now = () => T;
const now = Math.floor(Date.now() / 1000);
let failed = 0;
for (const [ts, want] of [
  [0, "—"], [now - 1, "לפני שנייה"], [now - 47, "לפני 47 שניות"],
  [now - 60, "לפני דקה"], [now - 119, "לפני דקה"], [now - 120, "לפני 2 דקות"],
  [now - 3600, "לפני שעה"], [now - 7300, "לפני 2 שעות"], [now - 86400, "לפני יום"], [now - 3 * 86400, "לפני 3 ימים"],
]) {
  const got = ago(ts);
  if (got !== want) failed++;
  console.log(`${got === want ? "PASS" : "FAIL"}  ${now - ts} s ago: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
}
console.log(failed ? `${failed} FAILED` : "ago: all passed");
process.exit(failed ? 1 : 0);
