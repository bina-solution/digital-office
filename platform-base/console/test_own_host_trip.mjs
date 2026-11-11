#!/usr/bin/env node
/* test_own_host_trip.mjs — a console whose nested names RESOLVE takes the sign-in trip; one whose do not, does not.
 *
 *     node platform-base/console/test_own_host_trip.mjs
 *
 * Two offices fixed this trip on the same day, and the merge of dgo-stable into mac-dgo (2026-11-10) keeps both:
 *   - DGO-1594 (dgo-stable): an app of THIS office behind the office's sign-in. On a `.localhost` console the n8n tile
 *     drew «the office is open at a numeric address» with nothing to press, because `leaveFor` refused every trip on a
 *     console `noNestedHost` names. Its second reader added: on a bare service name (`console:8000`) or an address
 *     (`http://192.168.16.102:8080`) the trip would be a top-level load of `n8n.console:8000` — «This site can't be
 *     reached» in place of the whole shell (measured 2026-11-02: `bina.hp-laptop.console:8000`).
 *   - DGO-1502 (mac-dgo; the owner: «שכל האפלקציות יפתחו גם בתוך הלשכה ולא רק בחוץ כמו שפגישות עכשו עושה לפעמים»):
 *     a LINKED office's app on its own host (Meet on vps1, Plane on the HP) is framed at `<alias>.<office>.<console
 *     host>`; on the Mac's and the HP's own consoles — `console.localhost`, whose nested names the browser answers
 *     itself — such a tile had become a card with nothing to press.
 * So the trip is refused only where the name cannot be LOOKED UP — a bare service name or an address — for this
 * office's app and a linked office's alike. What is provable without a browser is the DECISION: the predicates are
 * pure, so they are read out of app.js and run here; the live half is the console itself.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DIR = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(DIR, "static", "app.js"), "utf8");
const fn = (name) => {
  const m = src.match(new RegExp(`function ${name}\\(([\\s\\S]*?)\\n\\}`));
  if (!m) { console.log(`FAIL  ${name} is not in static/app.js`); process.exit(1); }
  return m[0];
};
const pure = (name) => new Function("hostname",
  `${fn("localhostFamily")}\n${fn("noNestedHost")}\n${fn("noNestedName")}\nreturn ${name}(hostname);`);
const localhostFamily = pure("localhostFamily");
const noNestedHost = pure("noNestedHost");
const noNestedName = pure("noNestedName");

let failed = 0;
const check = (what, got, want) => {
  const ok = got === want;
  if (!ok) failed++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${what}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
};

// [hostname, localhost family, nested host unusable in a FRAME (noNestedHost), nested NAME unresolvable (noNestedName)]
for (const [host, family, frame, name] of [
  ["console.localhost", true, true, false],          // the Mac's / the HP's own console: the trip is a sign-in
  ["localhost", true, true, false],
  ["CONSOLE.LOCALHOST", true, true, false],
  ["console", false, true, true],                    // the office browser's `console:8000`: a DNS failure
  ["10.79.7.1", false, true, true],                  // an address has no names under it
  ["192.168.16.102", false, true, true],             // the office-routes LAN door
  ["::1", false, true, true],
  ["fd00::1", false, true, true],
  ["console.exampleu.digital-office.co.il", false, false, false],   // a real domain frames its own host directly
]) {
  check(`localhostFamily(${host})`, localhostFamily(host), family);
  check(`noNestedHost(${host})`, noNestedHost(host), frame);
  check(`noNestedName(${host})`, noNestedName(host), name);
}

// the trip and the card that stands for a refused trip both read the NAME answer, never the wider frame answer —
// and no longer tell this office's app from a linked one's: both resolve where the name resolves
const leave = fn("leaveFor");
check("leaveFor refuses only where the name cannot be looked up", /if \(NO_NESTED_NAME\) return false;/.test(leave), true);
check("leaveFor says whether the browser is on its way", /location\.assign\(url\);\s*return true;/.test(leave), true);
check("leaveFor does not consult the wider frame answer", /NO_NESTED_HOST/.test(leave), false);
check("enterOwnHost hands back leaveFor's answer", /return leaveFor\(enterUrl\(m\)\);/.test(fn("enterOwnHost")), true);
const open = fn("openOwnHost");
check("openOwnHost: a trip on its way is the answer", /state === "signin" && enterOwnHost\(m\)\) return;/.test(open), true);
check("openOwnHost's «address» card follows the same name answer",
      /state === "signin" && NO_NESTED_NAME\) \{\s*(\/\/[^\n]*\n\s*)*renderExternalNotice\(m, url, "address"\)/.test(open), true);
check("NO_NESTED_NAME is THIS console's hostname's answer",
      /const NO_NESTED_NAME = noNestedName\(location\.hostname\);/.test(src), true);

console.log(failed ? `${failed} FAILED` : "own-host trip: all passed");
process.exit(failed ? 1 : 0);
