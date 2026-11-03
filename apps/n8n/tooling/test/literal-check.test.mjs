// literal-check.test.mjs — a jsCode that is not ONE well-formed literal is refused, naming the
// backtick (DGO-584).
//
//   node --test apps/n8n/tooling/test/literal-check.test.mjs
//
// The scanner's own cases need nothing installed. The cases through wrap.mjs (compile refuses the
// raw fixture, compiles the escaped one to the full body, verify is red/green on a file and on a
// directory, validate refuses) run only where the pinned toolchain is installed — beside wrap.mjs,
// or under ~/.cache/bbox-n8n-tooling on a /mnt/c checkout — and say so when skipped; they never
// trigger the `npm ci` wrap.mjs would otherwise start.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { checkCodeLiterals } from "../literal-check.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const tooling = path.join(here, "..");
const wrap = path.join(tooling, "wrap.mjs");
const RAW = path.join(here, "fixtures", "backtickRaw01.workflow.ts");
const ESCAPED = path.join(here, "fixtures", "backtickEscaped01.workflow.ts");
const rawText = fs.readFileSync(RAW, "utf8");
const escapedText = fs.readFileSync(ESCAPED, "utf8");

const lineCol = (text, offset) => {
  const before = text.slice(0, offset);
  return { line: before.split("\n").length, col: offset - before.lastIndexOf("\n") };
};
const culprit = lineCol(rawText, rawText.indexOf("closed by `") + "closed by ".length);   // the raw backtick

// A minimal blueprint around one jsCode body, in the transformer's notation.
const blueprint = (body, key = "jsCode") => `import { workflow, node, links } from '@n8n-as-code/transformer';
@workflow({ id: 'x01', name: 'x', active: false, settings: { executionOrder: 'v1' } })
export class X {
    @node({ id: 'a', name: 'Shape', type: 'n8n-nodes-base.code', version: 2, position: [0, 0] })
    Shape = {
        ${key}: \`${body}\`,
        options: {},
    };
}
`;

test("the raw fixture: one finding, the node named, the culprit backtick's line:col", () => {
  const f = checkCodeLiterals(rawText, RAW);
  assert.equal(f.length, 1, "exactly one finding (the first; later positions would be noise)");
  assert.equal(f[0].key, "jsCode");
  assert.equal(f[0].node, "Shape");
  assert.match(f[0].message, /raw backtick/);
  assert.match(f[0].message, new RegExp(`:${culprit.line}:${culprit.col}\\b`), "the raw backtick's own position is in the message");
  assert.match(f[0].message, /Escape every backtick inside the code as \\`/);
});

test("the escaped fixture: no finding", () => {
  assert.deepEqual(checkCodeLiterals(escapedText, ESCAPED), []);
});

test("every shape of a raw backtick is a finding; the escapes and the substitutions are not", () => {
  const raw = [
    "// answers ({\"by\": `name`})\nreturn 1;",            // word after the backtick
    "// answers ({\"by\": ` name `})\nreturn 1;",
    "// answers ({\"by\": `, \"n\"})\nreturn 1;",           // a comma after it
    "// answers ({\"by\": `})\nreturn 1;",                  // a brace after it — the shape the converter swallowed whole
    "// see (`)\nreturn 1;",                                // a paren after it
    "// uses `\nreturn 1;",                                 // end of line after it
    "// ``\nreturn 1;",                                     // two adjacent
    "// `: 1\nreturn 1;",
    "// answers ({\"by\": `\u2026`})\nreturn 1;",           // the item's own text
    "// answers ({\"by\": `<who>`})\nreturn 1;",            // TypeScript parses this one (a comparison)
    "const s = `x`;\nreturn s;",                           // code, not a comment
  ];
  for (const body of raw) {
    const f = checkCodeLiterals(blueprint(body), "t.ts");
    assert.equal(f.length, 1, `a finding for ${JSON.stringify(body)}`);
    assert.equal(f[0].node, "Shape");
  }
  const fine = [
    "// answers ({\"by\": \\`name\\`})\nreturn 1;",         // escaped
    "const s = \\`x\\${y}\\`;\nreturn s;",                  // escaped, with an escaped substitution
    "const s = ${'`' + \"x\" + '`'};\nreturn s;",           // a real substitution holding backticks and braces
    "const o = ${ { a: { b: 1 } }.a.b };\nreturn o;",       // nested braces inside a substitution
    "// it's \"quoted\" and /slashed/ \nreturn 1;",
  ];
  for (const body of fine) assert.deepEqual(checkCodeLiterals(blueprint(body), "t.ts"), [], `no finding for ${JSON.stringify(body)}`);
});

test("pythonCode and SQL are literals too; backticks in the file's own comments and strings are not", () => {
  assert.equal(checkCodeLiterals(blueprint("# uses `x`\nreturn 1", "pythonCode"), "t.ts")[0].key, "pythonCode");
  assert.equal(checkCodeLiterals(blueprint("SELECT `col` FROM t", "query"), "t.ts")[0].key, "query");
  const ok = "// a TypeScript comment with `backticks`\n" + blueprint("return 1;").replace("options: {}", "options: { note: 'a `tick` in a string', re: /`/ }");
  assert.deepEqual(checkCodeLiterals(ok, "t.ts"), []);
});

test("the fleet: every blueprint of every app is one well-formed literal per parameter", () => {
  const apps = path.join(tooling, "..", "..");
  const files = fs.readdirSync(apps).flatMap((a) => {
    const d = path.join(apps, a, "blueprint", "n8n");
    return fs.existsSync(d) ? fs.readdirSync(d).filter((f) => f.endsWith(".workflow.ts")).map((f) => path.join(d, f)) : [];
  });
  assert.ok(files.length > 50, `the fleet is there (${files.length} files)`);
  const bad = files.flatMap((f) => checkCodeLiterals(fs.readFileSync(f, "utf8"), f)).map((x) => x.message);
  assert.deepEqual(bad, []);
});

// ── through wrap.mjs (needs the pinned toolchain) ────────────────────────────────────────────────
const cacheRoot = path.join(os.homedir(), ".cache", "bbox-n8n-tooling");
const installed = fs.existsSync(path.join(tooling, "node_modules", "n8nac", "dist", "index.js")) ||
  (fs.existsSync(cacheRoot) && fs.readdirSync(cacheRoot).some((h) => fs.existsSync(path.join(cacheRoot, h, "node_modules", "n8nac", "dist", "index.js"))));
const run = (...args) => {
  const r = spawnSync(process.execPath, [wrap, ...args], { encoding: "utf8" });
  return { code: r.status, said: (r.stdout || "") + (r.stderr || "") };
};
// The body the escaped fixture means: its literal, unescaped the way TypeScript reads it.
const meant = (() => {
  const s = escapedText.indexOf("jsCode: `") + 9;
  return escapedText.slice(s, escapedText.indexOf("`,\n", s)).replace(/\\([`$\\])/g, "$1");
})();
const skip = installed ? false : "toolchain not installed (apps/n8n/tooling/node_modules or ~/.cache/bbox-n8n-tooling) — `bbox n8n code validate <any>` installs it";

test("compile refuses the raw fixture at the backtick, and compiles the escaped one to its whole body", { skip }, () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "literal-"));
  try {
    const red = run("compile", RAW, path.join(dir, "red"));
    assert.notEqual(red.code, 0, "red exits non-zero");
    assert.match(red.said, /not well-formed TypeScript/);
    assert.match(red.said, new RegExp(`backtickRaw01\\.workflow\\.ts:${culprit.line}:${culprit.col}\\b`), "names the raw backtick");
    assert.ok(!fs.existsSync(path.join(dir, "red", "backtickRaw01.json")), "nothing written for it");

    const green = run("compile", ESCAPED, path.join(dir, "green"));
    assert.equal(green.code, 0, "green exits 0: " + green.said.slice(-300));
    const wf = JSON.parse(fs.readFileSync(path.join(dir, "green", "backtickEscaped01.json"), "utf8"));
    const shape = wf.nodes.find((n) => n.name === "Shape");
    assert.equal(shape.parameters.jsCode, meant, "the stored body is the whole literal");
    assert.equal(shape.parameters.jsCode.length, meant.length);
    assert.ok(shape.parameters.jsCode.includes("closed by `}`"), "the backticks arrived as backticks");
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test("verify runs on a file and on a directory: red on the raw fixture, green on the escaped one", { skip }, () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "literal-"));
  try {
    const redFile = run("verify", RAW);
    assert.equal(redFile.code, 1);
    assert.match(redFile.said, /verify: 0\/1 lossless/);
    assert.match(redFile.said, new RegExp(`backtickRaw01\\.workflow\\.ts:${culprit.line}:${culprit.col}\\b`));
    assert.doesNotMatch(redFile.said, /ENOTDIR|ENOENT/, "no scandir crash on a file");

    const greenFile = run("verify", ESCAPED);
    assert.equal(greenFile.code, 0, greenFile.said.slice(-300));
    assert.match(greenFile.said, /verify: 1\/1 lossless/);

    fs.copyFileSync(ESCAPED, path.join(dir, "backtickEscaped01.workflow.ts"));
    const greenDir = run("verify", dir);
    assert.equal(greenDir.code, 0, greenDir.said.slice(-300));
    assert.match(greenDir.said, /verify: 1\/1 lossless/);
    assert.doesNotMatch(greenDir.said, /ENOTDIR|ENOENT/, "no scandir crash on a directory of code");

    const redDir = run("verify", path.join(here, "fixtures"));
    assert.equal(redDir.code, 1);
    assert.match(redDir.said, /backtickRaw01\.workflow\.ts:\d+:\d+/);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test("the TypeScript syntax net: a file the lexer passes but TypeScript cannot parse is refused with the parser's position", { skip }, () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "literal-"));
  try {
    const clazz = escapedText.replace(/^export class /m, "export clazz ");    // no backtick is wrong; the class is
    assert.deepEqual(checkCodeLiterals(clazz, "t.ts"), [], "the lexer has nothing to say about it");
    fs.writeFileSync(path.join(dir, "clazz01.workflow.ts"), clazz);
    const r = run("compile", path.join(dir, "clazz01.workflow.ts"), path.join(dir, "out"));
    assert.notEqual(r.code, 0);
    assert.match(r.said, /not well-formed TypeScript/);
    assert.match(r.said, /clazz01\.workflow\.ts:\d+:\d+: .+ — a TypeScript syntax error/, "the parser's own line:col and message");
    assert.doesNotMatch(r.said, /syntax net is off/);
    assert.ok(!fs.existsSync(path.join(dir, "out", "backtickEscaped01.json")), "nothing written for it");
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test("validate no longer says 'valid' of the raw fixture", { skip }, () => {
  const r = run("validate", RAW);
  assert.notEqual(r.code, 0);
  assert.match(r.said, new RegExp(`backtickRaw01\\.workflow\\.ts:${culprit.line}:${culprit.col}\\b`));
  assert.doesNotMatch(r.said, /Workflow is valid/);
});
