#!/usr/bin/env node
/* test_bina_nav — the side menu's CONTRACT, executed.

   `platform-base/bina-ui/bina-nav.js` makes one promise: an app DECLARES a menu
   (brand · primary · sections · items · search · footer) and the component builds it — the
   same doctrine as bina-table. The promise is only worth what checks it, and the ui-map can
   only photograph the apps that have adopted the component yet, so this file checks the
   component itself: it reads the shared block out of the source (the same block gate G27
   copies into every app), runs it against a minimal DOM, and asserts the STRUCTURE the
   declaration asks for.

   It is a contract test, not a browser test: it says nothing about pixels. What it catches is
   the failure this component invites — a config key that is documented, accepted, and quietly
   ignored (a badge that never renders, a "show N more" that never appears, a search that
   filters nothing), which is exactly the class of bug that makes ten apps look like ten
   different products.

       node platform-base/bina-ui/test_bina_nav.mjs

   It lives beside the component, where gate G72 (plane-tests-lint) runs every test of a plane: for
   its first months it sat in scripts/, where nothing ran it but whoever remembered to.

   Non-zero exit on the first broken promise. */

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { basename, dirname, extname, join, relative } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..", "..");
const SRC = join(ROOT, "platform-base/bina-ui/bina-nav.js");

/* ── a DOM, just enough of one ────────────────────────────────────────────── */
class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.attrs = {};
    this._cls = new Set();
    this._text = "";
    this._html = "";
    this.style = {};
    this.hidden = false;
    this.listeners = {};
    this.parentElement = null;
  }
  get className() { return [...this._cls].join(" "); }
  set className(v) { this._cls = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get classList() {
    const s = this._cls;
    return {
      add: (...c) => c.forEach((x) => s.add(x)),
      remove: (...c) => c.forEach((x) => s.delete(x)),
      contains: (c) => s.has(c),
      toggle: (c, force) => {
        const on = force === undefined ? !s.has(c) : !!force;
        if (on) s.add(c); else s.delete(c);
        return on;
      },
    };
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : k === "class" ? this.className : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  appendChild(n) { this.children.push(n); n.parentElement = this; return n; }
  insertBefore(n, ref) {
    const i = ref ? this.children.indexOf(ref) : -1;
    if (i < 0) this.children.push(n); else this.children.splice(i, 0, n);
    n.parentElement = this; return n;
  }
  remove() {
    const p = this.parentElement;
    if (p) { const i = p.children.indexOf(this); if (i >= 0) p.children.splice(i, 1); }
  }
  set innerHTML(v) { this.children = []; this._html = String(v); this._text = String(v).replace(/<[^>]*>/g, ""); }
  get innerHTML() { return this._html; }
  set textContent(v) { this.children = []; this._text = String(v); }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  fire(t, ev = {}) {
    const e = Object.assign({ preventDefault() {}, stopPropagation() {}, key: "" }, ev);
    (this.listeners[t] || []).forEach((f) => f(e));
  }
  focus() {}
  querySelectorAll(sel) {
    const parts = sel.trim().split(/\s+/);
    return walk(this).filter((n) => {
      if (!compound(n, parts[parts.length - 1])) return false;
      let p = n.parentElement, i = parts.length - 2;
      while (i >= 0 && p) { if (compound(p, parts[i])) i--; p = p.parentElement; }
      return i < 0;
    });
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

function walk(n, out = []) {
  for (const c of n.children) { out.push(c); walk(c, out); }
  return out;
}
/** One compound selector: `tag`, `.a.b`, `[attr]`, `[attr="v"]` — enough for this file's needs. */
function compound(n, sel) {
  let s = sel.trim();
  const classes = [...s.matchAll(/\.([\w-]+)/g)].map((m) => m[1]);
  const attrs = [...s.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)].map((m) => [m[1], m[2]]);
  const tag = s.replace(/[.\[][^\]]*\]?/g, "").trim();
  if (tag && n.tagName !== tag.toUpperCase()) return false;
  for (const c of classes) if (!n.classList.contains(c)) return false;
  for (const [k, v] of attrs) {
    const got = n.getAttribute(k);
    if (v === undefined ? got === null : got !== v) return false;
  }
  return true;
}

const document = {
  createElement: (t) => new El(t),
  body: new El("body"),
  addEventListener() {},
  querySelectorAll: (sel) => document.body.querySelectorAll(sel),
};
const store = new Map();
const localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
};
const getComputedStyle = () => ({ overflowY: "visible" });

/* ── the component, taken out of the source the same way G27 copies it ─────── */
const text = readFileSync(SRC, "utf8");
/* The markers are SPELLED here in two halves: gate G27 holds every file that carries one whole to
   being a kept copy of the block, and this file is the block's reader, not a copy of it. */
const mark = (edge) => "/* @bina-nav-js" + ":" + edge + " */";
const start = text.indexOf(mark("start"));
const end = text.indexOf(mark("end"));
if (start < 0 || end < 0) { console.error("FAIL  bina-nav.js: markers missing"); process.exit(1); }
const block = text.slice(start, end);
const BinaNav = new Function("document", "localStorage", "getComputedStyle", `${block}; return BinaNav;`)(
  document, localStorage, getComputedStyle,
);

/* ── the promises ─────────────────────────────────────────────────────────── */
let fails = 0;
function ok(what, cond, extra = "") {
  if (cond) { console.log(`ok    ${what}`); return true; }
  fails++;
  console.log(`FAIL  ${what}${extra ? "  — " + extra : ""}`);
  return false;
}

const cfg = {
  id: "selftest",
  brand: { name: "מייל", sub: "bina", avatar: "מ" },
  primary: { label: "הודעה חדשה", icon: "edit" },
  search: { placeholder: "חיפוש…" },
  sections: [
    {
      id: "boxes",
      title: "תיבות",
      actions: [{ icon: "plus", label: "תיקייה", onClick() {} }, { icon: "gear", label: "עוד", onClick() {} }],
      search: { placeholder: "חיפוש בתיבה…" },
      items: [
        { id: "inbox", label: "נכנס", icon: "inbox", meta: "12", badge: "3" },
        { id: "sent", label: "נשלח", icon: "send" },
        ...Array.from({ length: 8 }, (_, i) => ({ id: "l" + i, label: "תווית " + i, icon: "tag" })),
      ],
      showMore: 6,
    },
    { id: "extra", title: "עוד", items: [{ id: "drafts", label: "טיוטות", icon: "file", badge: "1" }] },
  ],
  footer: { text: "מחובר/ת · mail" },
};

const root = new El("aside");
const nav = BinaNav.mount(root, cfg);

ok("mount adds .bnv to the host element", root.classList.contains("bnv"));
ok("the brand row carries the name, the avatar and the context line",
  root.querySelector(".bnv-head b")?.textContent === "מייל"
  && root.querySelector(".bnv-avatar")?.textContent === "מ"
  && root.querySelector(".bnv-head small")?.textContent === "bina");
ok("each brand line reads the way its own first letter does, so one that does not fit is cut at its END",
  root.querySelector(".bnv-head b")?.getAttribute("dir") === "auto"
  && root.querySelector(".bnv-head small")?.getAttribute("dir") === "auto");
ok("the collapse control exists when the host may collapse", !!root.querySelector(".bnv-collapse"));
ok("the ONE primary action renders with its label",
  root.querySelector(".bnv-primary")?.textContent.includes("הודעה חדשה"));
ok("group titles render", walk(root).filter((n) => n.classList.contains("bnv-gtitle")).length === 2);
ok("group actions render, and never more than two",
  root.querySelectorAll(".bnv-act").length === 3,
  `expected 2 actions + 1 search toggle, got ${root.querySelectorAll(".bnv-act").length}`);

const boxes = root.querySelectorAll(".bnv-search");
ok("the menu's own search is always there", boxes.length === 2 && boxes[0].hidden === false);
const box = boxes[1];
ok("a group's search box waits to be asked for", box && box.hidden === true);
const searchToggle = root.querySelectorAll(".bnv-act").filter((n) => n.getAttribute("aria-expanded") !== null)[0];
searchToggle?.fire("click");
ok("the search toggle opens the box", box && box.hidden === false);

const rows = walk(root).filter((n) => n.classList.contains("bnv-item"));
ok("Priority+ keeps the list at its limit", rows.filter((r) => !r.parentElement.classList.contains("bnv-rest")).length === 7,
  "6 promised + 1 in the second group");
const rest = root.querySelector(".bnv-rest");
ok("the rows that did not fit are grouped, not lost", rest && rest.children.length === 4);
const more = root.querySelector(".bnv-more");
ok("the reveal row names how many are hidden", more && more.textContent.includes("4"), more && more.textContent);
more?.fire("click");
ok("the reveal row opens them and becomes the way back",
  rest.classList.contains("is-open") && more.textContent === "הצג פחות");

const inbox = walk(root).find((r) => r.getAttribute("data-bnv-id") === "inbox");
ok("a row carries its icon, label, meta column and badge",
  inbox?.querySelector(".bnv-ic") && inbox.querySelector(".bnv-label").textContent === "נכנס"
  && inbox.querySelector(".bnv-meta").textContent === "12"
  && inbox.querySelector(".bnv-badge").textContent === "3");

nav.setActive("inbox");
ok("setActive marks exactly one row current",
  inbox.classList.contains("is-active") && inbox.getAttribute("aria-current") === "page"
  && walk(root).filter((n) => n.classList.contains("is-active")).length === 1);
nav.setBadge("inbox", "9");
ok("setBadge rewrites the count in place", inbox.querySelector(".bnv-badge").textContent === "9");
nav.setBadge("inbox", "");
ok("setBadge with nothing removes the pill", !inbox.querySelector(".bnv-badge"));
nav.setMeta("sent", "4.2 MB");
ok("setMeta fills the second column",
  walk(root).find((r) => r.getAttribute("data-bnv-id") === "sent").querySelector(".bnv-meta").textContent === "4.2 MB");

const input = box.querySelector("input");
const boxesGroup = walk(root).find((n) => n.getAttribute("data-bnv-group") === "boxes");
const visibleIn = (g) => walk(g).filter((r) => r.classList.contains("bnv-item") && !r.hidden).length;
input.value = "תווית 3";
input.fire("input");
ok("typing in the menu's search hides what does not match", visibleIn(boxesGroup) === 1,
  `visible ${visibleIn(boxesGroup)}`);
ok("and it leaves the menu's other groups alone", visibleIn(walk(root).find((n) => n.getAttribute("data-bnv-group") === "extra")) === 1);
input.value = "אין-כזה-דבר";
input.fire("input");
ok("a search that matches nothing says so instead of looking broken",
  !!root.querySelector(".bnv-empty") && root.querySelector(".bnv-empty").hidden === false);

nav.setBrand({ sub: "user@local.test · מקומי" });
ok("setBrand rewrites the context line under the name",
  root.querySelector(".bnv-head small").textContent === "user@local.test · מקומי");
nav.setSearch("חשבונית");
ok("setSearch mirrors a URL's query into the menu's own search",
  boxes[0].querySelector("input").value === "חשבונית");

nav.setRail(true);
ok("the rail is a state of the same element", root.classList.contains("is-rail"));
ok("the rail is remembered for the next visit", localStorage.getItem("bnav:rail:selftest") === "1");
nav.setRail(false);

nav.open();
const scrim = document.body.children.find((c) => c.classList.contains("bnv-scrim"));
ok("opening the drawer raises a scrim and marks the menu open",
  root.classList.contains("is-open") && scrim && scrim.classList.contains("is-open"));
nav.close();
ok("closing it takes both back down", !root.classList.contains("is-open") && !scrim.classList.contains("is-open"));

/* A rail takes away WORDS, never a way in. The stylesheet takes a rail's parts off the screen — the
   search's field, the brand's name — and a part off the screen is one that has no boxes, which is
   what the component asks of it too. So that is what "a rail" is in here. */
const field = boxes[0].querySelector("input"), glass = boxes[0].querySelector("button");
let focused = 0;
field.focus = () => { focused++; };
ok("the search's magnifier is a button, named as the field is",
  !!glass && glass.getAttribute("aria-label") === field.placeholder);
boxes[0].fire("click");
ok("…it puts the keyboard in the field, and opens nothing while the field is there",
  focused === 1 && !root.classList.contains("is-open"));
field.getClientRects = () => [];
boxes[0].fire("click");
ok("in a rail the box is its magnifier alone: a press opens the menu on its search",
  root.classList.contains("is-open") && focused === 2);
delete field.getClientRects;

const fold = root.querySelector(".bnv-collapse"), brandName = root.querySelector(".bnv-head b");
fold.fire("click");
ok("the collapse control folds a menu that stands over the page — and that is all it does then",
  !root.classList.contains("is-open") && !root.classList.contains("is-rail"));
fold.fire("click");
ok("it makes the whole menu a rail, and the choice is remembered",
  root.classList.contains("is-rail") && localStorage.getItem("bnav:rail:selftest") === "1");
brandName.getClientRects = () => (root.classList.contains("is-rail") ? [] : [{}]);    // a rail somebody chose
fold.fire("click");
ok("it brings the whole menu back from a rail somebody chose",
  !root.classList.contains("is-rail") && !root.classList.contains("is-open")
  && localStorage.getItem("bnav:rail:selftest") === "0");
brandName.getClientRects = () => [];                                                  // a rail by width
fold.fire("click");
ok("where the frame is too narrow for the whole menu, it opens it over the page",
  root.classList.contains("is-open") && !root.classList.contains("is-rail"));
nav.setRail(true);
ok("choosing the rail shuts a menu that stands over the page", !root.classList.contains("is-open"));
nav.setRail(false);
delete brandName.getClientRects;

/* The page's half of the drawer is two buttons it only PLACES: the component draws and wires them. */
const menuBtn = document.body.appendChild(new El("button")), findBtn = document.body.appendChild(new El("button"));
menuBtn.setAttribute("data-nav-toggle", "תפריט");
findBtn.setAttribute("data-nav-find", "חיפוש");
const paged = new El("aside");
const nav4 = BinaNav.mount(paged, { id: "toggles-selftest", brand: { name: "מסך", avatar: "מ" }, search: { placeholder: "חיפוש" },
                                    sections: [{ id: "s", items: [{ id: "a", label: "אחד" }] }] });
ok("a button the page marks as the menu's is drawn and named by the component",
  menuBtn.innerHTML.includes("<svg") && menuBtn.getAttribute("aria-label") === "תפריט"
  && menuBtn.getAttribute("aria-expanded") === "false");
menuBtn.fire("click");
const opened = paged.classList.contains("is-open");
menuBtn.fire("click");
ok("…and it opens the menu and shuts it", opened && !paged.classList.contains("is-open"));
let found = 0;
paged.querySelector(".bnv-search input").focus = () => { found++; };
findBtn.fire("click");
ok("a button the page marks as the search's opens the menu on its search",
  findBtn.innerHTML.includes("<svg") && paged.classList.contains("is-open") && found === 1);
nav4.close();
menuBtn.remove(); findBtn.remove();

/* the two older shapes must keep working: an app mid-migration is not a broken app */
const flat = new El("nav");
const picked = [];
const nav2 = BinaNav.mount(flat, { items: [{ id: "a", label: "אחד" }, { id: "b", label: "שניים" }], onPick: (id) => picked.push(id) });
ok("a bare {items} list still builds rows", walk(flat).filter((n) => n.classList.contains("bnv-item")).length === 2);
nav2.setActive("b");
ok("and it still answers setActive",
  walk(flat).find((r) => r.getAttribute("data-bnv-id") === "b").classList.contains("is-active"));
walk(flat).find((r) => r.getAttribute("data-bnv-id") === "a").fire("click");
ok("and it still reports the pick to the app", picked.join(",") === "a");

/* …and the page that marks up its SECTIONS gets the same menu as a declared one. This shape built
   its rows by hand, so it had no brand row, no rail and no remembered state: the one screen that
   uses it (data-management) stood in the office as the menu with no name over it. */
const scrolled = [];
const page = document.body.appendChild(new El("main"));
for (const [id, label, icon] of [["sec-a", "סיכום", "chart"], ["sec-b", "ארכיונים", "archive"]]) {
  const s = page.appendChild(new El("section"));
  s.id = id; s.setAttribute("data-nav", label); s.setAttribute("data-nav-icon", icon);
  s.getBoundingClientRect = () => ({ top: id === "sec-b" ? 640 : 40 });
}
globalThis.window = { scrollY: 0, scrollTo: (o) => scrolled.push(o.top) };
const byPage = new El("nav");
const nav3 = BinaNav.mount(byPage, { id: "sections-selftest", sections: "[data-nav]",
                                    brand: { name: "ניהול נתונים", sub: "כל מה שהלשכה שומרת", avatar: "נ" } });
const secRows = walk(byPage).filter((n) => n.classList.contains("bnv-item"));
ok("a page's marked-up sections become rows, in the page's order",
  secRows.map((r) => r.querySelector(".bnv-label").textContent).join("|") === "סיכום|ארכיונים");
ok("…under the same brand row a declared menu has",
  byPage.querySelector(".bnv-head .bnv-avatar")?.textContent === "נ"
  && byPage.querySelector(".bnv-head-text").textContent.includes("ניהול נתונים")
  && !!byPage.querySelector(".bnv-collapse"));
secRows[1].fire("click");
ok("a row takes the page to its section", scrolled.length === 1 && scrolled[0] === 632, String(scrolled));
ok("…and is the marked one from the moment it is pressed",
  secRows[1].classList.contains("is-active") && !secRows[0].classList.contains("is-active"));
nav3.setActive("sec-a");
ok("and the menu marks the section it is told is in view",
  secRows[0].classList.contains("is-active") && !secRows[1].classList.contains("is-active"));
nav3.setRail(true);
ok("the rail is the same state, remembered under the page's id",
  byPage.classList.contains("is-rail") && localStorage.getItem("bnav:rail:sections-selftest") === "1");
page.remove();

/* ── the adopters: an app that declares its menu has NO menu markup of its own ────────────────
   This is the half of the mandate a component test cannot see: "i dont want everybody recreating
   the navigatore in diffrent wayies". An app joins this list when it moves to the declaration, and
   the list is what keeps it there — a hand-built row reappearing in an adopted app is the bug this
   catches, and it is invisible to every other check (it renders fine; it is just a second menu).

   WHO the adopters are is READ, not listed: every file under apps/ and platform-base/ that mounts
   the menu is one, the day it does. The list used to be kept here by hand, and the offices' pairing
   screen mounted the menu without ever being on it — so nothing held it to the promise. Two things
   are the adopter's own to say, and are read from its own files:
     · its PAGE — the mounting file itself when that is a page (.html, .tsx), else the page beside
       it that carries its name (`connect.js` → `connect.html`), else `index.html`;
     · `bina-nav:unsized`, written in the mounting file with the reason — a shell that is not yet
       `.bnv-host`/`.appgrid`. A remaining step for that app, said where the app is. */
const MOUNTS = (src, file) => src.includes("BinaNav.mount(")
  || (/\.tsx?$/.test(file) && src.includes("BinaNav") && /\.mount\(/.test(src));   // reached through `window`
function sources(dir, out = []) {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, e.name);
    if (e.isDirectory()) {
      if (!["node_modules", "dist", "build", ".git"].includes(e.name) && p !== HERE) sources(p, out);
    } else if ([".js", ".html", ".tsx", ".ts"].includes(extname(e.name))) out.push(p);
  }
  return out;
}
const ADOPTERS = ["apps", "platform-base"].flatMap((top) => sources(join(ROOT, top)))
  .filter((file) => MOUNTS(readFileSync(file, "utf8"), file))
  .map((file) => {
    const page = [".html", ".tsx"].includes(extname(file)) ? file
      : [join(dirname(file), basename(file, extname(file)) + ".html"), join(dirname(file), "index.html")].find(existsSync);
    const rel = (f) => relative(ROOT, f).split("\\").join("/");
    return { app: rel(file), js: rel(file), html: rel(page || file),
             sized: !readFileSync(file, "utf8").includes("bina-nav:unsized") };
  });
ok("the adopters are found in the tree (a search that finds none has measured nothing)", ADOPTERS.length >= 6,
  ADOPTERS.map((a) => a.app).join(" "));

/* Some apps mount into an element that is not called #sideNav — the contract is the CONTAINER and
   the mount, not the name. The check below reads the id out of the mount call instead of assuming. */
function mountTargetId(js, html) {
  const ids = [
    ...js.matchAll(/getElementById\(['"]([A-Za-z0-9_-]+)['"]\)/g),
    ...js.matchAll(/\$\("#([A-Za-z0-9_-]+)"\)/g),
  ].map((m) => m[1]);
  /* The menu mounts into the page's ONE <aside> — so the id that matters is the id that is an
     aside in the markup, not the first element the script happens to look up (notifications
     looks up a toast div long before it looks up its menu). */
  for (const id of ids) if (new RegExp(`<aside[^>]*id="${id}"`).test(html)) return id;
  /* Nothing matched an <aside>: either the page mounts into `sideNav` (the convention all five
     HTML apps follow) or the aside is reached by a ref, as a React app must. Never the first id
     the file happens to look up — that is how this check once "found" a toast div. */
  return html.includes('id="sideNav"') ? "sideNav" : (ids[0] || "sideNav");
}
const HAND_BUILT = ['class="bnv-item', "class='bnv-item", 'class="bnv-head', 'class="bnv-scroll', 'class="bnv-foot'];
for (const a of ADOPTERS) {
  const js = readFileSync(join(ROOT, a.js), "utf8");
  const html = readFileSync(join(ROOT, a.html), "utf8");
  ok(`${a.app} declares its menu through BinaNav.mount`,
    js.includes("BinaNav.mount(") || (js.includes("BinaNav") && /\.mount\(/.test(js)));
  const handJs = HAND_BUILT.filter((h) => js.includes(h));
  ok(`${a.app} builds no menu rows of its own`, handJs.length === 0, handJs.join(" "));
  const handHtml = HAND_BUILT.filter((h) => html.includes(h));
  ok(`${a.app}'s page carries no menu markup`, handHtml.length === 0, handHtml.join(" "));
  const target = mountTargetId(js, html);
  ok(`${a.app}'s page has the one element the menu is mounted into`,
    new RegExp(`id="${target}"[^>]*>\\s*</aside>`).test(html)      // plain HTML
    || new RegExp(`<aside[^>]*id="${target}"[^>]*></aside>`).test(html)
    || new RegExp(`<aside[^>]*id="${target}"[^>]*/>`).test(html), target);   // JSX, self-closing
  if (a.sized !== false) {
    ok(`${a.app}'s page lets the container decide the size (bnv-host + appgrid)`,
      html.includes('class="bnv-host"') && html.includes("appgrid"));
  }
}

console.log(fails ? `\n${fails} broken promise(s).` : "\nall promises kept.");
process.exit(fails ? 1 : 0);
