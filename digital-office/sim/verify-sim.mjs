#!/usr/bin/env node
/* verify-sim.mjs — tell me what is actually inside a platform-sim.html.

   The simulation is one 6 MB self-contained file, so "the drive is broken" and "you are looking at
   an old download" are indistinguishable by eye. This reads the embedded registry straight out of
   the file and reports which apps are real and which are the grey
   "מודול זה ייטען בגרסה הבאה של הסימולטור" placeholder.

       node digital-office/sim/verify-sim.mjs [path-to-platform-sim.html]

   Exit code is non-zero if any expected app is missing, so it can gate a release. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const target = process.argv[2] || path.join(HERE, '..', 'platform-sim.html');

if (!fs.existsSync(target)) {
  console.error(`✗ no such file: ${target}`);
  process.exit(2);
}

const buf = fs.readFileSync(target);
const src = buf.toString('utf8');

/* The apps the build is supposed to embed. Kept here rather than imported from build.mjs on
   purpose: this tool has to be able to judge a file that was built by a DIFFERENT (older) revision
   of build.mjs, which is exactly the case it exists for. */
const EXPECTED = [
  'any-concurrency', 'my-docs', 'localdrive', 'mailview', 'alerts',
  'machine', 'connections', 'feature-validation', 'incoming', 'wadmin',
];

const version = (src.match(/DO_VERSION\s*=\s*'([^']+)'/) || [])[1] || '?';
const md5 = crypto.createHash('md5').update(buf).digest('hex');

console.log(`file    ${target}`);
console.log(`size    ${(buf.length / 1048576).toFixed(2)} MB`);
console.log(`version ${version}`);
console.log(`md5     ${md5}\n`);

/* …and every tile the shell ITSELF offers. The list above is a floor, and a hand-kept one: the apps
   screen became an app, its tile had nothing behind it, and this tool went on saying "complete"
   for a week because the list did not name it. The tiles are read out of the file being judged
   (the shell's registry, `embed:"/a/<alias>/"`), so a tile added later is held to the same rule
   the day it is added. */
const tiles = [...new Set([...src.matchAll(/embed:"\/a\/([^"\/]+)\/"/g)].map((m) => m[1]))];
const wanted = [...new Set([...EXPECTED, ...tiles])];

const missing = [];
for (const id of wanted) {
  const m = new RegExp(`"${id.replace(/[-]/g, '\\-')}":"([A-Za-z0-9+/=]*)"`).exec(src);
  const len = m ? m[1].length : 0;
  if (len > 1000) {
    console.log(`  ✓ ${id.padEnd(20)} ${(len / 1024).toFixed(0).padStart(5)} KB embedded`);
  } else {
    console.log(`  ✗ ${id.padEnd(20)} PLACEHOLDER — this app will show "מודול זה ייטען בגרסה הבאה"`);
    missing.push(id);
  }
}

if (missing.length) {
  console.error(`\n✗ ${missing.length} app(s) are placeholders: ${missing.join(', ')}`);
  console.error('  This file is an incomplete build. Rebuild with: node digital-office/sim/build.mjs');
  process.exit(1);
}
console.log(`\n✓ all ${wanted.length} apps embedded (the shell's ${tiles.length} tiles among them) — this is a complete simulation.`);
