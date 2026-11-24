// The office on this computer: whether it answers, whether it is installed, and starting it through the platform's
// own `dgo` (packaging/dgo), which hands `run` to bbox — bbox.cmd into the project's WSL engine on Windows, the Lima
// engine on a Mac, the service on Linux. The engine is its own service: closing the app never stops the office.
'use strict';
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { candidates, PROBE_PATH, readProbe } = require('./offices');

// this computer's office: where the address «localhost» leads, by the one rule every typed address follows
const ORIGIN = candidates('localhost')[0];
// Where a person gets the office for this computer (the ≤5 MB dgo-install that installs the engine and this app).
// The download's own domain is the owner's step (DGO-1980); until then, the company's site.
const INSTALL_URL = 'https://digital-office.co.il/';

/**
 * Whether the office here answers: its console's own record, or the sign-in's redirect in front of it — read as every
 * typed address is (offices.js readProbe). `ask` is main.js's. Any answer under 500 used to count, so a computer with
 * another web server on port 80 was told «the office is running on this computer» and offered «Open»: the first
 * installers' proof on a clean Windows machine showed exactly that (v0.3.5, 2026-11-24, DGO-2188).
 */
async function running(ask) {
  const r = await ask(`${ORIGIN}${PROBE_PATH}`);
  return readProbe(ORIGIN, r || {}).kind !== 'not-office';
}

/**
 * After `dgo run` ended well: whether the office answers AS an office, asked every `gapMs` and `tries` times at most.
 * Its edge is up seconds before its console and its sign-in are, and what it answers until then (a 404) is no office
 * to running() — so «starting» has to last until it is one, or the button comes back over an office that is coming up
 * and a second press runs `dgo run` again (the second reader of running()'s reading, 2026-11-24).
 */
async function comesUp(ask, { tries = 30, gapMs = 2000, sleep = (ms) => new Promise((r) => setTimeout(r, ms)) } = {}) {
  for (let i = 0; i < tries; i++) {
    if (await running(ask)) return true;
    if (i < tries - 1) await sleep(gapMs);
  }
  return false;
}

/**
 * The `dgo` this computer has: $DGO_BIN, then $DGO_ROOT's build, then the PATH — and the folders a shell adds but an
 * app started from the Dock or Finder never gets (its PATH is /usr/bin:/bin:/usr/sbin:/sbin).
 */
function findDgo(env = process.env, platform = process.platform) {
  const exe = platform === 'win32' ? 'dgo.exe' : 'dgo';
  const home = env.HOME || env.USERPROFILE || '';
  const shellDirs = platform === 'win32' ? [] : ['/usr/local/bin', '/opt/homebrew/bin', home && path.join(home, '.local', 'bin')];
  const tries = [env.DGO_BIN, env.DGO_ROOT && path.join(env.DGO_ROOT, 'packaging', 'dgo', exe),
    ...[...String(env.PATH || '').split(path.delimiter), ...shellDirs].filter(Boolean).map((d) => path.join(d, exe))];
  return tries.find((p) => p && fs.existsSync(p) && fs.statSync(p).isFile()) || null;
}

/** `dgo run`, its lines handed to onLine as they come (colour codes taken off); resolves with its exit code. */
function start(dgo, onLine) {
  return new Promise((resolve) => {
    const child = spawn(dgo, ['run'], { windowsHide: true, env: process.env });
    let rest = '';
    const take = (chunk) => {
      const text = rest + chunk.toString('utf8');
      const parts = text.split(/\r?\n/);
      rest = parts.pop();
      for (const line of parts) if (line.trim()) onLine(line.replace(/\x1b\[[0-9;]*[A-Za-z]/g, ''));
    };
    child.stdout.on('data', take);
    child.stderr.on('data', take);
    child.on('error', (e) => { onLine(String(e.message)); resolve(-1); });
    child.on('close', (code) => { if (rest.trim()) onLine(rest); resolve(code); });
  });
}

module.exports = { ORIGIN, INSTALL_URL, running, comesUp, findDgo, start };
