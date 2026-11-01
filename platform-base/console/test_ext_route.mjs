#!/usr/bin/env node
/* test_ext_route.mjs — the address a window on an app's own host loads, and the deep link it writes.
 *
 *     node platform-base/console/test_ext_route.mjs
 *
 * A link that OPENS the app but not the screen it names looks like a link that works, so this is the
 * half of the fix that can be held without a browser. The live half (the console opened on a deep
 * link, in desktop mode) is `scripts/refactor/console-deeplink-lint.py --live`.
 *
 * The failure this guards, measured 2026-10-08 (DGO-11): `#/m/project-pln/bina/projects/<id>/issues/<id>`
 * — the link the office's own task tool hands the owner — opened Plane at its home screen in desktop
 * mode, because openExternal() never received the route, and the address bar of that window read
 * `#/m/ext:project-pln`, which names no module and teleported the next load to the first tile.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const win = {};
new Function("window", fs.readFileSync(path.join(HERE, "static/ext-route.js"), "utf8"))(win);
const { framedUrl, deepLink } = win.BinaExtRoute;

let bad = 0;
const check = (name, got, want) => {
  const ok = String(got) === String(want);
  if (!ok) bad++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : `\n        got  ${got}\n        want ${want}`}`);
};

const ORIGIN = "http://plane.console.localhost:8080";
const ROUTE = "/bina/projects/e13492c5-ae57-4c34-8cd2-85e4aa65bab9/issues/6a181c8d-521d-4e6c-b995-49ff81311fd6";

check("the work item the link named is the address the frame loads",
  framedUrl(ORIGIN, ROUTE), ORIGIN + ROUTE);
check("no route is the app's own home", framedUrl(ORIGIN, ""), ORIGIN);
check("a route that is only a query survives", framedUrl(ORIGIN, "?v=1"), ORIGIN + "?v=1");
check("the address bar names the MODULE, never ext:<id>",
  deepLink("project-pln", "ext:project-pln", ROUTE), "#/m/project-pln" + ROUTE);
check("a window that names no module keeps its own id",
  deepLink("", "ext:https://n8n.example", ""), "#/m/ext:https://n8n.example");
check("a module with no route is the module alone", deepLink("project-pln", "ext:project-pln", ""), "#/m/project-pln");

// …and the console must actually USE them: a fix that lands in ext-route.js while desktop.js keeps
// composing addresses by hand is a fix nothing reaches.
const desktop = fs.readFileSync(path.join(HERE, "static/desktop.js"), "utf8");
const check2 = (name, ok) => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"}  ${name}`); };
check2("desktop.js frames an app's own host through BinaExtRoute.framedUrl",
  /const extSrc = w => BinaExtRoute\.framedUrl\(/.test(desktop)
  && /frame\.src\s*=\s*extSrc\(w\)/.test(desktop));
check2("desktop.js writes its address bar through BinaExtRoute.deepLink",
  /BinaExtRoute\.deepLink\(/.test(desktop));
check2("no path frames an own-host window by its bare url",
  !/frame\.src\s*=\s*w\.ext\.url/.test(desktop));
check2("the inner route reaches the window that opens",
  /openExternal\(\{[^}]*route:\s*rest/.test(desktop));

console.log(bad ? `\n${bad} failed` : "\nall passed");
process.exit(bad ? 1 : 0);
