#!/usr/bin/env node
/* test_bottom_nav.mjs — which apps get a place in the phone's bar, and who decides.
 *
 *     node platform-base/console/test_bottom_nav.mjs
 *
 * The bar named four layer-3 apps by their ids in the console's own code (files, mail, chat and INDOX, in
 * buildBottomNav) — a base app naming the apps above it (DGO-1800, reading 02). Now an app ASKS for the place
 * (`routing[].module.tab: true`, carried by the compiler onto its tile) and the console reads the declaration.
 * DGO-2122: the bar is five at most — «בית», three apps, «פתוחים» (no «עוד») — in the HOME's order (its groups,
 * GROUPS, with the four old words read as their new ones), one place per kind of app, as the home has one tile per
 * kind. This runs the SHIPPED functions, lifted out of static/app.js, over a set of tiles, and reads the bar built.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(HERE, "static/app.js"), "utf8");
// a top-level function, whole, by its name — or nothing
const fnOf = (name) => {
  const start = src.indexOf(`function ${name}(`);
  const end = start < 0 ? -1 : src.indexOf("\n}\n", start);
  return start < 0 || end < 0 ? "" : src.slice(start, end + 2);
};
// a top-level `const` on one line, by its name — or nothing
const constOf = (name) => (src.match(new RegExp(`^const ${name} = .*;$`, "m")) || [""])[0];
// what buildBottomNav reads, from the same file — no stand-in: if any is gone, the console's boot throws, and so must this
const parts = {
  BOTTOM_PICKS: constOf("BOTTOM_PICKS"), GROUPS: constOf("GROUPS"), GROUP_HUE: constOf("GROUP_HUE"),
  GROUP_WAS: constOf("GROUP_WAS"), groupOf: fnOf("groupOf"), kindOf: constOf("kindOf"), ownHerd: constOf("ownHerd"),
  remoteInfo: fnOf("remoteInfo"), rather: fnOf("rather"), homeModel: fnOf("homeModel"), homeTiles: constOf("homeTiles"),
  buildBottomNav: fnOf("buildBottomNav"),
};
const missing = Object.keys(parts).filter((k) => !parts[k]);
if (missing.length) {
  console.log(`FAIL  static/app.js has no top-level ${missing.join(", ")}`);
  process.exit(1);
}

// The shipped code over a set of tiles: `run` is what to evaluate after it (the bar it builds, or the home's model).
function shipped(MODULES, run) {
  let bar = null;
  const el = (tag, cls, html = "") => ({ tag, cls, html, dataset: {}, title: "", href: "", children: [], attrs: {},
                                        appendChild(c) { this.children.push(c); return c; },
                                        setAttribute(k, v) { this.attrs[k] = String(v); } });
  const document = { querySelector: () => null, body: { appendChild: (b) => { bar = b; } } };
  const out = new Function("MODULES", "el", "document", "mIcon", "esc", "remoteCls", "remoteTip", "location",
               "renderSwitcher", "openPalette", `${Object.values(parts).join("\n")}\nreturn (${run})();`)(
    MODULES, el, document, () => "", (s) => String(s), () => "", () => "", {}, () => {}, () => {});
  return run.includes("buildBottomNav") ? bar : out;
}
const build = (MODULES) => shipped(MODULES, "() => buildBottomNav()");
const model = (MODULES) => shipped(MODULES, "() => homeModel()");
const picks = (MODULES) => build(MODULES).children.map((c) => c.dataset.id).filter((id) => id !== undefined && id !== "");

let bad = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) bad++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : `\n        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`}`);
};

// The tiles are made up (`t-…`): this test is about the console, which must name no app — its fixtures do not either
// (app-coupling-lint reads .mjs files). The one case about the OLD list builds its names from one string.
const T = (id, extra = {}) => ({ id, name: id, icon: "x", group: "ניהול העסק", ...extra });

check("the apps that declare `tab`, in the home's order, at most three",
  picks([T("t-docs", { tab: true }), T("t-files", { tab: true }), T("t-rec"), T("t-post", { tab: true }),
         T("t-talk", { tab: true })]),
  ["t-docs", "t-files", "t-post"]);
check("the home's order is group by group, as the home draws it, not the tiles' order alone",
  picks([T("t-infra", { group: "פיתוח ואוטומציות", tab: true, order: 0 }), T("t-post", { group: "תקשורת", tab: true, order: 3 }),
         T("t-main", { group: "בינה מלאכותית", tab: true, order: 9 })]),
  ["t-main", "t-post", "t-infra"]);
check("an office that has not taken the release says one of the four old words: each is read as its new group",
  picks([T("t-old-infra", { group: "תשתית", tab: true }), T("t-old-main", { group: "ראשי", tab: true }),
         T("t-new-ai", { group: "בינה מלאכותית", tab: true })]),
  ["t-new-ai", "t-old-main", "t-old-infra"]);
const OLD_FOUR = "drive mail chat incoming".split(" ");   // the ids the console used to name
check("an app named like one of the old four, that does not declare it, gets no place",
  picks([...OLD_FOUR.map((id) => T(id)), T("t-notes", { tab: true })]),
  ["t-notes"]);
check("`tab` must be true itself — a word or 1 is not a declaration",
  picks([T("t-a", { tab: "true" }), T("t-b", { tab: 1 }), T("t-c", { tab: true })]),
  ["t-c"]);
check("a linked office's tile that carries no `tab` gets no place",
  picks([T("t-files.other-office", { remote: { office: "other-office" } }), T("t-post", { tab: true })]),
  ["t-post"]);
check("a linked tile of this business's herd that carries `tab` — the compiler gives it when its app asks, on THIS office's manifest (DGO-2122) — takes its place in the home's order",
  picks([T("t-docs.hp", { tab: true, remote: { office: "hp", herd: true } }), T("t-post", { tab: true }),
         T("t-talk", { group: "תקשורת", tab: true }), T("t-more", { group: "תקשורת", tab: true })]),
  ["t-docs.hp", "t-post", "t-talk"]);
check("one place per kind: this office's own copy, not another machine of the herd's (both ask for it)",
  picks([T("t-docs.hp", { alias: "t-docs", tab: true, remote: { office: "hp", herd: true } }), T("t-docs", { alias: "t-docs", tab: true })]),
  ["t-docs"]);
check("another business's office is never in the bar, even when its tile asks",
  picks([T("t-shop.client", { alias: "t-shop", tab: true, remote: { office: "client" } }), T("t-post", { tab: true })]),
  ["t-post"]);
// The home's model (DGO-2122): one tile per kind of the business's own (this office and its herd), opening this
// office's copy, else one whose office answers; every linked office, of the herd or not, with all its tiles.
const H = (id, office, extra = {}) => T(`${id}.${office}`, { alias: id, remote: { office, label: office, herd: true, ...extra } });
const kinds = (m) => m.kinds.map((e) => [e.tile.id, e.copies.length]);
const offices = (m) => m.offices.map((o) => [o.id, o.herd, o.mods.length, o.off]);
check("a kind opens this office's own copy, wherever it stands in the registry",
  kinds(model([H("t-files", "hp"), T("t-files", { alias: "t-files" }), H("t-files", "dell")])), [["t-files", 3]]);
check("…else the copy whose office answers",
  kinds(model([H("t-files", "hp", { ok: false }), H("t-files", "dell"), H("t-files", "mac")])), [["t-files.dell", 3]]);
check("…else the first in the registry's order",
  kinds(model([H("t-files", "hp", { ok: false }), H("t-files", "dell", { ok: false })])), [["t-files.hp", 2]]);
check("another business's apps are its office's, never the home's kinds",
  [kinds(model([T("t-files", { alias: "t-files" }), T("t-shop.client", { alias: "t-shop", remote: { office: "client" } })])),
   offices(model([T("t-shop.client", { alias: "t-shop", remote: { office: "client", label: "c", ok: false } }), H("t-files", "hp")]))],
  [[["t-files", 1]], [["client", false, 1, true], ["hp", true, 1, false]]]);
const empty = build([T("t-a"), T("t-b")]);
check("no app declares it: the bar is «בית» and «פתוחים», and no «עוד»",
  [empty.children.length, empty.children.map((c) => c.dataset.id)], [2, ["", undefined]]);
const full = build(["a", "b", "c", "d", "e"].map((id) => T(`t-${id}`, { tab: true })));
check("five at most, «בית» first", [full.children.length, full.children[0].dataset.id, full.children[0].href], [5, "", "#/"]);
check("the bar is the page's main navigation, by name", [full.tag, full.attrs["aria-label"]], ["nav", "ניווט ראשי"]);

console.log(`test_bottom_nav: ${bad ? bad + " FAILED" : "ok"}`);
process.exit(bad ? 1 : 0);
