// node --test packaging/desktop/test/*.test.mjs (or `npm test` there) — the desktop app's pure rules (src/offices.js), no Electron needed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const o = createRequire(import.meta.url)('../src/offices.js');
const HP = o.scopeOf('http://console.localhost');
const VPS = o.scopeOf('https://console.staging.digital-office.co.il');
const LAN = o.scopeOf('http://console.192-168-16-100.sslip.io:8081');

test('an address as a person types it becomes the console to try', () => {
  assert.deepEqual(o.candidates('console.staging.digital-office.co.il'), ['https://console.staging.digital-office.co.il']);
  assert.deepEqual(o.candidates('https://console.staging.digital-office.co.il/#/m/indox'), ['https://console.staging.digital-office.co.il']);
  // the office's domain may be its website: its console first
  assert.deepEqual(o.candidates('staging.digital-office.co.il'),
    ['https://console.staging.digital-office.co.il', 'https://staging.digital-office.co.il']);
  assert.deepEqual(o.candidates('localhost'), ['http://console.localhost']);
  assert.deepEqual(o.candidates('console.localhost'), ['http://console.localhost']);
  assert.deepEqual(o.candidates('console.192-168-16-100.sslip.io:8081'), ['http://console.192-168-16-100.sslip.io:8081']);
});

test('a public office is https only, and an address never carries a password', () => {
  assert.throws(() => o.candidates('http://console.example.co.il'), /https-only/);
  assert.throws(() => o.candidates('http://console.8-8-8-8.sslip.io'), /https-only/);
  assert.throws(() => o.candidates('https://me:secret@console.example.co.il'), /credentials/);
  assert.throws(() => o.candidates('   '), /empty/);
  assert.throws(() => o.candidates('office'), /not-an-address/);
});

test('the office is its console and every app under its domain, on its own scheme', () => {
  assert.ok(o.inScope('https://console.staging.digital-office.co.il/#/m/mail', VPS));
  assert.ok(o.inScope('https://meet.staging.digital-office.co.il/room', VPS));
  assert.ok(o.inScope('https://auth.staging.digital-office.co.il/login?rd=x', VPS));
  assert.ok(!o.inScope('http://meet.staging.digital-office.co.il/', VPS));             // scheme downgrade
  assert.ok(!o.inScope('https://staging.digital-office.co.il.evil.com/', VPS));
  assert.ok(!o.inScope('https://evilstaging.digital-office.co.il/', VPS));
  assert.ok(!o.inScope('https://accounts.google.com/o/oauth2/auth', VPS));
  assert.ok(o.inScope('http://mail.localhost/', HP) && !o.inScope('http://localhost.evil.com/', HP));
  assert.ok(o.inScope('http://auth.192-168-16-100.sslip.io:8081/login', LAN));
  assert.ok(!o.inScope('file:///etc/passwd', HP) && !o.inScope('not a url', HP));
});

test('camera, microphone and the screen go to the office\'s meetings only', () => {
  assert.ok(o.mayGrant('media', 'https://meet.staging.digital-office.co.il/x', VPS));
  assert.ok(o.mayGrant('display-capture', 'https://meet.staging.digital-office.co.il/x', VPS));
  assert.ok(!o.mayGrant('media', 'https://console.staging.digital-office.co.il/', VPS));
  assert.ok(!o.mayGrant('media', 'https://meet.example.com/', VPS));
  assert.ok(o.mayGrant('notifications', 'https://console.staging.digital-office.co.il/', VPS));
  assert.ok(!o.mayGrant('notifications', 'https://example.com/', VPS));
  for (const p of ['clipboard-read', 'geolocation', 'midi', 'hid', 'serial', 'usb', 'window-management', 'openExternal', 'unknown']) {
    assert.ok(!o.mayGrant(p, 'https://console.staging.digital-office.co.il/', VPS), p);
  }
});

test('a link that leaves the office goes to the system browser or mail, never to a file or a program', () => {
  for (const u of ['https://example.com', 'http://example.com', 'mailto:person87@example.com', 'tel:+972500000000']) assert.ok(o.mayOpenOutside(u), u);
  for (const u of ['file:///C:/Windows/System32/calc.exe', 'smb://host/share', 'ms-msdt:/id', 'javascript:alert(1)', 'x']) {
    assert.ok(!o.mayOpenOutside(u), u);
  }
});

test('the rail names an office by the first word of its domain, and this computer\'s as local', () => {
  assert.deepEqual(o.labelOf('https://console.staging.digital-office.co.il'), { local: false, label: 'staging' });
  assert.deepEqual(o.labelOf('http://console.localhost'), { local: true, label: 'localhost' });
  assert.deepEqual(o.labelOf('https://192.168.1.5:8443'), { local: false, label: '192.168.1.5' });
});

test('each office has its own session, and two offices never share one', () => {
  assert.equal(o.partitionFor('https://console.staging.digital-office.co.il'), 'persist:office-https-console-staging-digital--office-co-il');
  assert.notEqual(o.partitionFor('http://console.localhost'), o.partitionFor('https://console.localhost'));
  // the second reader's case: a hyphen and a dot once gave the same name
  assert.notEqual(o.partitionFor('https://console.a-b.co.il'), o.partitionFor('https://console.a.b.co.il'));
});

test('what a probe answers is an origin the app keeps — the console tried first, or the address as typed', () => {
  // only the typed host answered: it must still be addable (the second reader's first finding)
  for (const origin of o.candidates('office.example.co.il')) assert.ok(o.isOfficeOrigin(origin), origin);
  assert.ok(o.isOfficeOrigin('http://console.localhost'));
  assert.ok(!o.isOfficeOrigin('http://console.example.co.il'));     // public office over http
  assert.ok(!o.isOfficeOrigin('https://console.example.co.il/x'));  // a page, not an origin
  assert.deepEqual(o.candidates('console.example.co.il.'), ['https://console.example.co.il']);   // a trailing dot
  assert.deepEqual(o.candidates('localhost.'), ['http://console.localhost']);                    // …which keeps http
});

test('a probe tells an office from anything else', () => {
  const vps = 'https://console.staging.digital-office.co.il';
  // what vps1 answered, 2026-11-18
  assert.deepEqual(o.readProbe(vps, { status: 302, location: 'https://auth.staging.digital-office.co.il/login?rd=https%3A%2F%2Fconsole.staging.digital-office.co.il%2Fmanifest.webmanifest&st=1' }),
    { kind: 'signin', origin: vps });
  assert.deepEqual(o.readProbe(vps, { status: 200, json: { name: 'הלשכה הדיגיטלית', icons: [] } }),
    { kind: 'office', origin: vps, name: 'הלשכה הדיגיטלית' });
  assert.equal(o.readProbe(vps, { status: 302, location: 'https://evil.example/login?rd=https://other.example/' }).kind, 'not-office');
  assert.equal(o.readProbe(vps, { status: 404 }).kind, 'not-office');
  assert.equal(o.readProbe(vps, { status: 200, json: { hello: 1 } }).kind, 'not-office');
});
