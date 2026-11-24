// node --test packaging/desktop/test/*.test.mjs (or `npm test` there) — the app's icons are where its build and its
// windows look for them, at the sizes they are named for (scripts/app_icons.py renders them from the mark).
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const at = (name) => new URL(`../build/icons/${name}`, import.meta.url);

function pngSize(name) {
  const head = readFileSync(at(name)).subarray(0, 24);
  assert.deepEqual([...head.subarray(0, 8)], [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a], `${name} is not a PNG`);
  return [head.readUInt32BE(16), head.readUInt32BE(20)];
}

test('the icon every installer is made from is 512 square (electron-builder: the .ico, the .icns, the launcher)', () => {
  assert.deepEqual(pngSize('icon-512.png'), [512, 512]);
  const conf = readFileSync(new URL('../electron-builder.yml', import.meta.url), 'utf8');
  assert.match(conf, /^icon: build\/icons\/icon-512\.png$/m);
});

test("the window's, the tray's and a notice's icon is 192 square (src/main.js iconPath)", () => {
  assert.deepEqual(pngSize('icon-192.png'), [192, 192]);
});
