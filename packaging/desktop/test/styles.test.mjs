// node --test packaging/desktop/test/*.test.mjs (or `npm test` there) — the app's own screens name no style variable
// their sheet never gives a value. shell.css drew the whole first run in the engine's default serif: with no `--font`
// anywhere in the sheet, `font:15px/1.5 var(--font)` is no declaration at all and the page falls to the default
// family — seen in the first installers' proof pictures and on a Windows office (v0.3.5, 2026-11-24, DGO-2188).
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';

const ui = new URL('../src/ui/', import.meta.url);
const sheet = readFileSync(new URL('shell.css', ui), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const defined = new Set([...sheet.matchAll(/(--[A-Za-z0-9_-]+)\s*:/g)].map((m) => m[1]));
// a use WITH a fallback (`var(--x, …)`) draws something either way; one without it needs the value
const uses = (text) => [...text.matchAll(/var\(\s*(--[A-Za-z0-9_-]+)\s*(,)?/g)].filter((m) => !m[2]).map((m) => m[1]);

test('every variable the sheet uses without a fallback has a value in the sheet', () => {
  const missing = [...new Set(uses(sheet))].filter((v) => !defined.has(v));
  assert.deepEqual(missing, []);
});

test('…and so has every one the screens and their scripts use inline', () => {
  const missing = new Set();
  for (const name of readdirSync(ui)) {
    if (!/\.(html|js)$/.test(name)) continue;
    for (const v of uses(readFileSync(new URL(name, ui), 'utf8'))) if (!defined.has(v)) missing.add(`${name}: ${v}`);
  }
  assert.deepEqual([...missing], []);
});

test("the family list is the office's: system-ui right after the family the sheet gives its Hebrew faces (G27)", () => {
  const font = sheet.match(/--font\s*:\s*([^;}]+)/);
  assert.ok(font, 'no --font in shell.css');
  assert.match(font[1], /^"Segoe UI",\s*system-ui,/);
  assert.match(font[1].trim(), /sans-serif$/);
});
