/* test_compile_blame.mjs — a blueprint that cannot be converted is NAMED, with the reason, and it
 * is the only one named.
 *
 *   node apps/n8n/test_compile_blame.mjs
 *
 * Every push compiles an app's whole blueprint directory in one converter process. The converter
 * converts what it can, exits 0, and says per file why it could not — and wrap.mjs used to throw
 * that away and blame the first input that had no output: one name, no reason. A push of indox
 * once failed on `indoxV2ActionsGDoc01`, a file that compiled clean by itself, and the session
 * that hit it debugged the wrong file (issues/convert-batch-blames-an-innocent-file.yaml).
 *
 * A directory is built from one real blueprint: itself, and twins of it that are no workflow class
 * any more. Local conversion only — nothing is pushed and no n8n is asked anything.
 */
import { spawnSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const wrap = join(here, 'tooling', 'wrap.mjs');
const good = join(here, '..', '..', 'apps', 'google-workspace-agent', 'blueprint', 'n8n', 'gwaHealthCheck01.workflow.ts');

let passed = 0;
function ok(cond, what) {
  if (!cond) { console.error('FAIL  ' + what); process.exit(1); }
  passed += 1;
}
const compile = (src, out) => {
  const r = spawnSync(process.execPath, [wrap, 'compile', src, out], { encoding: 'utf8' });
  return { code: r.status, said: (r.stdout || '') + (r.stderr || '') };
};

const dir = mkdtempSync(join(tmpdir(), 'blame-'));
try {
  const src = join(dir, 'src'), out = join(dir, 'out');
  mkdirSync(src);
  const broken = readFileSync(good, 'utf8').replace(/^export class /m, 'export clazz ');
  ok(broken !== readFileSync(good, 'utf8'), 'the fixture blueprint has a class to break');
  copyFileSync(good, join(src, 'gwaHealthCheck01.workflow.ts'));
  writeFileSync(join(src, 'aaaBroken01.workflow.ts'), broken);       // sorts BEFORE the good one
  writeFileSync(join(src, 'zzzBroken01.workflow.ts'), broken);       // ...and after it

  const all = compile(src, out);
  ok(all.code !== 0, 'a directory with a blueprint that does not convert fails');
  ok(/2 of 3 blueprint\(s\) did not convert/.test(all.said), 'it says how many of how many');
  for (const name of ['aaaBroken01', 'zzzBroken01']) {
    const line = all.said.split('\n').find((l) => l.includes(name + '.workflow.ts:')) || '';
    ok(line, `${name} is named`);
    ok(/No class with @workflow decorator/.test(line), `${name} is named WITH the converter's reason`);
  }
  ok(!all.said.split('\n').some((l) => /^\s+\S*gwaHealthCheck01\.workflow\.ts:/.test(l)), 'the blueprint that is fine is not blamed');
  ok(!existsSync(out) || readdirSync(out).length === 0, 'nothing is written for a directory that did not wholly convert');

  const one = compile(join(src, 'gwaHealthCheck01.workflow.ts'), join(dir, 'one'));
  ok(one.code === 0 && existsSync(join(dir, 'one', 'gwaHealthCheck01.json')), 'the good blueprint in that same directory still compiles by itself');

  const alone = compile(join(src, 'zzzBroken01.workflow.ts'), join(dir, 'alone'));
  ok(alone.code !== 0 && /1 of 1 blueprint\(s\) did not convert/.test(alone.said) && /No class with @workflow decorator/.test(alone.said),
    'a broken blueprint compiled by itself says the same reason');
} finally { rmSync(dir, { recursive: true, force: true }); }

console.log(`compile blame: ${passed} checks passed`);
