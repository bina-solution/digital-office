/* @bina-lang:start */
/* bina-lang.js — the office's language, in the browser.
 *
 * WHY THIS EXISTS
 * The office is bilingual by construction: every manifest carries `title`/`summary` as `{he, en}`,
 * and every screen was written in Hebrew only. Nothing ever asked WHICH language to show, so a
 * second language was impossible in practice — the shell, the rail and each app UI each hardcoded
 * Hebrew, and there was no single place that could answer "what language is this office in".
 *
 * The office's answer is one variable (`language:` in platform.state.yaml, compiled to
 * .generated/registry/locale.json) and one switcher (the console's top bar). This file is how a
 * PAGE learns that variable and swaps its own strings. It is deliberately tiny and dependency-free,
 * because it is bundled into every surface — the console's own shell and every app it frames.
 *
 * HOW A PAGE GETS ITS LANGUAGE (first hit wins)
 *   1. `?lang=xx`           — explicit, and what a link or a screenshot link can pin.
 *   2. `<meta name="bina-lang" content="xx">` — what the CONSOLE injects into every app it proxies
 *      under /a/<alias>/. It is the reason a framed app needs no fetch, no cookie and no CORS: the
 *      shell already knows the office's language, and it says so in the document it hands over.
 *   3. `localStorage["bina.lang"]` — a per-browser memory, so an app opened on its OWN host
 *      (`computers.localhost`) still remembers the last switch instead of snapping back.
 *   4. the document's own `<html lang>` — the value the app was compiled with.
 *   5. `he` — the office's original language and the only one every screen was written in first.
 *
 * HOW A STRING GETS TRANSLATED
 *   · Markup: put both languages on the element and the runtime keeps it right, forever —
 *         <h1 data-lang-he="מחשבים" data-lang-en="Computers">מחשבים</h1>
 *     Any attribute can be translated instead of the text, with data-lang-attr="title|placeholder|
 *     aria-label|…". The Hebrew stays visible in the file as the source text, so a translator reads
 *     the page it is translating rather than a key.
 *   · Script: `L("מחשבים", "Computers")` for one-off strings, `BinaLang.pick(he, en)` verbatim.
 *   Both are the same function; `L` is the shorthand because it appears hundreds of times.
 *
 * An element added by ANY renderer is translated without that renderer knowing about languages: a
 * MutationObserver picks up new nodes and applies the attributes to them. That is deliberate — the
 * alternative is calling apply() after every innerHTML assignment in every app, and the one place
 * somebody forgets is a screen that stays Hebrew in an English office.
 */
(function (global) {
  "use strict";

  /* The languages this office has. Extending the office means a row here and a row in
     reconcile.LANGUAGES — the two lists are the artifact and its compiler, not two opinions. */
  var DIRS = { he: "rtl", en: "ltr" };
  var ORDER = ["he", "en"];
  var DEFAULT_LANG = "he";
  var STORE_KEY = "bina.lang";

  function known(code) {
    return typeof code === "string" && code && DIRS.hasOwnProperty(code.toLowerCase())
      ? code.toLowerCase() : "";
  }

  function fromQuery() {
    try {
      return known(new URLSearchParams(global.location.search).get("lang"));
    } catch (e) { return ""; }
  }

  function fromMeta() {
    var m = document.querySelector('meta[name="bina-lang"]');
    return m ? known(m.getAttribute("content")) : "";
  }

  function fromStore() {
    try { return known(global.localStorage.getItem(STORE_KEY)); } catch (e) { return ""; }
  }

  function fromDocument() {
    return known(document.documentElement.getAttribute("lang"));
  }

  var lang = fromQuery() || fromMeta() || fromStore() || fromDocument() || DEFAULT_LANG;
  var listeners = [];

  function pick(he, en) {
    /* The whole translation API in one expression. `en` may be omitted, and then Hebrew serves both
       — a name that is the same in both languages should not have to be written twice. */
    return lang === "en" ? (en == null || en === "" ? he : en) : he;
  }

  function value(el, code) {
    var v = el.getAttribute("data-lang-" + code);
    return v == null ? "" : v;
  }

  function applyOne(el) {
    var he = value(el, "he"), en = value(el, "en");
    if (!he && !en) return;
    var out = pick(he || en, en || he);
    var attr = el.getAttribute("data-lang-attr");
    if (attr) {
      if (el.getAttribute(attr) !== out) el.setAttribute(attr, out);
    } else if (el.textContent !== out) {
      el.textContent = out;
    }
  }

  function apply(root) {
    root = root || document;
    // A DOCUMENT IS NOT AN ELEMENT, and this guard used to skip it: `document.nodeType` is 9, so
    // `apply(document)` — the call this file makes on load — did nothing at all. Static markup
    // carrying `data-lang-he/en` was therefore never translated, and only elements a renderer added
    // LATER were (the MutationObserver passes elements). The symptom is the one this whole feature
    // exists to remove: a page whose JS-built strings are English and whose own buttons are Hebrew —
    // measured on the live server for `sites` and `domains` (2026-10-11), and it is why the first
    // browser screenshot showed "New site"/"Adopt an existing site" in Hebrew under an English header.
    if (root.nodeType === 9) root = root.documentElement || document.body;
    if (!root || root.nodeType !== 1) return;
    if (root.hasAttribute("data-lang-he") || root.hasAttribute("data-lang-en")) applyOne(root);
    if (root.querySelectorAll) {
      var list = root.querySelectorAll("[data-lang-he],[data-lang-en]");
      for (var i = 0; i < list.length; i++) applyOne(list[i]);
    }
  }

  function direction() {
    document.documentElement.setAttribute("lang", lang);
    document.documentElement.setAttribute("dir", DIRS[lang]);
  }

  function set(code, opts) {
    var next = known(code);
    if (!next) return false;
    if ((opts && opts.store) !== false) {
      try { global.localStorage.setItem(STORE_KEY, next); } catch (e) { /* private mode: fine */ }
    }
    if (next === lang) { direction(); apply(document); return false; }
    lang = next;
    direction();
    apply(document);
    for (var i = 0; i < listeners.length; i++) {
      try { listeners[i](lang, DIRS[lang]); } catch (e) { /* a listener may not break the switch */ }
    }
    return true;
  }

  direction();

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { apply(document); });
  } else {
    apply(document);
  }

  /* New nodes, translated as they arrive. `apply` is idempotent and cheap (it only walks elements
     that carry the attributes), and the observer is attached once for the whole document. */
  if (global.MutationObserver) {
    new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        var added = muts[i].addedNodes;
        for (var j = 0; j < added.length; j++) {
          if (added[j].nodeType === 1) apply(added[j]);
        }
      }
    }).observe(document.documentElement, { childList: true, subtree: true });
  }

  global.BinaLang = {
    /* read */
    get lang() { return lang; },
    get dir() { return DIRS[lang]; },
    ORDER: ORDER,
    DIRS: DIRS,
    pick: pick,
    /* write (view only — the OFFICE's language is written by the console, through `bbox lang`) */
    set: set,
    apply: apply,
    /* called after a switch, for a renderer that builds its own markup without the attributes */
    onChange: function (fn) { listeners.push(fn); }
  };
  /* The shorthand. Every UI string in the office compares two languages and takes one; spelling
     `BinaLang.pick` at each of ~600 sites would be noise around the thing being translated. */
  global.L = pick;
})(window);
/* @bina-lang:end */
