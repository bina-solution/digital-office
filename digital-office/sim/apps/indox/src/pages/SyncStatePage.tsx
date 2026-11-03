import { useCallback, useEffect, useRef, useState } from 'react';
import SyncBoard from './SyncBoard';
import { ask } from '../ask';
import { columnOf, useColumns, wordOf } from '../words';
import { IC, Ic, XIcon } from '../icons';
import {
  api,
  ConnLocation,
  LEGAL_MOVES,
  MOVE_LABEL,
  SyncConnection,
  SyncItem,
  SyncItemState,
  SyncRegistryEntry,
  SyncStatus,
} from '../api';
import '../sync.css';

/**
 * INDOX · סנכרון — the ONE sync surface.
 *
 * This page used to be a read-only counter board, with the pipes it was counting described in a
 * different tab (הגדרות), also read-only. Both halves are merged here: each pipe is one card
 * carrying its config AND its live state, and everything you might want to do to it — run, pause,
 * edit, retry stuck items — is on that card. See sim/INDOX-SYNC.md for the reasoning.
 */

const POLL_MS = 5000;

type StateKey = SyncItemState;
const STATE_LABELS: Record<StateKey, string> = {
  to_sync: 'לסנכרון',
  in_progress: 'בתהליך',
  synced: 'סונכרן',
  failed: 'נכשל',
};
const STATE_ORDER: StateKey[] = ['to_sync', 'in_progress', 'synced', 'failed'];
const STATE_CLASS: Record<StateKey, string> = {
  to_sync: 'to_sync',
  in_progress: 'in_progress',
  synced: 'synced',
  failed: 'failed',
};

const zero = { to_sync: 0, in_progress: 0, synced: 0, failed: 0 };
const countsOf = (e: SyncRegistryEntry) => e.counts ?? zero;
/** a drive pipe's pair, in BOTH vocabularies the live registry carries: the editor's from/to/failed_to and the
 *  engine's to_sync/synced/failed (the live service fills each from the other — `_normalise_entry`) */
type Pair = { from?: string; to_sync?: string; to?: string; synced?: string; failed?: string; failed_to?: string; [k: string]: unknown };
/** the live page's (its SyncEditor): the cadence a source with no schedule of its own is run at */
const SCHEDULER_MIN = 15;
const SRC_LABEL: Record<string, string> = { gmail: 'Gmail', drive: 'Drive' };
// how many items a press will show — said in a hint, where nobody was looking: «הצג 1 פריטים»
const itemsHe = (n: number) => (n === 1 ? 'פריט אחד' : `${n} פריטים`);

function ago(iso?: string | null): string {
  if (!iso) return '—';
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return 'עכשיו';
  if (m < 60) return `לפני ${m} דק׳`;
  if (m < 1440) return `לפני ${Math.round(m / 60)} שע׳`;
  const d = Math.round(m / 1440);               // (one is said as one: «לפני 1 ימים» is «לפני יום»)
  return d === 1 ? 'לפני יום' : `לפני ${d} ימים`;
}
function fmtDateTime(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? String(iso)
    : d.toLocaleString('he-IL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

/** The 4-state bar. Every segment is a button: status → the items behind it, in one click. */
function StateBar({
  counts,
  onPick,
}: {
  counts: Record<StateKey, number>;
  onPick?: (s: StateKey) => void;
}) {
  const total = STATE_ORDER.reduce((a, k) => a + counts[k], 0);
  // A purely proportional bar hides exactly the states you care about: 2 waiting and 1 failed next to
  // 184 synced round to invisible slivers, so a pipe with a problem looks identical to a healthy one.
  // Give every non-zero state a visible floor, then renormalise so the bar still sums to 100%.
  const MIN_PCT = 6;
  const raw = STATE_ORDER.map((k) => (counts[k] > 0 ? Math.max(MIN_PCT, (counts[k] / Math.max(1, total)) * 100) : 0));
  const sum = raw.reduce((a, x) => a + x, 0) || 1;
  const width = STATE_ORDER.reduce(
    (acc, k, i) => ({ ...acc, [k]: (raw[i] / sum) * 100 }),
    {} as Record<StateKey, number>,
  );
  return (
    <>
      <div className="statebar" role="img" aria-label="מצב סנכרון">
        {STATE_ORDER.map((k) =>
          counts[k] > 0 ? (
            <div
              key={k}
              className={`seg ${STATE_CLASS[k]}`}
              style={{ width: `${width[k]}%` }}
              title={`${STATE_LABELS[k]}: ${counts[k]}`}
            />
          ) : null,
        )}
      </div>
      <div className="statelegend">
        {STATE_ORDER.map((k) => (
          <button
            key={k}
            type="button"
            className="li li-btn"
            onClick={() => onPick?.(k)}
            disabled={!onPick || counts[k] === 0}
            title={onPick && counts[k] ? `הצג ${itemsHe(counts[k])}` : undefined}
          >
            <span className={`sw ${STATE_CLASS[k]}`} />
            {STATE_LABELS[k]}
            <b className="num">{counts[k]}</b>
          </button>
        ))}
      </div>
    </>
  );
}

/* ── what a source's card says of it: the LIVE page's facts (apps/indox/app/webapp/src/pages/SyncStatePage.tsx
   `Fact` / `PipeFacts`, styled by ../sync.css) ────────────────────────────────────────────────────────────────
   The card said all of this in two lines of small grey text — «תוויות אינדוקס - חשבוניות - לטיפול → … · נכשל: …»
   and «כל 5 דק׳ · take 40 · הרצה אחרונה —»: the design the owner rejected on 2026-09-02, and the live page
   left behind. The code below is the live page's, and a change to it is made there first. Where this registry
   differs, only the reading differs: the live registry stores a folder's id and a label's organizer key, read
   into names from the sibling apps; this one stores the NAME itself, its hierarchy in the string. */

/** A location's own NAME and the ancestors it sits under, nearest ancestor FIRST — the live app's split
 *  (`LocParts` / `pathParts()`, its siblings.ts) as it is there: CSS cuts the END of a text, and the end of a
 *  path is the leaf, the one part that tells two siblings apart; so the leaf is a line of its own. */
interface LocParts { leaf: string; crumb: string }
function pathParts(name: string): LocParts {
  const parts = String(name || '').split('/').filter(Boolean);
  if (!parts.length) return { leaf: String(name || ''), crumb: '' };
  return { leaf: parts[parts.length - 1], crumb: parts.slice(0, -1).reverse().join(' ‹ ') };
}

/** one fact cell: the key over the value; the value is the NAME from the sibling list, the id one
 *  hover away; pinned (amber) when the stored id is not in the list; "ללא" when nothing is set */
function Fact({ k, icon, id, parts, known, none }: {
  k: string; icon?: string; id: string; parts: LocParts | null; known: boolean | null; none?: string;
}) {
  let cls = 'v';
  let text: string | null = null;
  let title = id;
  if (!id) { cls += ' none'; text = none || 'ללא'; title = ''; }
  else if (known === null) { cls += ' wait'; text = 'קורא…'; }
  else if (!known) { cls += ' pin'; text = 'לא נמצא ברשימה'; title = `המזהה השמור אינו ברשימת החיבור\n${id}`; }
  else if (!parts || !parts.leaf) { text = id; }
  /* the location's own NAME on its own line, its ancestors under it. The value used to be the whole
     joined path in ONE clamped block, so the clamp cut the leaf — the only part that tells two
     siblings apart. */
  const full = parts && parts.leaf ? [parts.leaf, parts.crumb].filter(Boolean).join('\n') : '';
  return (
    <div className="f">
      <div className="k">{icon && <Ic p={icon} />}{k}</div>
      {text !== null ? (
        <div className={cls} title={title || undefined}>{text}</div>
      ) : (
        <div className={cls} title={`${full}\n${id}`}>
          <span className="nm">{(parts as LocParts).leaf}</span>
          {(parts as LocParts).crumb && <span className="in">{(parts as LocParts).crumb}</span>}
        </div>
      )}
    </div>
  );
}

/** each connection's own folders or labels — the sibling reads the live card makes (`useFolderMap`, `useLabelSet`),
 *  read once per connection by the page; a connection not read yet is absent */
type LocLists = Record<string, Set<string>>;

/** where the pipe reads from and where it files to — a hairline grid of facts, one line each: a mailbox's four
 *  2×2, a drive's three in one row, the live page's keys and empty words. A stored location is KNOWN when its
 *  connection's own list holds it — «קורא…» while that list is read, and pinned, «לא נמצא ברשימה», when the list does
 *  not hold it or there is no connection to look in (a mailbox's destination with no drive): the live card's rule. */
function PipeFacts({ entry, lists }: { entry: SyncRegistryEntry; lists: LocLists }) {
  const at = (v: unknown) => String(v || '');
  const loc = (name: string) => (name ? pathParts(name) : null);
  const known = (connId: unknown, name: string): boolean | null => {
    if (!connId) return false;
    const s = lists[String(connId)];
    return s ? s.has(name) : null;
  };
  if (entry.source === 'gmail') {
    const l = entry.labels || {};
    const dest = at(entry.dest_folder);
    const box = entry.connection, drive = entry.drive_connection_id;
    return (
      <div className="pipe-facts c4" aria-label="תוויות ויעד">
        <Fact k="תווית מקור" icon={IC.tag} id={at(l.to_sync)} parts={loc(at(l.to_sync))} known={known(box, at(l.to_sync))} />
        <Fact k="אחרי סנכרון" id={at(l.synced)} parts={loc(at(l.synced))} known={known(box, at(l.synced))} none="ללא תווית" />
        <Fact k="כשלים" id={at(l.failed)} parts={loc(at(l.failed))} known={known(box, at(l.failed))} none="ללא תווית" />
        <Fact k="הקבצים נשמרים אל" icon={IC.folder} id={dest} parts={loc(dest)} known={known(drive, dest)} none="לא נבחרה תיקייה" />
      </div>
    );
  }
  const pairs = ((entry.pairs || []) as Pair[]).filter((x) => x && typeof x === 'object');
  const p = pairs[0] || {};
  const src = at(p.to_sync || p.from);
  const dst = at(p.synced || p.to);
  const failed = at(p.failed || p.failed_to);
  // (one is said as one: the live page's «(+1 זוגות)» is «(+זוג נוסף)» here)
  const more = pairs.length > 2 ? ` (+${pairs.length - 1} זוגות)` : pairs.length === 2 ? ' (+זוג נוסף)' : '';
  const box = entry.connection;
  return (
    <div className="pipe-facts c3" aria-label="תיקיות">
      <Fact k={`תיקיית מקור${more}`} icon={IC.folder} id={src} parts={loc(src)} known={known(box, src)} />
      <Fact k="אחרי סנכרון" id={dst} parts={loc(dst)} known={known(box, dst)} none="נשאר במקומו" />
      <Fact k="כשלים" id={failed} parts={loc(failed)} known={known(box, failed)} none="נשאר במקומו" />
    </div>
  );
}

/** how often it runs and when it last ran — the live page's activity line (`.pipe-activity`): at most four facts
 *  on one line, each a word and its value, the cadence falling back as the live page's does. Where its words are
 *  not the live page's, on purpose: the batch is «עד 40 בכל סבב» (DGO-525's acceptance; the live «40 לסבב»), a
 *  one-minute cadence is «כל דקה» (this editor allows one; the live one's least is 15), and a source that never ran
 *  says «טרם רץ», not «—» (platform-ui-ux: a dash is no Hebrew empty state; the live tooltip's own words). */
function PipeActivity({ entry }: { entry: SyncRegistryEntry }) {
  const cadence = (entry.cadence_min as number | undefined) ?? entry.batch?.schedule_min ?? SCHEDULER_MIN;
  const take = entry.batch?.take;
  const chunk = entry.batch?.chunk;
  const last = (entry.last_run as string | null | undefined) || null;
  const every = cadence === 1 ? 'כל דקה' : `כל ${cadence} דק׳`;
  return (
    <div className="pipe-activity">
      <span className="it" title={`הסבב רץ ${every}${take != null ? ` · עד ${take === 1 ? 'פריט אחד' : `${take} פריטים`} לסבב` : ''}${chunk != null ? ` · בנגלות של ${chunk}` : ''}`}>
        <Ic p={IC.clock} /> כל {cadence === 1 ? <b>דקה</b> : <><b className="num">{cadence}</b> דק׳</>}
        {take != null && <> · עד {take === 1 ? <b>פריט אחד</b> : <b className="num">{take}</b>} בכל סבב</>}
      </span>
      <span className="it" title={last ? `הרצה אחרונה ${fmtDateTime(last)}` : 'המקור טרם רץ'}>
        <Ic p={IC.activity} /> הרצה אחרונה <b>{last ? ago(last) : 'טרם רץ'}</b>
      </span>
    </div>
  );
}

// ── items drawer ─────────────────────────────────────────────────────────────
// Where "move an item between states" lives. Only the legal targets for the state you opened are
// offered (api.ts LEGAL_MOVES) — the mock refuses the rest, so the UI never suggests an illegal move.
/* Escape closes any overlay. Every dismissible surface has to answer the key people press first —
   a drawer that only closes by clicking its ✕ is a trap the moment it covers the control you were
   reaching for (which is exactly how it hid the tab strip). */
function useEscape(onClose: () => void) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onClose]);
}

function ItemsDrawer({
  sync,
  state,
  onClose,
  onChanged,
}: {
  sync: string;
  state: StateKey;
  onClose: () => void;
  onChanged: () => void;
}) {
  const typeCol = columnOf(useColumns(), 'TYPE');
  const [items, setItems] = useState<SyncItem[]>([]);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api
      .listSyncItems({ sync, state })
      .then((r) => setItems(r.items))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [sync, state]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setSel(new Set()); }, [state]);
  useEscape(onClose);

  const targets = LEGAL_MOVES[state] || [];
  const allSelected = items.length > 0 && sel.size === items.length;

  async function move(to: SyncItemState) {
    if (!sel.size) return;
    setBusy(true);
    try {
      await api.moveSyncItems(sync, Array.from(sel), to);
      setSel(new Set());
      load();
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="drawer-ov">
      <div className="scrim" onClick={onClose} />
      <div className="drawer">
        <div className="drawer-h">
          <h3>
            {STATE_LABELS[state]} · <span className="mono">{sync}</span>
          </h3>
          <button onClick={onClose} className="icbtn" aria-label="סגירה" title="סגירה (Esc)"><XIcon /></button>
        </div>

        <div className="drawer-body">
          {loading && <div className="spin">טוען פריטים…</div>}
          {!loading && !items.length && (
            <div className="callout">אין פריטים במצב זה.</div>
          )}
          {!loading && items.length > 0 && (
            <>
              <label className="flex items-center gap-1 small muted" style={{ cursor: 'pointer', marginBottom: 8 }}>
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(e) =>
                    setSel(e.target.checked ? new Set(items.map((i) => i.id)) : new Set())
                  }
                  style={{ width: 'auto', cursor: 'pointer' }}
                />
                בחר הכל ({items.length})
              </label>
              <div className="space-y-3">
                {items.map((it) => (
                  <label key={it.id} className="card" style={{ display: 'flex', gap: 10, cursor: 'pointer', padding: 10 }}>
                    <input
                      type="checkbox"
                      checked={sel.has(it.id)}
                      onChange={(e) => {
                        const n = new Set(sel);
                        if (e.target.checked) n.add(it.id); else n.delete(it.id);
                        setSel(n);
                      }}
                      style={{ width: 'auto', cursor: 'pointer', marginTop: 3 }}
                    />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{it.title}</div>
                      <div className="muted small">
                        <span className="tag" title={it.kind}>{wordOf(typeCol, it.kind)}</span>{' '}
                        {it.size_kb} KB · {ago(it.updated_at)}
                      </div>
                      {it.error && (
                        <div className="small" style={{ color: 'var(--red)', marginTop: 3 }}>{it.error}</div>
                      )}
                    </div>
                  </label>
                ))}
              </div>
            </>
          )}
        </div>

        <div className="drawer-foot">
          {targets.length === 0 ? (
            <div className="muted small">אין פעולות זמינות ממצב זה.</div>
          ) : (
            <div className="flex items-center gap-3" style={{ flexWrap: 'wrap' }}>
              <span className="muted small">נבחרו {sel.size}</span>
              {targets.map((t) => (
                <button
                  key={t}
                  className="btn"
                  disabled={!sel.size || busy}
                  onClick={() => move(t)}
                >
                  {MOVE_LABEL[`${state}>${t}`] || `העבר ל${STATE_LABELS[t]}`}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── the editor ───────────────────────────────────────────────────────────────
// Connection FIRST, then browse that connection's real locations. You cannot list the folders/labels
// to choose from until you know which account you are choosing them in (INDOX-SYNC.md §6).
function PipeEditor({
  existing,
  onClose,
  onSaved,
}: {
  existing: SyncRegistryEntry | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  // a document's type is WORDED as the service says the TYPE column's values read (words.tsx): the list here
  // offered «INVOICE», «RECEIPT» … as the database holds them, and one type the pipeline does not have
  const typeCol = columnOf(useColumns(), 'TYPE');
  const [step, setStep] = useState(existing ? 2 : 1);
  const [conns, setConns] = useState<SyncConnection[]>([]);
  const [connId, setConnId] = useState<string>((existing?.connection as string) || '');
  const [locs, setLocs] = useState<ConnLocation[]>([]);
  const [kind, setKind] = useState<'labels' | 'folders'>(
    existing?.source === 'gmail' ? 'labels' : 'folders',
  );
  const [locLoading, setLocLoading] = useState(false);
  const [newPath, setNewPath] = useState('');

  /* THE ORIGINAL VALUES. A save is a DIFF against them — the live SyncEditor's rule (its :556-578, :736-757): only
     what was changed here travels, so what this editor has no field for stays as it is stored — a pair's folder for
     what failed and the pairs after the first, a batch's chunk and timeout, a mailbox's failed label. The save
     rebuilt the entry from the fields it knew instead, and every save — an unchanged one too — rewrote those. */
  const isGmail0 = existing?.source === 'gmail';
  const pairs0 = ((existing?.pairs || []) as Pair[]).filter((x) => x && typeof x === 'object');
  const p0: Pair = pairs0[0] || {};
  const labels0 = (existing?.labels || {}) as Record<string, string>;
  const batch0 = existing?.batch || {};
  const orig = {
    connId: String(existing?.connection || ''),
    src: String((isGmail0 ? labels0.to_sync : p0.to_sync || p0.from) || ''),
    dst: String((isGmail0 ? labels0.synced : p0.synced || p0.to) || ''),
    name: existing?.name || '',
    typeHint: String(existing?.type_hint || ''),
    schedule: batch0.schedule_min ?? 10,
    take: batch0.take ?? 20,
  };
  const [name, setName] = useState(orig.name);
  const [typeHint, setTypeHint] = useState<string>(orig.typeHint);
  const [schedule, setSchedule] = useState(orig.schedule);
  const [take, setTake] = useState(orig.take);
  const [src, setSrc] = useState(orig.src);
  const [dst, setDst] = useState(orig.dst);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    // a source keeps its kind: an existing one is offered the connections of its own (the live editor's choice of
    // kind is for a new source only) — a mailbox's source moved to a drive would carry labels and no pairs
    api.listConnections()
      .then((r) => setConns((r.connections || []).filter((c) => !existing || c.source === existing.source)))
      .catch(() => setConns([]));
  }, [existing]);
  useEscape(onClose);

  const loadLocs = useCallback((id: string) => {
    if (!id) return;
    setLocLoading(true);
    api
      .listLocations(id)
      .then((r) => { setLocs(r.items || []); setKind(r.kind); })
      .catch(() => setLocs([]))
      .finally(() => setLocLoading(false));
  }, []);

  useEffect(() => { if (connId) loadLocs(connId); }, [connId, loadLocs]);

  const conn = conns.find((c) => c.id === connId);
  const isGmail = kind === 'labels';

  async function createLoc() {
    const p = newPath.trim();
    if (!p || !connId) return;
    const r = await api.createLocation(connId, p);
    setNewPath('');
    loadLocs(connId);
    if (!src) setSrc(r.item.path); else setDst(r.item.path);
  }

  async function save() {
    setErr(null);
    if (!src) { setErr(isGmail ? 'בחרו תווית מקור' : 'בחרו תיקיית מקור'); return; }
    const nm = (name || `${conn?.source || 'drive'}-${(src || 'sync').replace(/[^\w]+/g, '-').toLowerCase()}`).trim();
    const payload: Record<string, unknown> = {};
    // a new connection is another account: what the source kept for failures was the OLD account's — dropped, as the
    // live editor clears it when the connection changes (SyncEditor.tsx:907) and its save deletes both names (:746)
    const moved = !!existing && connId !== orig.connId;
    if (!existing) {
      payload.name = nm;
      payload.source = conn?.source || (isGmail ? 'gmail' : 'drive');
      payload.connection = connId;
    } else {
      if (nm !== orig.name) payload.name = nm;
      if (moved) payload.connection = connId;
    }
    if (!existing ? Boolean(typeHint) : typeHint !== orig.typeHint) {
      payload.type_hint = typeHint || null;
      payload.fallback_type = typeHint || null;
    }
    const takeN = Number(take) || 20;
    const everyN = Number(schedule) || 10;
    if (!existing) payload.batch = { take: takeN, chunk: 5, timeout_min: 10, schedule_min: everyN };
    else if (takeN !== orig.take || everyN !== orig.schedule) payload.batch = { ...batch0, take: takeN, schedule_min: everyN };
    if (isGmail) {
      const lab: Record<string, string> = { ...labels0 };
      let touched = false;
      if (!existing || src !== orig.src) { lab.to_sync = src; payload.claim_label = `${src}/בעיבוד`; touched = true; }
      if (!existing || dst !== orig.dst) { lab.synced = dst || `${src}/סונכרן`; touched = true; }
      if (!existing) lab.failed = `${src}/נכשל`;
      else if (moved && 'failed' in lab) { delete lab.failed; touched = true; }
      if (touched) payload.labels = lab;
    } else {
      // the pair is the stored one with what changed set in BOTH its vocabularies (the live editor's :736-749): a
      // source set in `from` alone left the engine's `to_sync` naming the old folder, and the card — which reads
      // `to_sync` first, as the live card does — said the edit had not happened
      const pair: Pair = { ...p0 };
      let touched = false;
      const to = dst || `${src}/ארכיון`;
      if (!existing || src !== orig.src) { pair.from = src; pair.to_sync = src; touched = true; }
      if (!existing || dst !== orig.dst) { pair.to = to; pair.synced = to; payload.dest_folder = to; touched = true; }
      if (moved && (pair.failed || pair.failed_to)) { delete pair.failed; delete pair.failed_to; touched = true; }
      if (touched) payload.pairs = [pair, ...pairs0.slice(1)];
    }
    // (the live editor's own sentence: an unchanged save writes nothing)
    if (existing && !Object.keys(payload).length) { setErr('לא שונה דבר — אין מה לשמור.'); return; }
    setBusy(true);
    try {
      if (existing) await api.patchSyncEntry(existing.name, payload);
      else await api.createSyncEntry(payload);
      onSaved();
      onClose();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="drawer-ov">
      <div className="scrim" onClick={onClose} />
      <div className="drawer">
        <div className="drawer-h">
          <h3>{existing ? `עריכת מקור · ${existing.name}` : 'מקור סנכרון חדש'}</h3>
          <button onClick={onClose} className="icbtn" aria-label="סגירה" title="סגירה (Esc)"><XIcon /></button>
        </div>

        <div className="drawer-body">
          <div className="muted small" style={{ marginBottom: 12 }}>
            {['1 חיבור', '2 מה לסנכרן', '3 סוג ותזמון'].map((s, i) => (
              <span key={s} style={{ fontWeight: step === i + 1 ? 700 : 400, color: step === i + 1 ? 'var(--accent-d)' : undefined }}>
                {i > 0 ? ' · ' : ''}{s}
              </span>
            ))}
          </div>

          {step === 1 && (
            <>
              <p className="small muted" style={{ marginTop: 0 }}>
                מאיזה חיבור למשוך? הבחירה קובעת אם נבחר <b>תוויות</b> (מייל) או <b>תיקיות</b> (דרייב).
              </p>
              <div className="space-y-3">
                {conns.map((c) => (
                  <label
                    key={c.id}
                    className="card"
                    style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', padding: 10,
                             borderColor: connId === c.id ? 'var(--accent)' : undefined }}
                  >
                    <input
                      type="radio"
                      name="conn"
                      checked={connId === c.id}
                      onChange={() => { setConnId(c.id); setSrc(''); setDst(''); }}
                      style={{ width: 'auto', cursor: 'pointer' }}
                    />
                    <span
                      style={{ width: 26, height: 26, borderRadius: '50%', background: c.color || 'var(--olive)',
                               color: 'var(--olive-ink)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                               fontWeight: 700, fontSize: 12, flex: 'none' }}
                    >
                      {(c.label || '?')[0]}
                    </span>
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <b style={{ display: 'block', fontSize: 13 }}>{c.label}</b>
                      <span className="muted small">{c.identity}</span>
                    </span>
                    <span className="tag">{SRC_LABEL[c.source] || c.source}</span>
                  </label>
                ))}
                {!conns.length && <div className="callout">אין חיבורים זמינים.</div>}
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <p className="small muted" style={{ marginTop: 0 }}>
                {isGmail
                  ? 'בחרו את התווית שממנה נמשכים מסמכים, ולאן לסמן אחרי סנכרון.'
                  : 'בחרו תיקיית מקור ותיקיית ארכיון. אפשר גם ליצור תיקייה חדשה כאן.'}
                {conn && <> חיבור: <b>{conn.label}</b></>}
              </p>

              {locLoading && <div className="spin">טוען…</div>}

              {!locLoading && (
                <>
                  <div className="field">
                    <label>{isGmail ? 'תווית מקור (לסנכרון)' : 'תיקיית מקור'}</label>
                    <select value={src} onChange={(e) => setSrc(e.target.value)}>
                      <option value="">— בחרו —</option>
                      {locs.map((l) => (
                        <option key={l.id} value={l.path}>{l.path} ({l.count})</option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label>{isGmail ? 'תווית אחרי סנכרון' : 'תיקיית ארכיון'}</label>
                    <select value={dst} onChange={(e) => setDst(e.target.value)}>
                      <option value="">— ברירת מחדל —</option>
                      {locs.map((l) => (
                        <option key={l.id} value={l.path}>{l.path} ({l.count})</option>
                      ))}
                    </select>
                  </div>

                  <div className="field">
                    <label>{isGmail ? 'יצירת תווית חדשה' : 'יצירת תיקייה חדשה'}</label>
                    <div className="flex items-center gap-3">
                      <input
                        value={newPath}
                        onChange={(e) => setNewPath(e.target.value)}
                        placeholder={isGmail ? 'INDOX/חדש' : 'נכנס/חדש'}
                        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); createLoc(); } }}
                      />
                      <button className="btn" type="button" onClick={createLoc} disabled={!newPath.trim()}>
                        צור
                      </button>
                    </div>
                  </div>
                </>
              )}
            </>
          )}

          {step === 3 && (
            <>
              <div className="field">
                <label>שם המקור</label>
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="נוצר אוטומטית" />
              </div>
              {/* Optional on purpose. A mixed folder/label has no single answer, and forcing one would
                  mislabel everything in it. Set it only when the LOCATION itself implies the type —
                  e.g. נכנס/קבלות is always receipts — in which case it also becomes the one-click fix
                  for documents the classifier could not type. */}
              <div className="field">
                <label>סוג ברירת מחדל (לא חובה)</label>
                <select value={typeHint} onChange={(e) => setTypeHint(e.target.value)}>
                  <option value="">ללא — הסוג ייקבע לפי זיהוי המסמך</option>
                  {['INVOICE', 'RECEIPT', 'ORDER', 'SHIPMENT', 'BALANCE_SHEET'].map((t) => (
                    <option key={t} value={t}>{wordOf(typeCol, t)}</option>
                  ))}
                </select>
                <div className="muted small" style={{ marginTop: 4 }}>
                  {typeHint
                    ? `מסמך שלא יזוהה מהמקור הזה יסווג כ«${wordOf(typeCol, typeHint)}» — וניתן יהיה לתקן כך גם כשלים בלחיצה אחת.`
                    : 'ללא ברירת מחדל, מסמך שלא יזוהה ייכשל עם "סוג המסמך לא זוהה" ויידרש טיפול ידני.'}
                </div>
              </div>
              <div className="field">
                <label>כל כמה דקות</label>
                <input type="number" min={1} value={schedule} onChange={(e) => setSchedule(Number(e.target.value))} />
              </div>
              <div className="field">
                <label>כמה למשוך בכל הרצה (take)</label>
                <input type="number" min={1} value={take} onChange={(e) => setTake(Number(e.target.value))} />
              </div>
            </>
          )}

          {err && <div className="callout bad" style={{ marginTop: 10 }}>{err}</div>}
        </div>

        <div className="drawer-foot">
          <div className="flex items-center gap-3">
            {step > 1 && <button className="btn" onClick={() => setStep(step - 1)}>חזרה</button>}
            {step < 3 && (
              <button className="btn" disabled={step === 1 && !connId} onClick={() => setStep(step + 1)}>
                המשך
              </button>
            )}
            {step === 3 && (
              <button className="btn" disabled={busy} onClick={save}>
                {busy ? 'שומר…' : existing ? 'שמירה' : 'יצירת מקור'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── one pipe = one card: config AND live state AND actions ───────────────────
function PipeCard({
  entry,
  onRun,
  onToggle,
  onEdit,
  onDelete,
  onPickState,
  onPickFailure,
  running,
  lists,
}: {
  entry: SyncRegistryEntry;
  onRun: () => void;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onPickState: (s: StateKey) => void;
  onPickFailure: (code: string) => void;
  running: boolean;
  lists: LocLists;
}) {
  const c = countsOf(entry);
  const enabled = entry.enabled !== false;
  const typeCol = columnOf(useColumns(), 'TYPE');
  return (
    <div className="card" style={{ opacity: enabled ? 1 : 0.62 }}>
      <div className="sync-meta">
        <span className="name">{entry.name}</span>
        {entry.source && <span className="tag">{SRC_LABEL[entry.source] || entry.source}</span>}
        {entry.type_hint ? <span className="tag" title={entry.type_hint}>{wordOf(typeCol, entry.type_hint)}</span>
                          : <span className="tag" style={{ color: 'var(--muted)' }}>ללא סוג קבוע</span>}
        {!enabled && <span className="tag">מושהה</span>}
        {/* (one is said as one: «1 תקועים» stood on the tag) */}
        {!!entry.stuck && <span className="tag" style={{ color: 'var(--amber)' }}>{entry.stuck === 1 ? 'תקוע אחד' : `${entry.stuck} תקועים`}</span>}
      </div>
      {/* A pipe is only as healthy as the account it pulls from — a dead connection is the single most
          common reason a whole pipe silently stops, so it is stated on the card, not buried. */}
      <div className="muted small" style={{ marginBottom: 6 }}>
        {entry.connection_label || '—'}
        {entry.connection_identity ? ` · ${entry.connection_identity}` : ''}
        {entry.connection_status && entry.connection_status !== 'ok' && (
          <span style={{ color: entry.connection_status === 'error' ? 'var(--red)' : 'var(--amber)', marginInlineStart: 6 }}>
            <span className={`dot ${entry.connection_status === 'error' ? 'bad' : 'warn'}`} style={{ width: 7, height: 7, marginInlineEnd: 5 }} />
            {entry.connection_reason || 'החיבור דורש טיפול'}
          </span>
        )}
      </div>

      <PipeFacts entry={entry} lists={lists} />

      <StateBar counts={c} onPick={onPickState} />

      {!!(entry.failures || []).length && (
        <div className="flex items-center gap-3" style={{ marginTop: 8, flexWrap: 'wrap' }}>
          {(entry.failures || []).map((f) => (
            <button
              key={f.code}
              className="link small"
              onClick={() => onPickFailure(f.code)}
              title={`הצג ${itemsHe(f.n)}: ${f.he}`}
              style={{ color: f.group === 'terminal' ? 'var(--muted)' : 'var(--red)' }}
            >
              {f.he} · {f.n}
            </button>
          ))}
        </div>
      )}

      <PipeActivity entry={entry} />

      <div className="flex items-center gap-3" style={{ marginTop: 10, flexWrap: 'wrap' }}>
        <button className="btn" onClick={onRun} disabled={running || !enabled}>
          {running ? 'מריץ…' : <><Ic p={IC.play} /> הרץ עכשיו</>}
        </button>
        <button className="link" onClick={onEdit}>עריכה</button>
        <button className="link" onClick={onToggle}>{enabled ? 'השהה' : 'הפעל'}</button>
        <button className="link danger" onClick={onDelete}>מחיקה</button>
      </div>
    </div>
  );
}

function BigStat({ k, v, cls }: { k: string; v: number | string; cls?: string }) {
  return (
    <div className={`bigstat${cls ? ` ${cls}` : ''}`}>
      <div className="k">{k}</div>
      {/* (a count is written as every other screen of the app writes one: «3097» stood here, «13,811» a tab away) */}
      <div className="v num">{typeof v === 'number' ? v.toLocaleString('he-IL') : v}</div>
    </div>
  );
}

export default function SyncStatePage() {
  const [registry, setRegistry] = useState<SyncRegistryEntry[]>([]);
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [paused, setPaused] = useState(false);
  const [runningAll, setRunningAll] = useState(false);
  const [runningOne, setRunningOne] = useState<string | null>(null);
  const [editing, setEditing] = useState<SyncRegistryEntry | null>(null);
  const [creating, setCreating] = useState(false);
  const [drawer, setDrawer] = useState<{ sync: string; state: StateKey } | null>(null);
  const [view, setView] = useState<'pipes' | 'board'>('pipes');
  const [boardSeed, setBoardSeed] = useState(0);
  // the list of folders or labels of every connection a source names (its own, and a mailbox's drive for the files),
  // read ONCE each — what the editor offers, and what a card checks a stored location against — and read again
  // after a save (the editor can make a folder or a label). A list that cannot be read is an empty one: everything
  // in it pins, as the live card's does.
  const [lists, setLists] = useState<LocLists>({});
  const [listsSeed, setListsSeed] = useState(0);
  const named = Array.from(new Set(registry.flatMap((e) => [e.connection, e.drive_connection_id])
    .filter(Boolean).map(String))).sort().join('|');
  useEffect(() => {
    let dead = false;
    Promise.all((named ? named.split('|') : []).map((id) => api.listLocations(id)
      .then((r): [string, Set<string>] => [id, new Set((r.items || []).map((x) => x.path))])
      .catch((): [string, Set<string>] => [id, new Set<string>()])))
      .then((got) => { if (!dead) setLists(Object.fromEntries(got)); });
    return () => { dead = true; };
  }, [named, listsSeed]);
  const inFlight = useRef(false);

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const [reg, st] = await Promise.all([api.getSyncRegistry(), api.getSyncStatus()]);
      setRegistry(reg.registry || []);
      setStatus(st);
      setErr(st.reachable === false ? st.error || 'מקור הנתונים אינו זמין' : null);
      setUpdated(new Date());
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  // The visibility guard is on the TICK, not inside `load` — guarding `load` itself returns before
  // `finally { setLoading(false) }`, stranding the page on its spinner with a healthy API behind it.
  useEffect(() => {
    if (paused) return;
    const id = setInterval(() => {
      if (!document.hidden) load();
    }, POLL_MS);
    const onVisible = () => {
      if (!document.hidden) load();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [load, paused]);
  // the top-bar instance switcher fires this — the whole board belongs to the active instance
  useEffect(() => {
    const h = () => load();
    window.addEventListener('indox:instance-changed', h);
    return () => window.removeEventListener('indox:instance-changed', h);
  }, [load]);

  const totals = STATE_ORDER.reduce(
    (a, k) => ({ ...a, [k]: registry.reduce((s, e) => s + countsOf(e)[k], 0) }),
    { ...zero },
  ) as Record<StateKey, number>;

  const stuckTotal = registry.reduce((a, e) => a + (e.stuck || 0), 0);
  const brokenConns = registry.filter((e) => e.connection_status === 'error');

  async function runAll() {
    setRunningAll(true);
    try { await api.runAllSyncs(); await load(); } finally { setRunningAll(false); }
  }
  async function runOne(name: string) {
    setRunningOne(name);
    try { await api.runSyncEntry(name); await load(); } finally { setRunningOne(null); }
  }
  async function toggle(e: SyncRegistryEntry) {
    await api.patchSyncEntry(e.name, { enabled: e.enabled === false });
    load();
  }
  async function remove(e: SyncRegistryEntry) {
    const c = countsOf(e);
    if (!(await ask({
      title: 'למחוק את מקור הסנכרון?', body: 'הפריטים שלו יוסרו מהתצוגה.', ok: 'מחיקה', danger: true,
      facts: [['מקור', e.name], ...STATE_ORDER.map((s): [string, string] => [STATE_LABELS[s], String(c[s])])],
    }))) return;
    await api.deleteSyncEntry(e.name);
    load();
  }

  if (loading && !registry.length) return <div className="spin">טוען סנכרון…</div>;

  return (
    <div>
      <div className="app-header">
        <div>
          <h1>סנכרון</h1>
          <div className="sub">
            מקורות הסנכרון של המופע הפעיל — הגדרה, מצב חי והרצה, במקום אחד.
          </div>
        </div>
        <div className="actions">
          {updated && <span className="muted small">עודכן {updated.toLocaleTimeString('he-IL')}</span>}
          <button className="link" onClick={() => setPaused((p) => !p)}>
            {paused ? 'המשך רענון' : 'השהה רענון'}
          </button>
          {!paused && <span className="live"><span className="beat" />חי</span>}
          <button className="btn" onClick={runAll} disabled={runningAll || !registry.length}>
            {runningAll ? 'מריץ…' : <><Ic p={IC.play} /> הרץ הכל</>}
          </button>
        </div>
      </div>

      {err && <div className="callout warn"><b>שגיאת רענון.</b> {err}</div>}

      {/* The two things that silently stop a company from reaching 100% synced: work claimed by a
          worker that never came back, and a pipe whose account is dead. Both are stated up front with
          a one-click route to the affected items — not left for someone to notice in a card. */}
      {(stuckTotal > 0 || brokenConns.length > 0) && (
        <div className="callout warn" style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          {stuckTotal > 0 && (
            <span>
              {stuckTotal === 1 ? <><b>פריט אחד</b> תקוע</> : <><b>{stuckTotal.toLocaleString('he-IL')}</b> פריטים תקועים</>} בעיבוד מעבר לזמן הקצוב.
            </span>
          )}
          {brokenConns.length > 0 && (
            <span>
              {/* (one is said as one: «1 מקורות על חיבור מנותק» stood here) */}
              {brokenConns.length === 1 ? <b>מקור אחד</b> : <><b>{brokenConns.length}</b> מקורות</>} על חיבור מנותק ({brokenConns.map((e) => e.connection_label).join(', ')}).
            </span>
          )}
          <button className="btn" onClick={() => { setView('board'); setBoardSeed((n) => n + 1); }}>
            טפל בלוח הפריטים
          </button>
        </div>
      )}

      <div className="subnav" style={{ marginBottom: 12 }}>
        <button className={`stab${view === 'pipes' ? ' active' : ''}`} onClick={() => setView('pipes')}>
          מקורות<span className="n num">{registry.length}</span>
        </button>
        <button className={`stab${view === 'board' ? ' active' : ''}`} onClick={() => setView('board')}>
          לוח פריטים<span className="n num">{(totals.to_sync + totals.in_progress + totals.failed).toLocaleString('he-IL')}</span>
        </button>
      </div>

      <div className="hud">
        <BigStat k="לסנכרון" v={totals.to_sync} cls={totals.to_sync ? 'wait' : undefined} />
        <BigStat k="בתהליך" v={totals.in_progress} cls={totals.in_progress ? 'run' : undefined} />
        <BigStat k="סונכרן" v={totals.synced} cls="ok" />
        <BigStat k="נכשל" v={totals.failed} cls={totals.failed ? 'err' : undefined} />
        <BigStat k="מקורות" v={registry.length} />
        <BigStat k="תקועים" v={stuckTotal} cls={stuckTotal ? 'wait' : undefined} />
      </div>

      {view === 'board' && (
        <SyncBoard key={boardSeed} registry={registry} onChanged={load} />
      )}

      {view === 'pipes' && (
      <>
      <div className="app-header" style={{ marginTop: 18 }}>
        <h3 style={{ margin: 0 }}>מקורות סנכרון</h3>
        <div className="actions">
          <button className="btn" onClick={() => setCreating(true)}><Ic p={IC.plus} /> מקור סנכרון חדש</button>
        </div>
      </div>

      {!registry.length && (
        <div className="callout">
          למופע הזה אין עדיין מקורות סנכרון. הוסיפו אחד כדי להתחיל למשוך מסמכים מחיבור קיים.
        </div>
      )}

      <div className="pipes">
        {registry.map((e) => (
          <PipeCard
            key={e.name}
            entry={e}
            running={runningOne === e.name}
            lists={lists}
            onRun={() => runOne(e.name)}
            onToggle={() => toggle(e)}
            onEdit={() => setEditing(e)}
            onDelete={() => remove(e)}
            onPickState={(s) => setDrawer({ sync: e.name, state: s })}
            onPickFailure={() => { setView('board'); setBoardSeed((n) => n + 1); }}
          />
        ))}
      </div>
      </>
      )}

      {drawer && (
        <ItemsDrawer
          sync={drawer.sync}
          state={drawer.state}
          onClose={() => setDrawer(null)}
          onChanged={load}
        />
      )}
      {(creating || editing) && (
        <PipeEditor
          existing={editing}
          onClose={() => { setCreating(false); setEditing(null); }}
          onSaved={() => { load(); setListsSeed((n) => n + 1); }}
        />
      )}
    </div>
  );
}
