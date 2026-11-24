// The office on this computer: whether it answers, whether it is installed, and starting it through the platform's
// own `dgo` (packaging/dgo), which hands `run` to bbox — bbox.cmd into the project's WSL engine on Windows, the Lima
// engine on a Mac, the service on Linux. The engine is its own service: closing the app never stops the office.
'use strict';
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { candidates, PROBE_PATH } = require('./offices');

// this computer's office: where the address «localhost» leads, by the one rule every typed address follows
const ORIGIN = candidates('localhost')[0];
// Where a person gets the office for this computer (the ≤5 MB dgo-install that installs the engine and this app).
// The download's own domain is the owner's step (DGO-1980); until then, the company's site.
const INSTALL_URL = 'https://digital-office.co.il/';

/** Whether the office here answers: its console, or the sign-in's redirect in front of it. `ask` is main.js's. */
async function running(ask) {
  const r = await ask(`${ORIGIN}${PROBE_PATH}`);
  return r.status > 0 && r.status < 500;
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

module.exports = { ORIGIN, INSTALL_URL, running, findDgo, start };
