/**
 * THE SIBLING APPS, READ BY THE BROWSER — drive and mail, same origin, under the console shell.
 *
 * Owner rule (2026-09-02): the INDOX BFF never talks to another application. What the sync page
 * needs from the source side — which connections exist, what a folder id is called, whether a
 * mailbox still logs in, what is sitting at the source right now — is read HERE, by the browser,
 * through the same `/a/<app>/` mounts the console already serves (RELEASE-DECISIONS N4: browser-side
 * cross-app reads are allowed; the BFF rule is about the server).
 *
 * Everything degrades explicitly. Outside the console shell there is no sibling to ask, so every
 * reader answers `null`/`[]` with a stated reason (`SIBLINGS_NOTE`), and the screens render "לא
 * נבדק" rather than a guess. Lists are cached per session (one connection catalog, one folder list
 * per drive connection, one label list per mailbox) because the card grid asks the same questions
 * for every pipe; `refresh` on the loaders bypasses the cache after a create.
 */
import { BASE_PATH } from './api';

const EMBED_RE = /\/a\/[^/]+\/?$/;
/** the app is mounted at `<console>/a/<alias>/` — the only place a sibling is reachable from */
export const IN_CONSOLE = EMBED_RE.test(BASE_PATH);
/** the console root (`/` or `/something/`), for the shell's own `/api/svc/<service>/…` proxies */
export const consoleRoot = (): string | null => (IN_CONSOLE ? BASE_PATH.replace(EMBED_RE, '') : null);
export const sibling = (app: string): string | null => {
  const root = consoleRoot();
  return root === null ? null : `${root}/a/${app}`;
};
export const SIBLINGS_NOTE =
  'מחוץ למעטפת הקונסול אין גישה לאפליקציות הדרייב והמייל — שמות, בריאות חיבורים ורשימות אינם נקראים.';

/** the mail app's rule editor (N1: the organizer JSON is the ONE store of label rules) */
export const mailOrganizerUrl = (): string | null => {
  const root = consoleRoot();
  return root === null ? null : `${root}/#/m/mail/organizer`;
};

async function sfetch<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, {
    credentials: 'same-origin',
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try {
      const body = (await r.json()) as { error?: unknown; message?: unknown };
      const m = body?.message ?? body?.error;
      if (typeof m === 'string' && m.trim()) msg = m;
    } catch {
      /* a non-JSON error page — the status is the message */
    }
    throw new Error(`${url.split('/a/')[1] || url.split('/api/')[1] || url}: ${msg}`);
  }
  return (await r.json()) as T;
}

export type ConnKind = 'drive' | 'gmail';
export interface Conn {
  id: string;
  kind: ConnKind;
  label: string;
  identity: string;
  protocol?: string;
  account_hint?: string;
}
export interface Folder { id: string; name: string; parent?: string | null }
export interface SourceFile {
  id: string;
  name: string;
  created?: string | null;
  modified?: string | null;
  size?: number | null;
}
export interface SourceMessage {
  id: string;
  subject: string;
  from: string;
  date: string;
}

/* ── per-session caches ──────────────────────────────────────────────────────────────────────── */
let connsCache: Promise<Conn[]> | null = null;
const foldersCache = new Map<string, Promise<Folder[]>>();
const labelsCache = new Map<string, Promise<string[]>>();
const probeCache = new Map<string, { at: number; p: Promise<Probe> }>();
const PROBE_TTL_MS = 60_000;

function withCache<T>(map: Map<string, Promise<T>>, key: string, refresh: boolean, make: () => Promise<T>): Promise<T> {
  if (!refresh) {
    const hit = map.get(key);
    if (hit) return hit;
  }
  const p = make().catch((e) => {
    map.delete(key); // a failure is not a fact worth remembering for the session
    throw e;
  });
  map.set(key, p);
  return p;
}

interface RawConn { id: string; label?: string; account_hint?: string; protocol?: string; profile_id?: string }

async function driveConnections(): Promise<Conn[]> {
  const base = sibling('drive');
  if (!base) return [];
  const r = await sfetch<{ connections?: RawConn[] }>(`${base}/connections`);
  return (r.connections || []).map((c) => ({
    id: c.id,
    kind: 'drive',
    label: c.label || c.account_hint || c.id,
    identity: [c.protocol, c.profile_id, c.account_hint].filter(Boolean).join(' · '),
    protocol: c.protocol,
    account_hint: c.account_hint,
  }));
}
async function mailConnections(): Promise<Conn[]> {
  const base = sibling('mailview');
  if (!base) return [];
  const r = await sfetch<{ connections?: RawConn[] }>(`${base}/api/connections`);
  return (r.connections || []).map((c) => ({
    id: c.id,
    kind: 'gmail',
    label: c.label || c.account_hint || c.id,
    identity: [c.protocol, c.account_hint].filter(Boolean).join(' · '),
    protocol: c.protocol,
    account_hint: c.account_hint,
  }));
}

/** every connection of both siblings. One catalog per session; a sibling that fails to answer
 *  is reported in `errors` rather than silently missing from the list. */
export interface ConnCatalog { conns: Conn[]; errors: string[] }
export function connections(refresh = false): Promise<ConnCatalog> {
  if (!refresh && connsCache) return connsCache.then((conns) => ({ conns, errors: [] }));
  const errors: string[] = [];
  const p = Promise.all([
    driveConnections().catch((e: unknown) => { errors.push(e instanceof Error ? e.message : String(e)); return [] as Conn[]; }),
    mailConnections().catch((e: unknown) => { errors.push(e instanceof Error ? e.message : String(e)); return [] as Conn[]; }),
  ]).then(([d, m]) => [...d, ...m]);
  connsCache = p;
  return p.then((conns) => ({ conns, errors }));
}

export function driveFolders(connId: string, refresh = false): Promise<Folder[]> {
  const base = sibling('drive');
  if (!base || !connId) return Promise.resolve([]);
  return withCache(foldersCache, connId, refresh, async () => {
    const r = await sfetch<{ folders?: Folder[] }>(`${base}/api/folders?connection_id=${encodeURIComponent(connId)}`);
    return r.folders || [];
  });
}
export async function driveCreateFolder(connId: string, name: string, parent = ''): Promise<Folder> {
  const base = sibling('drive');
  if (!base) throw new Error('אפליקציית הדרייב אינה נגישה מחוץ לקונסול');
  const r = await sfetch<{ folder: Folder }>(`${base}/api/folders?connection_id=${encodeURIComponent(connId)}`, {
    method: 'POST', body: JSON.stringify({ name, parent }),
  });
  foldersCache.delete(connId);
  return r.folder;
}
export function mailLabels(connId: string, refresh = false): Promise<string[]> {
  const base = sibling('mailview');
  if (!base || !connId) return Promise.resolve([]);
  return withCache(labelsCache, connId, refresh, async () => {
    const r = await sfetch<{ labels?: unknown[] }>(`${base}/api/labels?connection_id=${encodeURIComponent(connId)}`);
    return (r.labels || []).map(String);
  });
}
/** organizer KEY → label NAME. The registry stores the organizer's KEYS (DOC_TO_SYNC…) and the
 *  engine resolves them through the same store the label engine runs on; the mailbox's own list
 *  holds NAMES. Comparing a key against names read every pipe's labels as "not in the list"
 *  (measured on the laptop console, 2026-09-02) — this map is the missing hop. One read per
 *  session; a key the store does not know renders as itself (the engine uses it literally too). */
let labelMapCache: Promise<Map<string, string>> | null = null;
export function organizerLabelMap(refresh = false): Promise<Map<string, string>> {
  const base = sibling('mailview');
  if (!base) return Promise.resolve(new Map());
  if (!refresh && labelMapCache) return labelMapCache;
  const p = sfetch<{ gmail?: { labels?: Record<string, { name?: string } | null> } }>(`${base}/api/label-map`)
    .then((r) => new Map(Object.entries(r.gmail?.labels || {}).map(([k, v]) => [k, String((v && v.name) || k)])))
    .catch((e: unknown) => { labelMapCache = null; throw e; });
  labelMapCache = p;
  return p;
}
export async function mailCreateLabel(connId: string, name: string): Promise<void> {
  const base = sibling('mailview');
  if (!base) throw new Error('אפליקציית המייל אינה נגישה מחוץ לקונסול');
  await sfetch(`${base}/api/labels?connection_id=${encodeURIComponent(connId)}`, {
    method: 'POST', body: JSON.stringify({ name, connection_id: connId }),
  });
  labelsCache.delete(connId);
}

/** a folder's readable path — the registry stores ids, the operator reads names */
export function folderPath(byId: Map<string, Folder>, id: string): string {
  const parts: string[] = [];
  let cur = byId.get(id);
  let guard = 0;
  while (cur && guard++ < 12) {
    parts.unshift(cur.name);
    cur = cur.parent ? byId.get(cur.parent) : undefined;
  }
  return parts.join('/');
}

/** A location's own NAME and the ancestors it sits under, nearest ancestor FIRST.
 *
 *  Every screen that names a folder or a label shows this pair, never the joined path in one
 *  ellipsised block: CSS truncates the END, and the end of a path is the leaf — the only part that
 *  differs between two siblings. Rendering `.leaf` + `.crumb` (the crumb shrinking first) is what
 *  keeps "כרטסות ספקים - בבקשה להכניס לחודש" readable instead of "חשבוניות הכנסים/…".
 *  Nearest-first ordering matters too: the ellipsis then drops the far root and keeps the parent.
 *  One owner for the split — the sync cards and the sync editor both read it. */
export interface LocParts { leaf: string; crumb: string }

export function folderParts(byId: Map<string, Folder>, id: string): LocParts {
  const f = byId.get(id);
  if (!f) return { leaf: '', crumb: '' };
  const anc: string[] = [];
  let cur = f.parent ? byId.get(f.parent) : undefined;
  let guard = 0;
  while (cur && guard++ < 12) { anc.push(cur.name); cur = cur.parent ? byId.get(cur.parent) : undefined; }
  return { leaf: f.name, crumb: anc.join(' ‹ ') };
}

/** the same split for a name that carries its own hierarchy in the string (gmail labels: "a/b/c") */
export function pathParts(name: string): LocParts {
  const parts = String(name || '').split('/').filter(Boolean);
  if (!parts.length) return { leaf: String(name || ''), crumb: '' };
  return { leaf: parts[parts.length - 1], crumb: parts.slice(0, -1).reverse().join(' ‹ ') };
}

/* ── health ──────────────────────────────────────────────────────────────────────────────────── */
export type ProbeState = 'ok' | 'bad' | 'unknown';
export interface Probe { state: ProbeState; reason: string; at: number }

/** Verify ONE connection without selecting it — the same probe each service's /readyz runs, so the
 *  dot on the card and what n8n trusts cannot disagree. Drive answers on its own mount; mail has no
 *  per-connection probe on the mailview mount, so it is asked through the console's service proxy
 *  (`/api/svc/mail/connections/<id>/probe`), falling back to the service's `/readyz` when that
 *  proxy is absent — which answers only for the ACTIVE mailbox, and says so. */
export function probeConnection(kind: ConnKind, id: string, refresh = false): Promise<Probe> {
  const key = `${kind}:${id}`;
  const hit = probeCache.get(key);
  if (!refresh && hit && Date.now() - hit.at < PROBE_TTL_MS) return hit.p;
  const p = (async (): Promise<Probe> => {
    const root = consoleRoot();
    if (root === null || !id) return { state: 'unknown', reason: SIBLINGS_NOTE, at: Date.now() };
    try {
      if (kind === 'drive') {
        const r = await sfetch<{ ok?: boolean; reason?: string }>(`${root}/a/drive/connections/${encodeURIComponent(id)}/probe`);
        return { state: r.ok ? 'ok' : 'bad', reason: r.reason || '', at: Date.now() };
      }
      try {
        const r = await sfetch<{ ok?: boolean; reason?: string; error?: string }>(
          `${root}/api/svc/mail/connections/${encodeURIComponent(id)}/probe`,
        );
        return { state: r.ok ? 'ok' : 'bad', reason: r.reason || r.error || '', at: Date.now() };
      } catch (e) {
        // no per-connection probe on this console — the readiness of the ACTIVE mailbox is the
        // only thing left to read, and it is only an answer when it names this connection
        const rz = await fetch(`${root}/api/svc/mail/readyz`, { credentials: 'same-origin' });
        const body = (await rz.json().catch(() => ({}))) as { ready?: boolean; reason?: string; connection_id?: string };
        if (body.connection_id && body.connection_id !== id) {
          return { state: 'unknown', reason: 'המייל בודק רק את החיבור הפעיל שלו; חיבור זה לא נבדק', at: Date.now() };
        }
        if (typeof body.ready === 'boolean') {
          return { state: body.ready ? 'ok' : 'bad', reason: body.reason || '', at: Date.now() };
        }
        throw e;
      }
    } catch (e: unknown) {
      return { state: 'unknown', reason: e instanceof Error ? e.message : String(e), at: Date.now() };
    }
  })();
  probeCache.set(key, { at: Date.now(), p });
  return p;
}

/* ── what sits at the source right now (for the reconcile) ───────────────────────────────────── */
interface RawFile { id: string; name?: string; created?: string; modified?: string; createdTime?: string; modifiedTime?: string; size?: number | string }
export async function driveFiles(connId: string, folderId: string): Promise<SourceFile[]> {
  const base = sibling('drive');
  if (!base) throw new Error(SIBLINGS_NOTE);
  const q = new URLSearchParams({ connection_id: connId, folder: folderId });
  const r = await sfetch<{ files?: RawFile[] }>(`${base}/api/files?${q.toString()}`);
  return (r.files || []).map((f) => ({
    id: String(f.id),
    name: String(f.name ?? f.id),
    created: f.created ?? f.createdTime ?? null,
    modified: f.modified ?? f.modifiedTime ?? null,
    size: f.size == null ? null : Number(f.size),
  }));
}
interface RawMessage { id: string; subject?: string; from?: string; date?: string }
export async function mailMessages(connId: string, label: string, limit: number): Promise<SourceMessage[]> {
  const base = sibling('mailview');
  if (!base) throw new Error(SIBLINGS_NOTE);
  const q = new URLSearchParams({ connection_id: connId, label, limit: String(limit), test: '1' });
  const r = await sfetch<{ messages?: RawMessage[] }>(`${base}/api/messages?${q.toString()}`);
  return (r.messages || []).map((m) => ({
    id: String(m.id), subject: String(m.subject ?? ''), from: String(m.from ?? ''), date: String(m.date ?? ''),
  }));
}
