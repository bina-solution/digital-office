#!/usr/bin/env node
/**
 * extract-en.mjs — re-extract the harness's English UI dictionaries from an installed profile.
 *
 * The Hebrew pack keeps one dictionary per harness UI namespace (dicts/he/<ns>.json) and the pinned
 * English source beside it (dicts/en/<ns>.json); build-client.mjs refuses a Hebrew dictionary whose
 * key set differs from its English source. When the harness version changes, the English source has
 * to be taken again from THAT version — this script does it, so the bump is repeatable (it used to
 * live outside the repo, in the bina-lab notes).
 *
 * How: every `@deepseek-ai/*` browser bundle (`lib/client.js` / `lib/client.browser.js`) registers its
 * strings with `ctx.locale.register(<namespace>, { en, zh, … })` when the host applies it. The bundle is
 * evaluated here with a stub module loader, a stub `require` and a stub context whose `locale.register`
 * records the call; everything else the bundle touches is an inert proxy. A bundle that throws after
 * registering still counts; one that never registers has no strings.
 *
 *   node extract-en.mjs <profile-dir> [--write]
 *     prints namespaces added / removed / changed against dicts/en, and with --write replaces dicts/en
 *     and dicts/index.json (the version comes from the profile's installed @deepseek-ai/dsh).
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const [profile, ...flags] = process.argv.slice(2);
if (!profile) { console.error("usage: node extract-en.mjs <profile-dir> [--write] [--packages <file>]"); process.exit(2); }
const WRITE = flags.includes("--write");
// --packages <file>: only the bundles the page actually loads (one `@deepseek-ai/<pkg>` per line, as the
// served index's boot manifest lists them). A package that is installed but not mounted by the profile
// shows no string to anyone, and translating it is work for nobody.
const pi = flags.indexOf("--packages");
const ONLY = pi >= 0 ? new Set(fs.readFileSync(flags[pi + 1], "utf8").split(/\s+/).filter(Boolean).map((p) => p.replace(/^@deepseek-ai\//, ""))) : null;
const HERE = path.dirname(new URL(import.meta.url).pathname);
const EN = path.join(HERE, "dicts", "en");

// An inert value: callable, constructible, every property is another inert value, never a thenable.
function inert() {
  const fn = function () {};
  return new Proxy(fn, {
    get(_t, k) {
      if (k === "then") return undefined;
      if (k === Symbol.toPrimitive) return () => "";
      if (k === Symbol.iterator) return function* () {};
      if (k === "length") return 0;
      return inert();
    },
    apply() { return inert(); },
    construct() { return inert(); },
    has() { return true; },
  });
}

function bundles(root) {
  const pnpm = path.join(root, "node_modules", ".pnpm");
  const out = new Map();
  for (const d of fs.readdirSync(pnpm)) {
    if (!d.startsWith("@deepseek-ai+")) continue;
    const scope = path.join(pnpm, d, "node_modules", "@deepseek-ai");
    if (!fs.existsSync(scope)) continue;
    for (const pkg of fs.readdirSync(scope)) {
      if (ONLY && !ONLY.has(pkg)) continue;
      for (const f of ["lib/client.js", "lib/client.browser.js"]) {
        const p = path.join(scope, pkg, f);
        if (fs.existsSync(p) && !out.has(`${pkg}/${f}`)) out.set(`${pkg}/${f}`, p);
      }
    }
  }
  return out;
}

const found = {};   // namespace -> { en, source }
for (const [name, file] of bundles(profile)) {
  const loaded = [];
  const sandbox = { console: { log() {}, warn() {}, error() {}, info() {}, debug() {} } };
  sandbox.window = sandbox; sandbox.globalThis = sandbox; sandbox.self = sandbox;
  sandbox.document = inert(); sandbox.navigator = inert(); sandbox.location = inert();
  sandbox.setTimeout = () => 0; sandbox.clearTimeout = () => {}; sandbox.setInterval = () => 0; sandbox.clearInterval = () => {};
  sandbox.queueMicrotask = () => {}; sandbox.URL = URL; sandbox.Map = Map; sandbox.Set = Set; sandbox.WeakMap = WeakMap;
  sandbox.Symbol = Symbol; sandbox.Object = Object; sandbox.Array = Array; sandbox.JSON = JSON; sandbox.Promise = Promise;
  sandbox.__ModuleLoader__ = { load(def) { loaded.push(def); } };
  try { vm.runInNewContext(fs.readFileSync(file, "utf8"), sandbox, { filename: file, timeout: 5000 }); } catch { /* a bundle that needs a real browser at load time has nothing for us */ }
  for (const def of loaded) {
    let mod;
    try { mod = def.factory(inert()); } catch { continue; }   // `require` has members too (require.asset)
    const apply = mod && (mod.apply || mod.default?.apply);
    if (typeof apply !== "function") continue;
    const record = (ns, dicts) => {
      if (typeof ns === "string" && dicts && typeof dicts === "object" && dicts.en && typeof dicts.en === "object") {
        found[ns] = { en: JSON.parse(JSON.stringify(dicts.en)), source: name };
      }
      return inert();
    };
    const locale = new Proxy(inert(), { get(_t, k) { return k === "register" ? record : k === "then" ? undefined : inert(); } });
    const ctx = new Proxy(inert(), {
      get(_t, k) {
        if (k === "then") return undefined;
        if (k === "locale") return locale;
        if (k === "inject") return (_names, cb) => { try { cb(ctx); } catch {} return inert(); };
        if (k === "effect") return (fn) => { try { fn(); } catch {} return inert(); };
        return inert();
      },
    });
    try { apply(ctx, inert()); } catch { /* registration happens first; the rest needs a host */ }
  }
  // Static fallback: a bundle whose apply() touches the host before it registers (and so throws inside
  // the stub) still names its dictionaries literally — `register(NS,{zh,en,…})`, `const NS=\`chat\``,
  // `const en={…}`. Each such object literal is evaluated on its own, as data.
  // A bundle may hold several modules, each with its own `NS` and `en`: every name is resolved to its
  // NEAREST definition before the register call (modules are emitted before their use).
  const src = fs.readFileSync(file, "utf8");
  const nearest = (re, before) => { let hit = null; for (const d of src.slice(0, before).matchAll(re)) hit = d; return hit; };
  const esc = (s) => s.trim().replace(/\$/g, "\\$");
  for (const m of src.matchAll(/locale\.register\(([A-Za-z_$][\w$]*|`[^`]+`),\{([^}]*)\}/g)) {
    const nsTok = m[1];
    const ns = nsTok.startsWith("`") ? nsTok.slice(1, -1) : (nearest(new RegExp(`(?:const|let|var) ${esc(nsTok)}=\`([^\`]+)\``, "g"), m.index) || [])[1];
    if (!ns || found[ns]) continue;
    const enIdent = (m[2].split(",").map((s) => s.trim()).map((s) => s.split(":")).find(([k]) => k === "en") || [])[1] || (m[2].split(",").map((s) => s.trim()).includes("en") ? "en" : null);
    if (!enIdent) continue;
    const def = nearest(new RegExp(`(?:const|let|var) ${esc(enIdent)}=\\{`, "g"), m.index);
    const at = def ? def.index : -1;
    if (at < 0) continue;
    const start = src.indexOf("{", at);
    const literal = balanced(src, start);
    if (!literal) continue;
    // A dictionary may name a constant defined elsewhere in the bundle (`"plan.next":PLAN_NEXT_ACTION_EN`):
    // each name the evaluation reports missing is taken from its nearest definition and the literal is
    // evaluated again, a bounded number of times.
    const scope = {};
    for (let tries = 0; tries < 30; tries++) {
      try {
        const en = vm.runInNewContext("(" + literal + ")", { ...scope }, { timeout: 2000 });
        if (en && typeof en === "object") found[ns] = { en: JSON.parse(JSON.stringify(en)), source: name + " (static)" };
        break;
      } catch (e) {
        const missing = /^([A-Za-z_$][\w$]*) is not defined$/.exec(e?.message || "")?.[1];
        if (!missing) break;
        const d = nearest(new RegExp(`(?:const|let|var) ${esc(missing)}=`, "g"), at);
        if (!d) break;
        const vStart = d.index + d[0].length;
        const value = src[vStart] === "{" ? balanced(src, vStart) : stringAt(src, vStart);
        if (value === null) break;
        try { scope[missing] = vm.runInNewContext("(" + value + ")", { ...scope }, { timeout: 1000 }); } catch { break; }
      }
    }
  }
}

// The text of one string literal ("…", '…' or `…`) starting at `i`, or null when there is none.
function stringAt(s, i) {
  const q = s[i];
  if (q !== '"' && q !== "'" && q !== "`") return null;
  for (let j = i + 1; j < s.length; j++) {
    if (s[j] === "\\") { j++; continue; }
    if (s[j] === q) return s.slice(i, j + 1);
  }
  return null;
}

// The text of the balanced {...} starting at `i`, skipping over strings and template literals.
function balanced(s, i) {
  let depth = 0;
  for (let j = i; j < s.length; j++) {
    const c = s[j];
    if (c === '"' || c === "'" || c === "`") {
      for (j++; j < s.length && s[j] !== c; j++) if (s[j] === "\\") j++;
      continue;
    }
    if (c === "{") depth++;
    else if (c === "}" && --depth === 0) return s.slice(i, j + 1);
  }
  return null;
}

// --keep <ns,…>: a namespace whose bundle registers one language at a time (`register(NS, locale,
// dict)` in a loop — the folder picker) cannot be read either way; its pinned English is kept as it is.
const ki = flags.indexOf("--keep");
for (const ns of ki >= 0 ? flags[ki + 1].split(",").filter(Boolean) : []) {
  const f = path.join(EN, ns + ".json");
  if (!found[ns] && fs.existsSync(f)) found[ns] = { en: JSON.parse(fs.readFileSync(f, "utf8")), source: "(kept: registers per language)" };
}

const sortKeys = (o) => Object.fromEntries(Object.keys(o).sort().map((k) => [k, o[k]]));
const have = new Set(fs.readdirSync(EN).filter((f) => f.endsWith(".json")).map((f) => f.slice(0, -5)));
const now = new Set(Object.keys(found));
const added = [...now].filter((n) => !have.has(n)).sort();
const removed = [...have].filter((n) => !now.has(n)).sort();
const changed = [];
for (const ns of [...now].filter((n) => have.has(n)).sort()) {
  const old = JSON.parse(fs.readFileSync(path.join(EN, ns + ".json"), "utf8"));
  const a = Object.keys(found[ns].en), b = Object.keys(old);
  const plus = a.filter((k) => !(k in old)), minus = b.filter((k) => !(k in found[ns].en));
  const text = a.filter((k) => k in old && old[k] !== found[ns].en[k]);
  if (plus.length || minus.length || text.length) changed.push({ ns, plus: plus.length, minus: minus.length, text: text.length });
}
console.log(`namespaces: ${now.size} found, ${added.length} new, ${removed.length} gone, ${changed.length} changed`);
for (const n of added) console.log(`  + ${n} (${Object.keys(found[n].en).length} keys, ${found[n].source})`);
for (const n of removed) console.log(`  - ${n}`);
for (const c of changed) console.log(`  ~ ${c.ns}: +${c.plus} -${c.minus} keys, ${c.text} English texts changed`);

if (WRITE) {
  const pkg = path.join(profile, "node_modules", "@deepseek-ai", "dsh", "package.json");
  const version = JSON.parse(fs.readFileSync(pkg, "utf8")).version;
  for (const n of removed) fs.rmSync(path.join(EN, n + ".json"));
  const index = { dsh: version, namespaces: {} };
  for (const ns of [...now].sort()) {
    fs.writeFileSync(path.join(EN, ns + ".json"), JSON.stringify(sortKeys(found[ns].en), null, 1) + "\n");
    index.namespaces[ns] = { file: ns + ".json", source: found[ns].source, keys: Object.keys(found[ns].en).length };
  }
  fs.writeFileSync(path.join(HERE, "dicts", "index.json"), JSON.stringify(index, null, 1) + "\n");
  console.log(`wrote dicts/en (${now.size} namespaces) and dicts/index.json for dsh ${version}`);
}
