// What an office is to the desktop app, as pure functions: the address a person types, the origins that belong to
// the office, what a page of it may be granted, and where a link may go. main.js is the only caller; tests in
// test/offices.test.mjs. Nothing here touches Electron, the disk or the network.
'use strict';

// The plain-http offices: a computer's own (*.localhost, loopback) and an office's LAN door, which serves the console
// at http://console.<address>.sslip.io:<port> (apps/lan-console) — a private address, by number or spelled as a name.
const PRIVATE_V4 = /^(10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|127\.\d+\.\d+\.\d+)$/;

function isLocalHost(host) {
  return host === 'localhost' || host.endsWith('.localhost') || host === '[::1]' || /^127\.\d+\.\d+\.\d+$/.test(host);
}

function isPrivateHost(host) {
  if (isLocalHost(host) || PRIVATE_V4.test(host)) return true;
  // 192-168-16-100.sslip.io, console.192-168-16-100.sslip.io: the address IS the name
  const m = host.match(/(?:^|\.)(\d+)-(\d+)-(\d+)-(\d+)\.(?:sslip|nip)\.io$/);
  return !!m && PRIVATE_V4.test(m.slice(1, 5).join('.'));
}

const isIp = (host) => /^\d+\.\d+\.\d+\.\d+$/.test(host) || host.startsWith('[');

/**
 * An address as a person types it → the origins to try, best first. «staging.example.co.il» may be the office's
 * website, so its console (console.staging.example.co.il) is tried first; «localhost» is this computer's office.
 * Throws Error('empty' | 'not-an-address' | 'https-only' | 'credentials').
 */
function candidates(input) {
  let s = String(input || '').trim();
  if (!s) throw new Error('empty');
  if (/^localhost\.?(:\d+)?\/?$/i.test(s)) s = s.replace(/^localhost\.?/i, 'console.localhost');
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(s)) {
    const host = s.split(/[/:]/)[0].toLowerCase().replace(/\.$/, '');
    s = (isPrivateHost(host) ? 'http://' : 'https://') + s;
  }
  let u;
  try { u = new URL(s); } catch { throw new Error('not-an-address'); }
  if (u.username || u.password) throw new Error('credentials');
  const host = u.hostname.toLowerCase().replace(/\.$/, '');     // «console.x.co.il.» is console.x.co.il
  if (!host || (!host.includes('.') && host !== 'localhost')) throw new Error('not-an-address');
  if (u.protocol !== 'https:' && !(u.protocol === 'http:' && isPrivateHost(host))) throw new Error('https-only');
  const port = u.port ? `:${u.port}` : '';
  const typed = `${u.protocol}//${host}${port}`;
  if (host.startsWith('console.') || isIp(host)) return [typed];
  return [`${u.protocol}//console.${host}${port}`, typed];
}

/** Whether an origin is one an address can name (what the app keeps and opens: a probe's answer, a saved office). */
function isOfficeOrigin(origin) {
  try { return candidates(origin).includes(origin); } catch { return false; }
}

/** The office an origin is the console of: the domain its apps live under (console.<domain>, meet.<domain> …). */
function scopeOf(origin) {
  const u = new URL(origin);
  const host = u.hostname.toLowerCase();
  const domain = host.startsWith('console.') ? host.slice('console.'.length) : host;
  return { origin: u.origin, protocol: u.protocol, host, domain, ip: isIp(domain) };
}

/** Whether a URL is the office's own: its console, or any app under its domain, on the office's own scheme. */
function inScope(url, scope) {
  let u;
  try { u = new URL(url); } catch { return false; }
  if (u.protocol !== scope.protocol) return false;
  const host = u.hostname.toLowerCase();
  if (scope.ip) return u.origin === scope.origin;
  return host === scope.domain || host.endsWith(`.${scope.domain}`);
}

/**
 * What a page may be granted (Electron's permission names). Camera, microphone and screen sharing: only the
 * office's meetings (meet.<domain>), which are Jitsi. Notifications, the clipboard and full screen: any page of the
 * office. Everything else — reading the clipboard (no office page does), location, MIDI, USB, HID, serial, window
 * management … — nobody.
 */
function mayGrant(permission, requestingUrl, scope) {
  if (!inScope(requestingUrl, scope)) return false;
  const host = new URL(requestingUrl).hostname.toLowerCase();
  if (permission === 'media' || permission === 'display-capture') return host.startsWith('meet.');
  return ['notifications', 'clipboard-sanitized-write', 'fullscreen', 'pointerLock'].includes(permission);
}

/** Where a link that leaves the office may go: the system's browser or mail, never a file or a program. */
function mayOpenOutside(url) {
  try { return ['https:', 'http:', 'mailto:', 'tel:'].includes(new URL(url).protocol); } catch { return false; }
}

/** How the rail and the tray name an office: «this computer», or the first word of its domain (staging, exampleu …). */
function labelOf(origin) {
  const { domain } = scopeOf(origin);
  if (isLocalHost(domain)) return { local: true, label: 'localhost' };
  return { local: false, label: isIp(domain) ? domain : domain.split('.')[0] };
}

/**
 * One session (cookies, storage) per office, so being signed in to two offices never mixes them. Two origins never
 * share a name: a hyphen is doubled before every other mark becomes one (console.a-b.co.il ≠ console.a.b.co.il).
 */
const partitionFor = (origin) =>
  `persist:office-${origin.toLowerCase().replace(/-/g, '--').replace(/[^a-z0-9-]+/g, '-')}`;

/**
 * A probe's answers → what the address is. `manifest`: the response to <origin>/manifest.webmanifest asked with no
 * cookies and no redirect followed ({status, location, json}). The console answers its manifest (an office with no
 * sign-in in front), or — what every office does — the edge answers with its sign-in: a redirect to a /login that
 * carries `rd`, back to this console.
 */
function readProbe(origin, manifest) {
  if (manifest.status === 200 && manifest.json && manifest.json.name && Array.isArray(manifest.json.icons)) {
    return { kind: 'office', origin, name: manifest.json.name };
  }
  if (manifest.status >= 300 && manifest.status < 400 && manifest.location) {
    let to;
    try { to = new URL(manifest.location, origin); } catch { return { kind: 'not-office', origin }; }
    const rd = to.searchParams.get('rd') || '';
    if (/\/login\/?$/.test(to.pathname) && rd.startsWith(origin)) return { kind: 'signin', origin };
  }
  return { kind: 'not-office', origin };
}

module.exports = {
  candidates, isOfficeOrigin, scopeOf, inScope, mayGrant, mayOpenOutside, labelOf, partitionFor, readProbe, isPrivateHost,
};
