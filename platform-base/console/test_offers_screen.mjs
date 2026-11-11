#!/usr/bin/env node
/* test_offers_screen.mjs — which apps of app-management's list the screen search offers as screens.
 *
 *     node platform-base/console/test_offers_screen.mjs
 *
 * The failure this guards (DGO-1760, the owner from his phone on Exampleu's office, 2026-11-09: «למה יש שתי
 * אפלקציות כניסה ? כפל זה חמור»): ⌘K listed «זהות וכניסה (Go)» (forward-auth) and «שער הכניסה» (traefik) as
 * screens. Each is a service with a host on routing[0] and no declared screen; app-management gave it a launch
 * url, and the search offered every app with one. Now app-management says `launch.screen`, and the search takes
 * only a declared screen — while a list from an app-management before that field is read exactly as before.
 * The function is read out of static/app.js itself, so the test holds the shipped filter, not a copy.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(HERE, "static/app.js"), "utf8");
const m = src.match(/^function offersScreen\(a, known\) \{[\s\S]*?^\}$/m);
if (!m) { console.log("FAIL  static/app.js has no `function offersScreen(a, known)`"); process.exit(1); }
const offersScreen = new Function(`${m[0]}; return offersScreen;`)();

let bad = 0;
const check = (name, got, want) => {
  const ok = got === want;
  if (!ok) bad++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : `  (got ${got}, want ${want})`}`);
};
const known = new Set(["drive", "mailview"]);
const app = (id, launch, enabled = true) => ({ id, enabled, launch });

check("a service with a host and no screen (forward-auth) is not a screen",
  offersScreen(app("forward-auth", { url: "https://signin.x", module: "forward-auth", screen: false }), known), false);
check("traefik, the same", offersScreen(app("traefik", { url: "https://traefik.x", module: "traefik", screen: false }), known), false);
check("a declared screen on its own host (authentik, embed false) is offered",
  offersScreen(app("authentik", { url: "https://auth.x", module: "authentik", screen: true, embed: false }), known), true);
check("an older app-management's list (no `screen`) is read as before",
  offersScreen(app("openhands", { url: "https://openhands.x", module: "openhands" }), known), true);
check("an app that is already a tile is not offered twice",
  offersScreen(app("drive", { url: "https://drive.x", module: "drive", screen: true }), known), false);
check("…nor by its module's id", offersScreen(app("mail", { url: "https://mail.x", module: "mailview", screen: true }), known), false);
check("an app that is off is not offered", offersScreen(app("portainer", { url: "https://p.x", module: "portainer", screen: true }, false), known), false);
check("an app with no launch is not offered", offersScreen(app("lib", null), known), false);
check("nothing at all is not offered", offersScreen(null, known), false);

console.log(bad ? `\n${bad} FAILED` : "\nall pass");
process.exit(bad ? 1 : 0);
