#!/usr/bin/env node
/**
 * apply-he.mjs — bring dicts/he in line with dicts/en after a harness version bump.
 *
 * The second half of a bump, after extract-en.mjs has re-taken the English source:
 *   1. every key a translations file names is written into its namespace's Hebrew dictionary;
 *   2. every key the English source no longer has is dropped from the Hebrew one;
 *   3. a namespace the index no longer lists loses its Hebrew file.
 * Then `node build-client.mjs --check` says whether every Hebrew key set matches its English source.
 *
 *   node apply-he.mjs <translations.json>    # { "<namespace>": { "<key>": "<Hebrew>" } }
 *
 * A translation must keep every placeholder of its English text (`{name}`, `{{count}}`, `%s`, an ICU
 * `{n, plural, …}`); one that does not is refused and listed, and nothing is written.
 */
import fs from "node:fs";
import path from "node:path";

const HERE = path.dirname(new URL(import.meta.url).pathname);
const EN = path.join(HERE, "dicts", "en"), HE = path.join(HERE, "dicts", "he");
const file = process.argv[2];
if (!file) { console.error("usage: node apply-he.mjs <translations.json>"); process.exit(2); }
const tr = JSON.parse(fs.readFileSync(file, "utf8"));
const index = JSON.parse(fs.readFileSync(path.join(HERE, "dicts", "index.json"), "utf8"));
const PH = /\{\{?\s*[A-Za-z_][\w.]*\s*\}?\}|%[sd]|\{[A-Za-z_]\w*,\s*(?:plural|select)/g;
const sortKeys = (o) => Object.fromEntries(Object.keys(o).sort().map((k) => [k, o[k]]));

const refused = [];
const out = {};
for (const [ns, meta] of Object.entries(index.namespaces)) {
  const en = JSON.parse(fs.readFileSync(path.join(EN, meta.file), "utf8"));
  let he = {};
  try { he = JSON.parse(fs.readFileSync(path.join(HE, meta.file), "utf8")); } catch { /* a new namespace */ }
  const next = {};
  for (const k of Object.keys(en)) {
    const given = tr[ns]?.[k];
    if (given !== undefined) {
      const a = (en[k].match(PH) || []).sort().join("|"), b = (String(given).match(PH) || []).sort().join("|");
      if (a !== b) { refused.push(`${ns}.${k}: placeholders ${a || "∅"} ≠ ${b || "∅"}`); continue; }
      next[k] = given;
    } else if (k in he) next[k] = he[k];
  }
  out[meta.file] = sortKeys(next);
}
if (refused.length) { console.error(`refused ${refused.length}:\n  ${refused.join("\n  ")}`); process.exit(1); }
for (const [f, d] of Object.entries(out)) fs.writeFileSync(path.join(HE, f), JSON.stringify(d, null, 1) + "\n");
const keep = new Set(Object.keys(out));
for (const f of fs.readdirSync(HE)) if (f.endsWith(".json") && !keep.has(f)) { fs.rmSync(path.join(HE, f)); console.log(`removed dicts/he/${f} (no such namespace any more)`); }
const missing = Object.entries(index.namespaces).reduce((n, [, m]) => {
  const en = JSON.parse(fs.readFileSync(path.join(EN, m.file), "utf8"));
  return n + Object.keys(en).filter((k) => !(k in out[m.file])).length;
}, 0);
console.log(`dicts/he: ${keep.size} namespaces written; ${missing} English keys still without Hebrew`);
