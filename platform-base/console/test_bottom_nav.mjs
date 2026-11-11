#!/usr/bin/env node
/* test_bottom_nav.mjs — which apps get a place in the phone's bar, and who decides.
 *
 *     node platform-base/console/test_bottom_nav.mjs
 *
 * The bar named four layer-3 apps by their ids in the console's own code (files, mail, chat and INDOX, in
 * buildBottomNav) — a base app naming the apps above it (DGO-1800, reading 02). Now an app ASKS for the place
 * (`routing[].module.tab: true`, carried by the compiler onto its tile) and the console reads the declaration.
 * This runs the SHIPPED function, lifted out of static/app.js, over a set of tiles, and reads the bar it built.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(HERE, "static/app.js"), "utf8");
const start = src.indexOf("function buildBottomNav() {");
const end = src.indexOf("\n}\n", start);
if (start < 0 || end < 0) {
  console.log("FAIL  buildBottomNav() is not in static/app.js");
  process.exit(1);
}
const fn = src.slice(start, end + 2);
// the two constants the function reads, from the same file — no stand-in: if either is gone, the console's boot
// throws, and so must this
const picksConst = (src.match(/^const BOTTOM_PICKS = \d+;/m) || [""])[0];
const groupsConst = (src.match(/^const GROUPS = \[[^\]]*\];/m) || [""])[0];
if (!picksConst || !groupsConst) {
  console.log(`FAIL  static/app.js has no ${picksConst ? "GROUPS" : "BOTTOM_PICKS"} at the top level`);
  process.exit(1);
}

function build(MODULES) {
  let bar = null;
  const el = (tag, cls, html = "") => ({ tag, cls, html, dataset: {}, title: "", children: [],
                                        appendChild(c) { this.children.push(c); return c; } });
  const document = { querySelector: () => null, body: { appendChild: (b) => { bar = b; } } };
  new Function("MODULES", "el", "document", "mIcon", "esc", "remoteInfo", "remoteCls", "remoteTip", "location",
               "renderSwitcher", "openPalette", `${picksConst}\n${groupsConst}\n${fn}\nbuildBottomNav();`)(
    MODULES, el, document, () => "", (s) => String(s), (m) => m.remote || null, () => "", () => "", {}, () => {}, () => {});
  return bar.children.map((c) => c.dataset.id).filter((id) => id !== undefined && id !== "");
}

let bad = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) bad++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : `\n        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`}`);
};

// The tiles are made up (`t-…`): this test is about the console, which must name no app — its fixtures do not either
// (app-coupling-lint reads .mjs files). The one case about the OLD list builds its names from one string.
const T = (id, extra = {}) => ({ id, name: id, icon: "x", group: "עסק", ...extra });

check("the apps that declare `tab`, in the rail's order",
  build([T("t-docs", { tab: true }), T("t-files", { tab: true }), T("t-rec"), T("t-post", { tab: true }),
         T("t-talk", { tab: true })]),
  ["t-docs", "t-files", "t-post", "t-talk"]);
check("the rail's order is group by group, as the rail draws it, not the tiles' order alone",
  build([T("t-infra", { group: "תשתית", tab: true, order: 0 }), T("t-post", { tab: true, order: 3 }),
         T("t-main", { group: "ראשי", tab: true, order: 9 })]),
  ["t-main", "t-post", "t-infra"]);
const OLD_FOUR = "drive mail chat incoming".split(" ");   // the ids the console used to name
check("an app named like one of the old four, that does not declare it, gets no place",
  build([...OLD_FOUR.map((id) => T(id)), T("t-notes", { tab: true })]),
  ["t-notes"]);
check("at most four, the first four in the rail",
  build(["a", "b", "c", "d", "e"].map((id) => T(`t-${id}`, { tab: true }))),
  ["t-a", "t-b", "t-c", "t-d"]);
check("`tab` must be true itself — a word or 1 is not a declaration",
  build([T("t-a", { tab: "true" }), T("t-b", { tab: 1 }), T("t-c", { tab: true })]),
  ["t-c"]);
check("a linked office's `remote:` tile, which carries no `tab`, gets no place",
  build([T("t-files.other-office", { remote: { office: "other-office" } }), T("t-post", { tab: true })]),
  ["t-post"]);
check("no app declares it: the bar is «בית», «פתוחים», «עוד» only", build([T("t-a"), T("t-b")]), []);

console.log(`test_bottom_nav: ${bad ? bad + " FAILED" : "ok"}`);
process.exit(bad ? 1 : 0);
