#!/usr/bin/env node
// wrap.mjs — the ONE entry point to the vendored n8n-as-code toolchain.
// Plan + rationale: ai/context/n8n-as-code-migration.md. Nothing else in this repo may call
// n8nac/the transformer directly: every hook, gate and bbox verb goes through here, so the
// lossless-graft below has no bypass.
//
//   node wrap.mjs render  <json file|dir> <out dir>    JSON  -> .workflow.ts   (+ meta inject)
//   node wrap.mjs compile <ts file|dir>   <out dir>    .ts   -> import JSON    (+ meta graft)
//   node wrap.mjs verify  <json dir>                   render+compile+deep-equal, N/N report
//
// THE GRAFT. @n8n-as-code/transformer 2.0.0 drops these on JSON->TS (measured 0/64 round-trips
// on the INDOX fleet before grafting, 81/81 after): workflow `description`/`isArchived`/`tags`
// (id'd objects flattened)/`versionMetadata`/`connections` (edges from DISABLED nodes vanish and
// trailing empty switch outputs are trimmed — so the marker line is the AUTHORITATIVE graph and
// the generated links() DSL is a read-only view), and node `notes`/`notesInFlow`/`disabled`/
// `continueOnFail`. Until the upstream PR lands, render re-injects them into the generated TS as
// marker lines the compile step extracts and grafts back. The marker keeps the values
// HUMAN-EDITABLE in the .ts — one-line JSON, edit like any other code:
//
//     /*__n8n__*/ notes: "one-line JSON string",
//
// Node association rule: a node-level marker line applies to the NEAREST `name: '...'` line
// ABOVE it inside the same decorator block — render always emits them directly after `name:`,
// and compile validates every extracted note maps to a real node name, loudly.
//
// PERFORMANCE RULE: one n8nac process per DIRECTORY (convert-batch), never per file — CLI
// cold-start dominates and a per-file loop measured minutes-per-fleet on /mnt/c under WSL.

import { execFileSync, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
// 9P TAX: when this repo lives on /mnt/c (Windows checkout run through WSL — the standard bbox
// path), loading 289 packages from node_modules over the 9P mount costs MINUTES per n8nac cold
// start. So on Linux with a /mnt/* repo the toolchain self-installs to native ext4, keyed by the
// lockfile hash (a lockfile bump = a fresh cache dir). On native Windows / Linux-native repos it
// stays beside this file.
import { createHash } from "node:crypto";
function toolHome() {
  if (process.platform !== "win32" && HERE.startsWith("/mnt/")) {
    const lock = path.join(HERE, "package-lock.json");
    const h = createHash("sha256").update(fs.readFileSync(lock)).digest("hex").slice(0, 12);
    return path.join(os.homedir(), ".cache", "bbox-n8n-tooling", h);
  }
  return HERE;
}
const TOOL_HOME = toolHome();
const N8NAC = path.join(TOOL_HOME, "node_modules", "n8nac", "dist", "index.js");
const MARK = "/*__n8n__*/";
const WF_KEYS = ["description", "isArchived", "connections", "tags", "versionMetadata", "meta", "pinData", "staticData", "shared"];
const NODE_KEYS = ["notes", "notesInFlow", "disabled", "continueOnFail"];

function ensureDeps() {
  if (fs.existsSync(N8NAC)) return;
  fs.mkdirSync(TOOL_HOME, { recursive: true });
  if (TOOL_HOME !== HERE) {
    fs.copyFileSync(path.join(HERE, "package.json"), path.join(TOOL_HOME, "package.json"));
    fs.copyFileSync(path.join(HERE, "package-lock.json"), path.join(TOOL_HOME, "package-lock.json"));
  }
  console.error("[wrap] toolchain not installed — running npm ci in " + TOOL_HOME);
  execFileSync(process.platform === "win32" ? "npm.cmd" : "npm", ["ci", "--no-audit", "--no-fund"],
    { cwd: TOOL_HOME, stdio: "inherit" });
  if (!fs.existsSync(N8NAC)) throw new Error("npm ci did not produce n8nac — check network/registry");
}

const ENV = { ...process.env, N8NAC_TELEMETRY_DISABLED: "1" };

// convert-batch converts what it can, exits 0 whatever happened, and says for each input it could
// not convert WHY ("\u274C name: reason"). That used to be thrown away, and the caller then blamed
// the FIRST input without an output — one name, no reason, and not necessarily the file that was
// wrong (issues/convert-batch-blames-an-innocent-file.yaml). `why` is those sentences, by name.
function convertBatch(files, format) {
  // convert-batch writes outputs NEXT TO the inputs, so feed it a scratch copy.
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "wrapbatch-"));
  for (const f of files) fs.copyFileSync(f, path.join(tmp, path.basename(f)));
  // Both streams: the per-file sentences are on stderr, the summary on stdout.
  const r = spawnSync(process.execPath, [N8NAC, "convert-batch", tmp, "--format", format, "-f"],
    { stdio: ["ignore", "pipe", "pipe"], env: ENV, encoding: "utf8" });
  const said = [r.stdout, r.stderr].filter(Boolean).join("\n");
  if (r.status !== 0) throw new Error(`convert-batch exited ${r.status}: ${said.trim().slice(-400)}`);
  const why = new Map([...said.matchAll(/^\s*\u274C\s+(\S+):\s*(.+)$/gmu)].map((m) => [m[1], m[2].trim()]));
  return { tmp, why };
}

// One error for EVERY input left without an output, each with the converter's own reason, and
// nothing written for any of them. `lost` is [[the source path, the name the converter knew it by]].
function refuseLost(lost, total, why, what) {
  if (!lost.length) return;
  throw new Error(`${lost.length} of ${total} ${what} did not convert:\n` + lost.map(([src, name]) =>
    `  ${src}: ${why.get(name) || "the converter said nothing about it — convert it alone to see why"}`).join("\n"));
}

const jstr = (v) => JSON.stringify(v);
const NAME_RE = /^(\s*)name: (['"`])((?:\\.|(?!\2).)*)\2,\s*$/;
const unesc = (s) => s.replace(/\\(['"`\\])/g, "$1");

// ── inject: raw transformer TS + original workflow JSON -> grafted TS ─────────────────────
function injectMeta(ts, wf, id) {
  const wfLines = [];
  for (const k of WF_KEYS) if (wf[k] !== undefined) wfLines.push(`    ${MARK} ${k}: ${jstr(wf[k])},`);
  if (wfLines.length) ts = ts.replace(/@workflow\(\{\n/, (m) => m + wfLines.join("\n") + "\n");

  const byName = new Map();
  for (const n of wf.nodes || []) {
    const extras = [];
    for (const k of NODE_KEYS) if (n[k] !== undefined) extras.push(`        ${MARK} ${k}: ${jstr(n[k])},`);
    if (extras.length) byName.set(n.name, extras);
  }
  if (byName.size) {
    ts = ts.replace(new RegExp(NAME_RE.source, "gm"), (line, ind, q, rawName) => {
      const extras = byName.get(unesc(rawName));
      if (!extras) return line;
      byName.delete(unesc(rawName));
      return line + "\n" + extras.join("\n");
    });
    if (byName.size) throw new Error(`${id}: could not inject notes for node(s): ${[...byName.keys()].join(", ")}`);
  }
  return ts;
}

// ── extract: grafted TS -> {strippedTs, wfMeta, nodeMeta} ─────────────────────────────────
function extractMeta(raw, srcLabel) {
  const wfMeta = {};
  const nodeMeta = new Map();
  let currentName = null;
  const kept = [];
  for (const line of raw.split("\n")) {
    const nm = line.match(NAME_RE);
    if (nm) currentName = unesc(nm[3]);
    const mk = line.match(/^\s*\/\*__n8n__\*\/ ([A-Za-z_]+): (.*),\s*$/);
    if (mk) {
      const [, key, valRaw] = mk;
      const value = JSON.parse(valRaw);
      if (WF_KEYS.includes(key) && currentName === null) wfMeta[key] = value;
      else if (NODE_KEYS.includes(key) && currentName !== null) {
        if (!nodeMeta.has(currentName)) nodeMeta.set(currentName, {});
        nodeMeta.get(currentName)[key] = value;
      } else throw new Error(`${srcLabel}: marker key '${key}' in unexpected position`);
      continue;
    }
    kept.push(line);
  }
  return { stripped: kept.join("\n"), wfMeta, nodeMeta };
}

function graftMeta(wf, wfMeta, nodeMeta, srcLabel) {
  for (const [k, v] of Object.entries(wfMeta)) wf[k] = v;
  if (wfMeta.tags === undefined && Array.isArray(wf.tags) && wf.tags.length === 0) delete wf.tags;
  const nodesByName = new Map((wf.nodes || []).map((n) => [n.name, n]));
  for (const [name, metaObj] of nodeMeta) {
    const node = nodesByName.get(name);
    if (!node) throw new Error(`${srcLabel}: notes for unknown node '${name}' — was the name edited without moving its ${MARK} lines?`);
    for (const [k, v] of Object.entries(metaObj)) node[k] = v;
  }
  return wf;
}

// ── dir pipelines (batched) ───────────────────────────────────────────────────────────────
function renderDir(jsonFiles, outDir) {
  if (!jsonFiles.length) return [];
  const { tmp, why } = convertBatch(jsonFiles, "typescript");
  const outs = [];
  try {
    const tsOf = (f) => path.join(tmp, path.basename(f, ".json") + ".workflow.ts");
    refuseLost(jsonFiles.filter((f) => !fs.existsSync(tsOf(f))).map((f) => [f, path.basename(f)]),
      jsonFiles.length, why, "workflow(s)");
    for (const f of jsonFiles) {
      const wf = JSON.parse(fs.readFileSync(f, "utf8"));
      const id = wf.id || path.basename(f, ".json");
      const tsTmp = tsOf(f);
      const ts = injectMeta(fs.readFileSync(tsTmp, "utf8"), wf, id);
      const outTs = path.join(outDir, id + ".workflow.ts");
      fs.mkdirSync(outDir, { recursive: true });
      fs.writeFileSync(outTs, ts);
      outs.push(outTs);
    }
  } finally { fs.rmSync(tmp, { recursive: true, force: true }); }
  return outs;
}

function compileDir(tsFiles, outDir) {
  if (!tsFiles.length) return [];
  const strip = fs.mkdtempSync(path.join(os.tmpdir(), "wrapstrip-"));
  const metas = new Map(); // stripped filename -> {wfMeta, nodeMeta, src}
  try {
    for (const f of tsFiles) {
      const { stripped, wfMeta, nodeMeta } = extractMeta(fs.readFileSync(f, "utf8"), f);
      const b = path.basename(f);
      fs.writeFileSync(path.join(strip, b), stripped);
      metas.set(b.replace(/\.workflow\.ts$/, ".json"), { wfMeta, nodeMeta, src: f });
    }
    const { tmp, why } = convertBatch(fs.readdirSync(strip).map((b) => path.join(strip, b)), "json");
    const outs = [];
    try {
      refuseLost([...metas].filter(([jsonName]) => !fs.existsSync(path.join(tmp, jsonName)))
        .map(([jsonName, m]) => [m.src, jsonName.replace(/\.json$/, ".workflow.ts")]),
        metas.size, why, "blueprint(s)");
      for (const [jsonName, m] of metas) {
        const p = path.join(tmp, jsonName);
        const wf = graftMeta(JSON.parse(fs.readFileSync(p, "utf8")), m.wfMeta, m.nodeMeta, m.src);
        const id = wf.id || jsonName.replace(/\.json$/, "");
        const outPath = path.join(outDir, id + ".json");
        fs.mkdirSync(outDir, { recursive: true });
        fs.writeFileSync(outPath, JSON.stringify(wf, null, 2) + "\n");
        outs.push(outPath);
      }
    } finally { fs.rmSync(tmp, { recursive: true, force: true }); }
    return outs;
  } finally { fs.rmSync(strip, { recursive: true, force: true }); }
}

// ── deep equality with path reporting ─────────────────────────────────────────────────────
function firstDiff(a, b, p = "$") {
  if (typeof a !== typeof b) return `${p}: type`;
  if (a && b && typeof a === "object") {
    if (Array.isArray(a) !== Array.isArray(b)) return `${p}: shape`;
    if (Array.isArray(a)) {
      if (a.length !== b.length) return `${p}: len ${a.length}!=${b.length}`;
      for (let i = 0; i < a.length; i++) { const d = firstDiff(a[i], b[i], `${p}[${i}]`); if (d) return d; }
      return null;
    }
    for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
      if (!(k in a)) return `${p}.${k}: extra in rebuilt`;
      if (!(k in b)) return `${p}.${k}: missing in rebuilt`;
      const d = firstDiff(a[k], b[k], `${p}.${k}`); if (d) return d;
    }
    return null;
  }
  return a === b ? null : `${p}: ${jstr(a)?.slice(0, 60)} != ${jstr(b)?.slice(0, 60)}`;
}

const listJson = (dir) => fs.readdirSync(dir).filter((f) => f.endsWith(".json") && !f.includes(".bak")).sort().map((f) => path.join(dir, f));
const listTs = (dir) => fs.readdirSync(dir).filter((f) => f.endsWith(".workflow.ts")).sort().map((f) => path.join(dir, f));

// Authoring intelligence passthrough — the toolkit's OFFLINE skills (537 node schemas, docs,
// guides, template search) surfaced as first-class bbox verbs. `validate` accepts our grafted
// .workflow.ts directly (verified: marker lines tolerated).
const SKILLS = { validate: "validate", info: "node-info", schema: "node-schema", search: "search", docs: "docs", guides: "guides", list: "list" };

function main() {
  const [cmd, src, out] = process.argv.slice(2);
  if (!cmd) {
    console.error("usage: wrap.mjs render|compile <src> <outDir> | verify <jsonDir> | validate|info|schema|search|docs|guides <args>");
    process.exit(2);
  }
  ensureDeps();
  if (SKILLS[cmd]) {
    try {
      execFileSync(process.execPath, [N8NAC, "skills", SKILLS[cmd], ...process.argv.slice(3)],
        { stdio: "inherit", env: ENV });
    } catch (e) { process.exit(e.status || 1); }
    return;
  }
  if (!src) { console.error("usage: wrap.mjs " + cmd + " <src> [...]"); process.exit(2); }
  if (cmd === "render" || cmd === "compile") {
    if (!out) throw new Error("outDir required");
    const isDir = fs.statSync(src).isDirectory();
    const files = isDir ? (cmd === "render" ? listJson(src) : listTs(src)) : [src];
    const outs = cmd === "render" ? renderDir(files, out) : compileDir(files, out);
    console.log(`${cmd}: ${outs.length} workflow(s) -> ${out}`);
    return;
  }
  if (cmd === "verify") {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "wrapverify-"));
    const tsDir = path.join(tmp, "ts"), jsDir = path.join(tmp, "json");
    let ok = 0; const bad = [];
    try {
      const files = listJson(src);
      renderDir(files, tsDir);
      compileDir(listTs(tsDir), jsDir);
      for (const f of files) {
        const orig = JSON.parse(fs.readFileSync(f, "utf8"));
        const id = orig.id || path.basename(f, ".json");
        const rp = path.join(jsDir, id + ".json");
        if (!fs.existsSync(rp)) { bad.push(`${path.basename(f)}: no rebuilt output`); continue; }
        const d = firstDiff(orig, JSON.parse(fs.readFileSync(rp, "utf8")));
        if (d) bad.push(`${path.basename(f)}: ${d}`); else ok++;
      }
    } catch (e) { bad.push(String(e.message || e).slice(0, 200)); }
    finally { fs.rmSync(tmp, { recursive: true, force: true }); }
    console.log(`verify: ${ok}/${ok + bad.length} lossless`);
    for (const b of bad.slice(0, 20)) console.log("  DIFF " + b);
    process.exit(bad.length ? 1 : 0);
  }
  throw new Error("unknown command: " + cmd);
}

main();
