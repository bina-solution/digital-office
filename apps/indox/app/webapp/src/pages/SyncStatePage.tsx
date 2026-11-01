import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, SyncItem, SyncItemCounts, SyncRegistryEntry, SyncSkipNote, SyncSummary } from '../api';
import { Ic, useToasts } from '../components/DataGrid';
import { useConfirm } from '../components/ConfirmModal';
import SyncEditor, { AUTHORITY_HE, SCHEDULER_MIN, SRC_LABEL } from '../components/SyncEditor';
import { IC } from '../icons';
import { useInstanceLink, useInstanceParam } from '../instancesContext';
import {
  Conn, ConnKind, Folder, IN_CONSOLE, Probe, SIBLINGS_NOTE, connections, driveFiles, driveFolders,
  LocParts, folderParts, pathParts, mailLabels, mailMessages, organizerLabelMap, probeConnection,
} from '../siblings';
import { foldReason, reasonView } from '../reasons';
import '../sync.css';

/**
 * INDOX · סנכרון — the card and the summary (RELEASE-DECISIONS N4), the editor (N5), one notice
 * channel and confirmations with facts (N13).
 *
 * Every NUMBER on this page is the SYNC ITEM (`sync_item_counts` over `sync_ledger`, served by the
 * BFF, which talks to no other app). Every NAME and every HEALTH DOT is read by the BROWSER from the
 * sibling apps under the console shell (siblings.ts) — allowed, because the owner's rule is about
 * the server. Outside the console those read "לא נבדק" and ids stay ids; nothing is guessed.
 *
 * Everything that opens (the editor, the items drawer, the reconcile) lives in the URL
 * (`?new=1`, `?edit=<name>`, `?items=<name>&status=…`, `?reconcile=<name>`), so a screen survives a
 * reload and a link opens exactly what was on it. While one is open the 5 s poll is frozen — a
 * drawer that remounted under the operator's cursor every five seconds was defect #1 of N5.
 */

const POLL_MS = 5000;
/** N10: nothing before this date was imported into the ledger */
const HISTORY_SINCE_FALLBACK = '2026-08-28';
/** the reconcile reads this many newest items at the source, and this many ledger rows */
const RECON_SOURCE_N = 200;
const RECON_ITEMS_N = 5000;

type BarKey = 'to_sync' | 'in_progress' | 'synced' | 'failed';
const BAR_ORDER: BarKey[] = ['to_sync', 'in_progress', 'synced', 'failed'];
const BAR_LABEL: Record<BarKey, string> = { to_sync: 'לסנכרון', in_progress: 'בתהליך', synced: 'סונכרן', failed: 'נכשל' };
/** the ledger status each bar segment opens in the items drawer */
const BAR_STATUS: Record<BarKey, string> = { to_sync: 'discovered', in_progress: 'claimed', synced: 'delivered', failed: 'failed' };
const STATUS_HE: Record<string, string> = {
  discovered: 'לסנכרון', claimed: 'בתהליך', delivered: 'סונכרן', failed: 'נכשל', needs_review: 'דורש בדיקה',
};
const STATUS_KIND: Record<string, string> = {
  discovered: 'muted', claimed: 'warn', delivered: 'ok', failed: 'bad', needs_review: 'degraded',
};

/** the document types a pipe can expect, in the operator's language (the key is the title) */
const TYPE_HE: Record<string, string> = {
  INVOICE: 'חשבונית', BALANCE_SHEET: 'דוח גיול', SHIPMENT: 'תעודת משלוח', ORDER: 'הזמנה', RECEIPT: 'קבלה', GDOC: 'מסמך',
};
/** the scheduler's one-word notes on a pass */
const NOTE_HE: Record<string, string> = { dispatched: 'הופעל', skipped: 'דולג', error: 'שגיאה', held: 'ממתין לסבב פעיל' };

const ZERO: SyncItemCounts = { discovered: 0, claimed: 0, delivered: 0, failed: 0, needs_review: 0, total: 0 };
const countsOf = (e: SyncRegistryEntry): SyncItemCounts => e.counts ?? ZERO;
const barOf = (c: SyncItemCounts): Record<BarKey, number> => ({
  to_sync: c.discovered, in_progress: c.claimed, synced: c.delivered, failed: c.failed,
});
const he = (n: number) => n.toLocaleString('he-IL');

function ago(iso?: string | null): string {
  if (!iso) return '—';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return String(iso);
  const m = Math.round((Date.now() - t) / 60000);
  if (m < 1) return 'עכשיו';
  if (m < 60) return `לפני ${m} דק׳`;
  if (m < 1440) return `לפני ${Math.round(m / 60)} שע׳`;
  const d = Math.round(m / 1440);               // (one is said as one: «לפני 1 ימים» is «לפני יום»)
  return d === 1 ? 'לפני יום' : `לפני ${d} ימים`;
}
function fmtClock(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit' });
}
function fmtDateTime(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? String(iso)
    : d.toLocaleString('he-IL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}
function fmtDay(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleDateString('he-IL');
}
function fmtSize(v: unknown): string {
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/* ── sibling reads shared by every card (one catalog, one list per connection) ───────────────── */
function useConnCatalog() {
  const [conns, setConns] = useState<Map<string, Conn> | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  useEffect(() => {
    let dead = false;
    if (!IN_CONSOLE) { setConns(new Map()); return; }
    connections()
      .then((r) => { if (!dead) { setConns(new Map(r.conns.map((c) => [c.id, c]))); setErrors(r.errors); } })
      .catch((e: unknown) => { if (!dead) { setConns(new Map()); setErrors([e instanceof Error ? e.message : String(e)]); } });
    return () => { dead = true; };
  }, []);
  return { conns, errors };
}
function useFolderMap(connId: string | null | undefined): Map<string, Folder> | null {
  const [m, setM] = useState<Map<string, Folder> | null>(null);
  useEffect(() => {
    let dead = false;
    if (!IN_CONSOLE || !connId) { setM(new Map()); return; }
    setM(null);
    driveFolders(connId)
      .then((fs) => { if (!dead) setM(new Map(fs.map((f) => [f.id, f]))); })
      .catch(() => { if (!dead) setM(new Map()); });
    return () => { dead = true; };
  }, [connId]);
  return m;
}
function useLabelSet(connId: string | null | undefined): Set<string> | null {
  const [s, setS] = useState<Set<string> | null>(null);
  useEffect(() => {
    let dead = false;
    if (!IN_CONSOLE || !connId) { setS(new Set()); return; }
    setS(null);
    mailLabels(connId)
      .then((ls) => { if (!dead) setS(new Set(ls)); })
      .catch(() => { if (!dead) setS(new Set()); });
    return () => { dead = true; };
  }, [connId]);
  return s;
}
/** organizer KEY → label NAME; the registry stores keys, the mailbox lists names */
function useLabelMap(enabled: boolean): Map<string, string> | null {
  const [m, setM] = useState<Map<string, string> | null>(null);
  useEffect(() => {
    let dead = false;
    if (!IN_CONSOLE || !enabled) { setM(new Map()); return; }
    setM(null);
    organizerLabelMap()
      .then((r) => { if (!dead) setM(r); })
      .catch(() => { if (!dead) setM(new Map()); });
    return () => { dead = true; };
  }, [enabled]);
  return m;
}
function useProbe(kind: ConnKind, id: string | null | undefined): Probe | null {
  const [p, setP] = useState<Probe | null>(null);
  useEffect(() => {
    let dead = false;
    if (!id) { setP({ state: 'unknown', reason: 'אין חיבור מוגדר', at: Date.now() }); return; }
    setP(null);
    probeConnection(kind, id).then((r) => { if (!dead) setP(r); });
    return () => { dead = true; };
  }, [kind, id]);
  return p;
}

/** the connection named on the card, with its health dot (browser probe, never a guess) */
function ConnLine({ kind, id, conn }: { kind: ConnKind; id: string | null; conn: Conn | undefined }) {
  const probe = useProbe(kind, id);
  const title = probe
    ? probe.state === 'ok' ? 'החיבור נבדק עכשיו בדפדפן ומשיב'
      : probe.state === 'bad' ? `החיבור לא משיב: ${probe.reason || 'ללא סיבה'}`
        : `לא נבדק — ${probe.reason || SIBLINGS_NOTE}`
    : 'בודק את החיבור…';
  /* the identity (protocol · profile · account) is one hover away, never in the headline: on the
     card it read "drive_local · admin · admin · מנהל", a database line on a Hebrew page */
  const full = [title, conn?.identity ? `חיבור: ${conn.identity}` : '', id ? `מזהה: ${id}` : ''].filter(Boolean).join('\n');
  return (
    <span className="connline" title={full}>
      <span className={`hdot ${probe ? probe.state : 'busy'}`} aria-label={title} />
      <Ic p={kind === 'gmail' ? IC.mail : IC.drive} />
      <span className="nm">{conn?.label || conn?.account_hint || id || '— ללא חיבור'}</span>
      {probe && probe.state !== 'ok' && (
        <span className="small" style={{ color: probe.state === 'bad' ? 'var(--red)' : 'var(--muted)', whiteSpace: 'nowrap' }}>
          {probe.state === 'bad' ? 'לא משיב' : 'לא נבדק'}
        </span>
      )}
    </span>
  );
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
     siblings apart, and the reason every drive-bs fact read "חשבוניות הכנסים/כרטסות ספקים - ...".
     The split has one owner: folderParts() / pathParts() in siblings.ts. */
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

/** where the pipe reads from and where it files to — a hairline grid of facts, one line each */
function PipeFacts({ entry, folders, destFolders, labels, labelMap }: {
  entry: SyncRegistryEntry;
  folders: Map<string, Folder> | null;
  destFolders: Map<string, Folder> | null;
  labels: Set<string> | null;
  /** organizer KEY → NAME (null while it loads) */
  labelMap: Map<string, string> | null;
}) {
  const fparts = (m: Map<string, Folder> | null, id: string) => (m ? folderParts(m, id) : null);
  const fknown = (m: Map<string, Folder> | null, id: string) => (m ? m.has(id) : null);
  /* a registry label is an organizer KEY; the engine resolves it to the NAME the mailbox carries
     (a key the store does not know is used literally, by the engine and here alike) */
  const lparts = (key: string) => (labelMap ? pathParts(labelMap.get(key) || key) : null);
  const lknown = (key: string) => (labels && labelMap ? labels.has(labelMap.get(key) || key) : null);
  if (entry.source === 'gmail') {
    const l = entry.labels || {};
    const dest = String(entry.dest_folder || '');
    const key = (v: unknown) => String(v || '');
    return (
      <div className="pipe-facts c4" aria-label="תוויות ויעד">
        <Fact k="תווית מקור" icon={IC.tag} id={key(l.to_sync)} parts={lparts(key(l.to_sync))} known={lknown(key(l.to_sync))} />
        <Fact k="אחרי סנכרון" id={key(l.synced)} parts={lparts(key(l.synced))} known={lknown(key(l.synced))} none="ללא תווית" />
        <Fact k="כשלים" id={key(l.failed)} parts={lparts(key(l.failed))} known={lknown(key(l.failed))} none="ללא תווית" />
        <Fact k="הקבצים נשמרים אל" icon={IC.folder} id={dest} parts={fparts(destFolders, dest)} known={fknown(destFolders, dest)} none="לא נבחרה תיקייה" />
      </div>
    );
  }
  const pairs = (entry.pairs || []) as { from?: string; to_sync?: string; to?: string; synced?: string; failed?: string; failed_to?: string }[];
  const p = pairs[0] || {};
  const src = String(p.to_sync || p.from || '');
  const dst = String(p.synced || p.to || '');
  const failed = String(p.failed || p.failed_to || '');
  const more = pairs.length > 1 ? ` (+${pairs.length - 1} זוגות)` : '';
  return (
    <div className="pipe-facts c3" aria-label="תיקיות">
      <Fact k={`תיקיית מקור${more}`} icon={IC.folder} id={src} parts={fparts(folders, src)} known={fknown(folders, src)} />
      <Fact k="אחרי סנכרון" id={dst} parts={fparts(folders, dst)} known={fknown(folders, dst)} none="נשאר במקומו" />
      <Fact k="כשלים" id={failed} parts={fparts(folders, failed)} known={fknown(folders, failed)} none="נשאר במקומו" />
    </div>
  );
}

/* ── THE bar: four states, every non-zero state visibly present, every segment a door ─────────── */
function StateBar({ counts, onPick, picked }: { counts: SyncItemCounts; onPick: (status: string) => void; picked?: string | null }) {
  const bar = barOf(counts);
  const total = BAR_ORDER.reduce((a, k) => a + bar[k], 0);
  const MIN_PCT = 6;
  const raw = BAR_ORDER.map((k) => (bar[k] > 0 ? Math.max(MIN_PCT, (bar[k] / Math.max(1, total)) * 100) : 0));
  const sum = raw.reduce((a, x) => a + x, 0) || 1;
  const tip: Record<BarKey, string> = {
    to_sync: `לסנכרון: ${he(bar.to_sync)} — התגלו וטרם נמסרו`,
    in_progress: `בתהליך: ${he(bar.in_progress)} — נלקחו למסירה בסבב הזה`,
    synced: `סונכרנו: ${he(bar.synced)}`,
    failed: `נכשלו: ${he(bar.failed)} — ייעשה ניסיון חוזר עם השהיה`,
  };
  return (
    <>
      <div className="statebar" role="group" aria-label="מצב הסנכרון — לחיצה על מקטע פותחת את הפריטים">
        {BAR_ORDER.map((k, i) =>
          bar[k] > 0 ? (
            <button key={k} type="button" className={`seg ${k}`} style={{ width: `${(raw[i] / sum) * 100}%` }}
                    title={`${tip[k]} · לחיצה פותחת את הפריטים`} aria-label={tip[k]} onClick={() => onPick(BAR_STATUS[k])} />
          ) : null,
        )}
        {total === 0 && <div className="seg" style={{ width: '100%', background: 'transparent' }} title="אין פריטים" />}
      </div>
      <div className="statelegend">
        {BAR_ORDER.map((k) => (
          <button key={k} type="button" className="li" title={`${tip[k]} · לחיצה פותחת את הפריטים במצב הזה`}
                  aria-pressed={picked === BAR_STATUS[k]} onClick={() => onPick(BAR_STATUS[k])}>
            <span className={`sw ${k}`} />{BAR_LABEL[k]}<b className="num">{he(bar[k])}</b>
          </button>
        ))}
        <button type="button" className="li" aria-pressed={picked === 'needs_review'}
                title={`דורשים בדיקה: ${he(counts.needs_review)} — פריטים שהמנוע הפסיק לנסות (מצב סופי עד ניסיון חוזר ידני). לחיצה פותחת אותם.`}
                onClick={() => onPick('needs_review')}>
          <span className="sw review" />דורש בדיקה<b className="num">{he(counts.needs_review)}</b>
        </button>
      </div>
    </>
  );
}

/* ── the pipe card ───────────────────────────────────────────────────────────────────────────── */
function PipeCard({ entry, busy, conns, n8nBase, onRun, onRetry, onToggle, onEdit, onDelete, onItems }: {
  entry: SyncRegistryEntry;
  busy: string | null;
  conns: Map<string, Conn> | null;
  n8nBase: string;
  onRun: () => void; onRetry: () => void; onToggle: () => void; onEdit: () => void; onDelete: () => void;
  onItems: (status: string, reason?: string) => void;
}) {
  const link = useInstanceLink();
  const c = countsOf(entry);
  const known = entry.counts != null && entry.counts_computed !== false;
  const paused = entry.enabled === false;
  const red = c.failed + c.needs_review;
  const kind: ConnKind = entry.source === 'gmail' ? 'gmail' : 'drive';
  const connId = entry.connection ? String(entry.connection) : null;
  const conn = connId && conns ? conns.get(connId) : undefined;
  const folders = useFolderMap(kind === 'drive' ? connId : null);
  const destFolders = useFolderMap(kind === 'gmail' ? (entry.drive_connection_id ? String(entry.drive_connection_id) : null) : null);
  const labels = useLabelSet(kind === 'gmail' ? connId : null);
  const labelMap = useLabelMap(kind === 'gmail');
  const cadence = entry.cadence_min ?? entry.batch?.schedule_min ?? SCHEDULER_MIN;
  const take = entry.batch?.take;
  const chunk = entry.batch?.chunk;
  const lastUrl = entry.last_run_url
    || (entry.last_run_execution && n8nBase ? `${n8nBase.replace(/\/+$/, '')}/executions/${entry.last_run_execution}` : null);
  const isBusy = (k: string) => busy === `${k}:${entry.name}`;
  const anyBusy = Boolean(busy);
  /* the one link out of this card (owner rule: no docs-state overview here — at most a link to
     the table narrowed to this pipe): the grid's own equals-filter on SYNC_NAME */
  const docsTo = link(`/documents?f_SYNC_NAME=${encodeURIComponent(entry.name)}`);

  const reasons = (entry.reasons || []).slice(0, 3);
  /* the last error is the top reason chip whenever reasons exist; it is shown on its own only
     when the ledger has no reason rows to explain the red count */
  const lastErr = !reasons.length && entry.last_error ? reasonView(String(entry.last_error)) : null;

  return (
    <div className={`card pipe${paused ? ' paused' : ''}`}>
      <div className="pipe-head">
        <span className="name" title={entry.name}>{entry.name}</span>
        <span className="tag">{SRC_LABEL[entry.source || 'drive'] || entry.source}</span>
        {entry.type_hint && (
          <span className="tag" title={`סוג מסמך צפוי: ${String(entry.type_hint)} · ${AUTHORITY_HE[String(entry.type_authority || 'hint')] || ''}`}>
            {TYPE_HE[String(entry.type_hint)] || String(entry.type_hint)}
          </span>
        )}
        {paused && <span className="pill warn" title="המקור מושהה — הסבב מדלג עליו">מושהה</span>}
        <span className="spacer" />
        <ConnLine kind={kind} id={connId} conn={conn} />
      </div>

      <PipeFacts entry={entry} folders={folders} destFolders={destFolders} labels={labels} labelMap={labelMap} />

      {known
        ? <div><StateBar counts={c} onPick={(s) => onItems(s)} /></div>
        : <div className="callout warn" style={{ margin: 0 }}>מצב הפריטים לא נקרא — טבלת הסנכרון אינה זמינה כרגע.</div>}

      {(reasons.length > 0 || lastErr) && (
        <div className="reasons" aria-label="הסיבות לפריטים האדומים">
          {reasons.map((r) => {
            const v = reasonView(r.reason);
            if (!v) return null;
            return (
              <button key={r.reason} type="button" className={`reason ${v.kind}`}
                      title={`${v.translated ? `${v.raw}\n` : ''}${he(r.count)} פריטים${r.last_at ? ` · האחרון ${fmtDateTime(r.last_at)}` : ''} · לחיצה פותחת אותם`}
                      onClick={() => onItems('', r.reason)}>
                <span className="n num">{he(r.count)}</span>
                <span className={`t${v.translated ? '' : ' raw'}`}>{v.he}</span>
              </button>
            );
          })}
          {lastErr && (
            <span className={`reason ${lastErr.kind}`} title={lastErr.translated ? lastErr.raw : undefined} style={{ cursor: 'default' }}>
              <span className="n">שגיאה אחרונה</span>
              <span className={`t${lastErr.translated ? '' : ' raw'}`}>{lastErr.he}</span>
            </span>
          )}
        </div>
      )}

      <div className="pipe-activity">
        <span className="it" title={`הסבב רץ כל ${cadence} דק׳${take != null ? ` · עד ${take} פריטים לסבב` : ''}${chunk != null ? ` · בנגלות של ${chunk}` : ''}`}>
          <Ic p={IC.clock} /> כל <b className="num">{cadence}</b> דק׳{take != null && <> · <b className="num">{take}</b> לסבב</>}
        </span>
        <span className="it" title={entry.last_run ? `הרצה אחרונה ${fmtDateTime(entry.last_run)}` : 'המקור טרם רץ'}>
          <Ic p={IC.activity} /> הרצה אחרונה <b>{ago(entry.last_run)}</b>
          {lastUrl && (
            <a className="link" href={lastUrl} target="_blank" rel="noreferrer" title="ההרצה האחרונה של המקור במנוע האוטומציה">
              פתח ב-n8n <Ic p={IC.external} />
            </a>
          )}
        </span>
        {entry.last_delivered_at && (
          <span className="it" title={`מסירה אחרונה ${fmtDateTime(entry.last_delivered_at)}`}>
            <Ic p={IC.check} /> מסירה אחרונה <b>{ago(entry.last_delivered_at)}</b>
          </span>
        )}
        {entry.oldest_waiting_at && (entry.waiting || 0) > 0 && (
          <span className="it" title={`${he(entry.waiting || 0)} ממתינים · הוותיק ביותר התגלה ${fmtDateTime(entry.oldest_waiting_at)} (פריטים הדורשים בדיקה אינם נספרים)`}>
            <Ic p={IC.alert} /> הוותיק בתור <b>{ago(entry.oldest_waiting_at)}</b>
          </span>
        )}
        <span className="spacer" />
        <Link className="link" to={docsTo} title="טבלת המסמכים מסוננת למקור הזה"><Ic p={IC.file} /> המסמכים של המקור</Link>
      </div>

      <div className="pipe-foot">
        <label className="switchlbl" title={paused ? 'הפעלה — המקור יחזור לסבב האוטומטי' : 'השהיה — הסבב ידלג על המקור; ההגדרה נשמרת'}>
          <button type="button" className={`switch${!paused ? ' on' : ''}`} role="switch" aria-checked={!paused}
                  aria-label={paused ? 'הפעלת המקור' : 'השהיית המקור'} onClick={onToggle} disabled={anyBusy}>
            <span className="knob" />
          </button>
          {isBusy('toggle') ? <span className="spinner" /> : paused ? 'מושהה' : 'פעיל'}
        </label>
        <button className="btn sm" onClick={onRun} disabled={anyBusy || paused}
                title={paused ? 'המקור מושהה — הפעילו אותו לפני הרצה' : 'מריץ סבב סנכרון עכשיו: גילוי במקור ומסירה של מה שהתגלה'}>
          {isBusy('run') ? <span className="spinner" /> : <Ic p={IC.play} />} הרץ
        </button>
        {red > 0 && (
          <button className="btn sm ghost" onClick={onRetry} disabled={anyBusy}
                  title={`מחזיר ${he(red)} פריטים שנכשלו או דורשים בדיקה לתור ומתחיל סבב`}>
            {isBusy('retry') ? <span className="spinner" /> : <Ic p={IC.refresh} />} נסה שוב <span className="num">({he(red)})</span>
          </button>
        )}
        <button className="btn sm ghost" onClick={() => onItems('')} title="כל פריטי הסנכרון של המקור, עם הסיבה לכל אחד">
          <Ic p={IC.list} /> פריטים
        </button>
        <span className="spacer" />
        <button className="btn sm ghost" onClick={onEdit} disabled={anyBusy} title="פותח את עורך המקור — שומר רק שדות ששונו">
          <Ic p={IC.edit} /> עריכה
        </button>
        <button className="btn sm ghost danger" onClick={onDelete} disabled={anyBusy}
                title="מוחק את ההגדרה ואת שורות ספר הסנכרון שלה — אחרי אישור עם המספרים">
          {isBusy('del') ? <span className="spinner" /> : <Ic p={IC.trash} />} מחיקה
        </button>
      </div>
    </div>
  );
}

/* ── the items drawer: one pipe's ledger rows, with the reason on each ───────────────────────── */
function ItemsDrawer({ entry, status, reason, onStatus, onClose, docsLink }: {
  entry: SyncRegistryEntry;
  status: string;
  reason: string | null;
  onStatus: (s: string, reason?: string | null) => void;
  onClose: () => void;
  docsLink: (docId: string) => string;
}) {
  const [items, setItems] = useState<SyncItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [limit, setLimit] = useState(200);
  const c = countsOf(entry);

  useEffect(() => {
    let dead = false;
    setItems(null);
    setErr(null);
    api.getSyncItems(entry.name, { status: status || undefined, limit })
      .then((r) => {
        if (dead) return;
        if (r.reachable === false) setErr(r.error || 'טבלת הסנכרון אינה זמינה');
        setItems(r.items || []);
      })
      .catch((e: unknown) => { if (!dead) { setErr(e instanceof Error ? e.message : String(e)); setItems([]); } });
    return () => { dead = true; };
  }, [entry.name, status, limit]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onClose]);

  /* a chip carries the FOLDED reason (identifiers collapsed, the way the card groups them), so a
     row matches on its folded text — the raw sentence keeps its ids */
  const shown = useMemo(
    () => (reason ? (items || []).filter((i) => foldReason(i.reason) === reason || String(i.reason || '') === reason) : items || []),
    [items, reason],
  );
  const reasonHe = reason ? reasonView(reason) : null;
  const chips: { s: string; l: string; n: number }[] = [
    { s: '', l: 'הכל', n: c.total },
    { s: 'discovered', l: STATUS_HE.discovered, n: c.discovered },
    { s: 'claimed', l: STATUS_HE.claimed, n: c.claimed },
    { s: 'delivered', l: STATUS_HE.delivered, n: c.delivered },
    { s: 'failed', l: STATUS_HE.failed, n: c.failed },
    { s: 'needs_review', l: STATUS_HE.needs_review, n: c.needs_review },
  ];
  const nameOf = (i: SyncItem) => String(i.listing?.name || i.listing?.subject || '') || '';

  return (
    <div className="drawer-ov">
      <div className="scrim" onClick={onClose} />
      <div className="drawer" style={{ maxWidth: 720 }} role="dialog" aria-modal="true" aria-label={`פריטי הסנכרון של ${entry.name}`}>
        <div className="drawer-h">
          <div style={{ minWidth: 0 }}>
            <h3>פריטי סנכרון · <span className="mono">{entry.name}</span></h3>
            <div className="muted small">שורות ספר הסנכרון של המקור — כל שורה עם מצבה והסיבה שנרשמה עליה.</div>
          </div>
          <button className="icbtn" onClick={onClose} aria-label="סגירה" title="סגירה (Esc)"><Ic p={IC.x} /></button>
        </div>
        <div className="drawer-body">
          <div className="atl-chips" style={{ marginBottom: 10 }}>
            {chips.map((ch) => (
              <button key={ch.s} type="button" className={`chip${status === ch.s ? ' on' : ''}`} aria-pressed={status === ch.s}
                      onClick={() => onStatus(ch.s, reason)} title={`${ch.l}: ${he(ch.n)} פריטים`}>
                {ch.l}<span className="num">{he(ch.n)}</span>
              </button>
            ))}
          </div>
          {reason && (
            <div className="callout warn" style={{ marginTop: 0 }}>
              מסונן לסיבה <b title={reasonHe?.translated ? reasonHe.raw : undefined}>{reasonHe?.he || reason}</b>{' '}
              <button className="link" onClick={() => onStatus(status, null)}>הסר סינון</button>
            </div>
          )}
          {err && <div className="callout bad">{err}</div>}
          {items === null && !err && <div className="spin">טוען פריטים…</div>}
          {items !== null && shown.length === 0 && !err && (
            <div className="callout">
              {reason ? 'אין פריטים עם הסיבה הזו בין הפריטים שנקראו.' : status ? `אין פריטים במצב «${STATUS_HE[status] || status}».` : 'אין פריטים למקור הזה.'}
            </div>
          )}
          {shown.length > 0 && (
            <div className="tbl-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>פריט</th>
                    <th>מצב</th>
                    <th>סיבה</th>
                    <th>התגלה</th>
                    <th>נמסר</th>
                    <th>מסמך</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((i) => {
                    const nm = nameOf(i);
                    const from = String(i.listing?.from || '');
                    const date = i.listing?.date ? String(i.listing.date) : '';
                    const size = fmtSize(i.listing?.size);
                    return (
                      <tr key={`${i.status}:${i.platform_id}`}>
                        <td style={{ maxWidth: 260 }}>
                          <div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                               title={`${nm || '(ללא רישום)'} · ${i.platform_id}`}>
                            {nm || <span className="muted">ללא רישום — פריט מהגירה</span>}
                          </div>
                          <div className="muted small" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {[from, date ? fmtDay(date) : '', size].filter(Boolean).join(' · ') || <span className="mono num">{i.platform_id}</span>}
                          </div>
                        </td>
                        <td>
                          <span className={`pill ${STATUS_KIND[i.status] || 'muted'}`} title={i.status}>{STATUS_HE[i.status] || i.status}</span>
                          {(i.attempts || 0) > 0 && <div className="muted small num">{i.attempts} ניסיונות</div>}
                        </td>
                        <td className="small reason-cell" style={{ maxWidth: 260 }}>
                          {(() => {
                            const v = reasonView(i.reason);
                            if (!v) return <span className="muted">—</span>;
                            /* the Hebrew sentence in the cell, the engine's original one hover away —
                               stacking both made a 300 px row of the drawer's first item */
                            return <span className={v.translated ? 'he' : 'raw'} title={v.raw}>{v.he}</span>;
                          })()}
                          {i.not_before && i.status === 'failed' && (
                            <div className="muted small" title={fmtDateTime(i.not_before)}>ניסיון הבא: {fmtDateTime(i.not_before)}</div>
                          )}
                        </td>
                        <td className="muted small num" title={fmtDateTime(i.discovered_at)}>{ago(i.discovered_at)}</td>
                        <td className="muted small num" title={i.delivered_at ? fmtDateTime(i.delivered_at) : ''}>{i.status === 'delivered' ? ago(i.delivered_at) : '—'}</td>
                        <td>
                          {i.doc_id ? <Link className="link" to={docsLink(String(i.doc_id))} title={String(i.doc_id)}>פתח</Link> : <span className="muted">—</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {items !== null && items.length >= limit && (
            <div className="muted small" style={{ marginTop: 8 }}>
              מוצגים {he(limit)} הפריטים האחרונים.{' '}
              <button className="link" onClick={() => setLimit((l) => l + 500)}>טען עוד 500</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── the reconcile: newest N at the source vs this pipe's items, in the browser ─────────────── */
interface ReconResult {
  sourceN: number;
  known: number;
  unknown: { id: string; name: string; when: string }[];
  itemsN: number;
  itemsCapped: boolean;
  at: Date;
  note: string;
}

function ReconcileModal({ entries, initial, onPick, onClose }: {
  entries: SyncRegistryEntry[];
  initial: string;
  onPick: (name: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(initial);
  const [running, setRunning] = useState(false);
  const [res, setRes] = useState<ReconResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const entry = entries.find((e) => e.name === name) || null;

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape' && !running) onClose(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onClose, running]);

  async function run() {
    if (!entry) return;
    setRunning(true);
    setErr(null);
    setRes(null);
    try {
      if (!IN_CONSOLE) throw new Error(SIBLINGS_NOTE);
      const conn = String(entry.connection || '');
      if (!conn) throw new Error('למקור אין חיבור מוגדר');
      let source: { id: string; name: string; when: string }[] = [];
      let note = '';
      if (entry.source === 'gmail') {
        const label = String(entry.labels?.to_sync || '');
        if (!label) throw new Error('למקור אין תווית מקור');
        const msgs = await mailMessages(conn, label, RECON_SOURCE_N);
        source = msgs.map((m) => ({ id: m.id, name: m.subject || '(ללא נושא)', when: m.date }));
        note = `${he(source.length)} ההודעות החדשות ביותר הנושאות את התווית «${label}» (התווית נשארת גם אחרי מסירה).`;
      } else {
        const pairs = (entry.pairs || []) as { from?: string; to_sync?: string }[];
        const folder = String(pairs[0]?.to_sync || pairs[0]?.from || '');
        if (!folder) throw new Error('למקור אין תיקיית מקור');
        const files = await driveFiles(conn, folder);
        files.sort((a, b) => String(b.created || b.modified || '').localeCompare(String(a.created || a.modified || '')));
        source = files.slice(0, RECON_SOURCE_N).map((f) => ({ id: f.id, name: f.name, when: String(f.created || f.modified || '') }));
        note = `${he(source.length)} הקבצים שבתיקיית המקור כרגע (קובץ שנמסר עובר לתיקיית «אחרי סנכרון», ולכן כאן אמורים להיות רק ממתינים).`;
      }
      const r = await api.getSyncItems(entry.name, { limit: RECON_ITEMS_N });
      const ids = new Set((r.items || []).map((i) => String(i.platform_id)));
      const unknown = source.filter((s) => !ids.has(s.id));
      setRes({
        sourceN: source.length,
        known: source.length - unknown.length,
        unknown,
        itemsN: (r.items || []).length,
        itemsCapped: (r.items || []).length >= RECON_ITEMS_N,
        at: new Date(),
        note,
      });
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="modal-ov" onMouseDown={(e) => { if (e.target === e.currentTarget && !running) onClose(); }}>
      <div className="modal" style={{ width: 'min(640px, 94vw)', maxHeight: '85vh', overflowY: 'auto' }} role="dialog" aria-modal="true" aria-label="בדיקת התאמה">
        <div className="modal-h">
          <h3><Ic p={IC.gitCompare} /> בדיקת התאמה — מקור מול ספר הסנכרון</h3>
          <button className="icbtn" onClick={onClose} aria-label="סגירה" title="סגירה (Esc)" disabled={running}><Ic p={IC.x} /></button>
        </div>
        <div className="muted small" style={{ marginBottom: 10, lineHeight: 1.6 }}>
          הדפדפן קורא את {he(RECON_SOURCE_N)} הפריטים החדשים ביותר מהמקור (דרך אפליקציית הדרייב או המייל) ובודק
          כמה מהם מוכרים לספר הסנכרון של המקור. בדיקה צנועה: היא עונה «מה במקור ואינו אצלנו», לא להפך.
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <label style={{ flex: 1, minWidth: 220 }}>מקור
            <select value={name} onChange={(e) => { setName(e.target.value); onPick(e.target.value); setRes(null); }}>
              <option value="">בחרו מקור…</option>
              {entries.map((e) => <option key={e.name} value={e.name}>{e.name} — {SRC_LABEL[e.source || 'drive']}</option>)}
            </select>
          </label>
          <button className="btn" onClick={run} disabled={!entry || running} title="מריץ את הבדיקה בדפדפן — קריאה בלבד">
            {running ? <><span className="spinner" /> בודק…</> : 'בדוק'}
          </button>
        </div>
        {!IN_CONSOLE && <div className="callout warn">{SIBLINGS_NOTE}</div>}
        {err && <div className="callout bad">הבדיקה נכשלה: {err}</div>}
        {res && (
          <div style={{ marginTop: 12 }}>
            <div className="statelegend" style={{ marginTop: 0 }}>
              <span className="li">במקור<b className="num">{he(res.sourceN)}</b></span>
              <span className="li"><span className="sw synced" />מוכרים<b className="num">{he(res.known)}</b></span>
              <span className="li"><span className={`sw ${res.unknown.length ? 'failed' : 'synced'}`} />לא מוכרים<b className="num">{he(res.unknown.length)}</b></span>
            </div>
            <div className="muted small" style={{ marginTop: 6 }}>
              {res.note} הושוו מול {he(res.itemsN)} שורות ספר{res.itemsCapped ? ` (הקריאה נעצרה בתקרת ${he(RECON_ITEMS_N)} — פריט ותיק יותר עלול להיראות «לא מוכר»)` : ''}.
              נבדק ב-{res.at.toLocaleTimeString('he-IL')}.
            </div>
            {res.unknown.length === 0 ? (
              <div className="callout ok" style={{ marginTop: 10 }}><b>תואם.</b> כל מה שנקרא מהמקור מוכר לספר הסנכרון.</div>
            ) : (
              <div className="callout warn" style={{ marginTop: 10 }}>
                <b>{he(res.unknown.length)} פריטים במקור שאינם בספר הסנכרון.</b> הסבב הבא אמור לגלות אותם; אם הם נשארים
                כאן סבב אחרי סבב, זו התשובה לבדוק (חלון הזמן, הסמן, או תווית שהוסרה).
                <div className="tbl-scroll" style={{ marginTop: 8, maxHeight: 220, overflowY: 'auto' }}>
                  <table className="table">
                    <thead><tr><th>פריט</th><th>תאריך</th><th>מזהה</th></tr></thead>
                    <tbody>
                      {res.unknown.slice(0, 25).map((u) => (
                        <tr key={u.id}>
                          <td style={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={u.name}>{u.name}</td>
                          <td className="num small muted">{u.when ? fmtDay(u.when) : '—'}</td>
                          <td className="mono small num">{u.id}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {res.unknown.length > 25 && <div className="muted small" style={{ marginTop: 6 }}>מוצגים 25 הראשונים מתוך {he(res.unknown.length)}.</div>}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── freshness — from the DB clock when the BFF stamps one; otherwise an elapsed time, which is
   honest whatever the two clocks disagree about ──────────────────────────────────────────────── */
function Freshness({ asOf, fetchedAt, err, frozen }: { asOf: string | null; fetchedAt: number | null; err: string | null; frozen: boolean }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 2000); return () => clearInterval(id); }, []);
  const age = fetchedAt ? now - fetchedAt : null;
  const live = !err && age !== null && age < POLL_MS * 3 && !frozen;
  const dbClock = asOf ? new Date(asOf) : null;
  const clockOk = dbClock && !Number.isNaN(dbClock.getTime());
  const text = clockOk
    ? `עודכן ${dbClock!.toLocaleTimeString('he-IL', { hour12: false })}`
    : age !== null ? `נקרא לפני ${Math.max(0, Math.round(age / 1000))} שנ׳` : 'טרם נקרא';
  const title = frozen
    ? 'הסקר מוקפא בזמן שחלון פתוח — ייחודש בסגירתו'
    : clockOk ? `שעון מסד הנתונים · ${asOf}` : 'זמן שחלף מאז הקריאה האחרונה (שעון הדפדפן; אין חותמת שעון מהשרת בתשובה)';
  return (
    <span className={`live${live ? '' : ' paused'}`} style={{ cursor: 'default' }} title={err || title}>
      <span className="beat" />
      {err ? 'לא מעודכן' : text}
    </span>
  );
}

/* ── the page ────────────────────────────────────────────────────────────────────────────────── */
export default function SyncStatePage() {
  const { push } = useToasts();
  const { ask, confirmUI } = useConfirm();
  const [params, setParams] = useSearchParams();
  const instance = useInstanceParam();
  const link = useInstanceLink();

  const [registry, setRegistry] = useState<SyncRegistryEntry[]>([]);
  const [summary, setSummary] = useState<SyncSummary | null>(null);
  const [n8nBase, setN8nBase] = useState('');
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [fetchedAt, setFetchedAt] = useState<number | null>(null);
  const [syncOn, setSyncOn] = useState<boolean | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const inFlight = useRef(false);
  const { conns, errors: connErrors } = useConnCatalog();

  /* what is open, from the URL */
  const editName = params.get('edit');
  const creating = params.get('new') === '1';
  const itemsName = params.get('items');
  const itemsStatus = params.get('status') || '';
  const itemsReason = params.get('reason');
  const reconcileName = params.get('reconcile');
  const reconcileOpen = params.has('reconcile');
  const overlayOpen = Boolean(editName) || creating || Boolean(itemsName) || reconcileOpen;
  const overlayRef = useRef(overlayOpen);
  overlayRef.current = overlayOpen;

  const setP = useCallback((patch: Record<string, string | null>) => {
    setParams((prev) => {
      const n = new URLSearchParams(prev);
      for (const [k, v] of Object.entries(patch)) { if (v === null || v === '') n.delete(k); else n.set(k, v); }
      return n;
    }, { replace: true });
  }, [setParams]);
  const closeOverlays = useCallback(
    () => setP({ edit: null, new: null, items: null, status: null, reason: null, reconcile: null }),
    [setP],
  );

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const reg = await api.getSyncRegistry();
      setRegistry(reg.registry || []);
      setSummary(reg.summary || null);
      setN8nBase(reg.n8n_base || '');
      setErr(reg.reachable === false ? reg.error || 'מקור הנתונים אינו זמין' : null);
      setFetchedAt(Date.now());
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }, []);
  const loadGate = useCallback(async () => {
    try {
      const r = await api.getConfigSettings();
      const row = (r.settings || []).find((s) => s.key === 'indoxSyncOn');
      setSyncOn(row ? String(row.value) !== 'false' : true); // missing row reads as ON (COALESCE)
    } catch { setSyncOn(null); }
  }, []);

  useEffect(() => { load(); loadGate(); }, [load, loadGate]);
  /* the poll — FROZEN while any overlay is open (N5): a drawer remounting every 5 s is not a
     drawer anyone can type into */
  useEffect(() => {
    const id = setInterval(() => { if (!document.hidden && !overlayRef.current) load(); }, POLL_MS);
    const onVisible = () => { if (!document.hidden && !overlayRef.current) load(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => { clearInterval(id); document.removeEventListener('visibilitychange', onVisible); };
  }, [load]);
  useEffect(() => {
    const h = () => { load(); loadGate(); };
    window.addEventListener('indox:instance-changed', h);
    return () => window.removeEventListener('indox:instance-changed', h);
  }, [load, loadGate]);
  /* an overlay closing = the numbers may have moved while the poll was frozen */
  const wasOpen = useRef(false);
  useEffect(() => {
    if (wasOpen.current && !overlayOpen) load();
    wasOpen.current = overlayOpen;
  }, [overlayOpen, load]);

  const totals = useMemo(() => {
    const t = summary?.totals;
    const computed = registry.reduce((acc, e) => {
      const c = countsOf(e);
      return {
        to_sync: acc.to_sync + c.discovered, in_progress: acc.in_progress + c.claimed, synced: acc.synced + c.delivered,
        failed: acc.failed + c.failed, needs_review: acc.needs_review + c.needs_review,
      };
    }, { to_sync: 0, in_progress: 0, synced: 0, failed: 0, needs_review: 0 });
    return {
      to_sync: t?.to_sync ?? computed.to_sync,
      in_progress: t?.in_progress ?? computed.in_progress,
      synced: t?.synced ?? computed.synced,
      failed: t?.failed ?? computed.failed,
      needs_review: t?.needs_review ?? computed.needs_review,
      sources: t?.sources ?? registry.length,
    };
  }, [summary, registry]);

  const withBusy = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    try { await fn(); } catch (e: unknown) { push('bad', e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); load(); }
  };
  const skipText = (s: SyncSkipNote[] | undefined) => (s || []).map((x) => x.he).join(' · ');
  const execAction = (url?: string | null, id?: string | null) =>
    url ? { label: 'פתח ב-n8n', run: () => { window.open(url, '_blank', 'noopener'); } }
      : id ? { label: `הרצה ${id}`, run: () => { navigator.clipboard?.writeText(String(id)).catch(() => {}); } }
        : undefined;

  const toggleGate = () => withBusy('gate', async () => {
    const next = !(syncOn ?? true);
    const r = await api.putConfigSetting('indoxSyncOn', next ? 'true' : 'false');
    if (r.reachable === false) throw new Error(r.error || 'המתג לא נשמר — השרת אינו זמין');
    setSyncOn(next);
    push('ok', next ? 'הסנכרון הופעל — הסבב הבא יגלה וימסור.' : 'הסנכרון הושהה — לא יתגלה ולא יימסר דבר עד להפעלה מחדש.');
  });
  const runAll = () => withBusy('all', async () => {
    const r = await api.runAllSyncs();
    if (r.status === 'ran' || (r.ran || 0) > 0) push('ok', `הופעלו ${r.ran ?? 0} מקורות${r.held ? ` · ${r.held} ממתינים לסבב פעיל` : ''}`);
    else if (r.status === 'skipped') push('warn', skipText(r.skipped) || 'סבב סנכרון אחר עדיין פעיל — ההרצה הבאה תתפוס.');
    else push('bad', (r.errors || []).join(' · ') || r.error || 'ההרצה לא בוצעה');
  });
  const runOne = (name: string) => withBusy(`run:${name}`, async () => {
    const r = await api.runSyncEntry(name);
    const ex = (r as { execution?: { execution_id?: string; url?: string | null } | null }).execution;
    if (r.status === 'ran') push('ok', `'${name}' הופעל — גילוי הסתיים, מסירות ממשיכות ברקע.`, execAction(ex?.url, ex?.execution_id));
    else if (r.status === 'skipped') push('warn', skipText(r.skipped) || `'${name}' לא הורץ — סבב אחר עדיין פעיל.`, execAction(ex?.url, ex?.execution_id));
    else push('bad', r.error || `'${name}' לא הורץ`, execAction(ex?.url, ex?.execution_id));
  });
  const toggle = (e: SyncRegistryEntry) => withBusy(`toggle:${e.name}`, async () => {
    const r = await api.patchSyncEntry(e.name, { enabled: e.enabled === false });
    if (r && r.success === false) throw new Error('השינוי לא נשמר — מסד הנתונים אינו זמין');
    push('ok', e.enabled === false ? `'${e.name}' הופעל — ייכנס לסבב הבא.` : `'${e.name}' הושהה — הסבב ידלג עליו.`);
  });

  const retry = async (e: SyncRegistryEntry) => {
    const c = countsOf(e);
    const red = c.failed + c.needs_review;
    const ok = await ask({
      title: `ניסיון חוזר · ${e.name}`,
      consequence: (
        <>
          <b className="num">{he(red)}</b> פריטים יחזרו למצב «לסנכרון» (הניסיונות מתאפסים, גם פריטים ללא רישום — הגילוי
          יאתר מחדש את מה שעדיין קיים במקור) ו<b>יתחיל סבב סנכרון</b> שימסור אותם. שום קובץ או הודעה במקור לא ייגעו.
        </>
      ),
      facts: [
        { label: 'נכשלו (בניסיון חוזר)', value: he(c.failed), kind: c.failed ? 'bad' : 'muted' },
        { label: 'דורשים בדיקה', value: he(c.needs_review), kind: c.needs_review ? 'warn' : 'muted' },
        ...((e.reasons || []).slice(0, 3).map((r) => {
          const v = reasonView(r.reason);
          return {
            label: `${he(r.count)} פריטים`,
            value: v?.translated
              ? <span title={v.raw}>{v.he}</span>
              : <span className="mono small" style={{ direction: 'ltr', unicodeBidi: 'isolate' }}>{r.reason.slice(0, 80)}</span>,
          };
        })),
        ...(!(e.reasons || []).length && e.last_error ? [{
          label: 'השגיאה האחרונה',
          value: (() => { const v = reasonView(String(e.last_error)); return v?.translated ? <span title={v.raw}>{v.he}</span> : <span className="mono small" style={{ direction: 'ltr', unicodeBidi: 'isolate' }}>{String(e.last_error).slice(0, 120)}</span>; })(),
        }] : []),
      ],
      confirmLabel: 'החזר לתור והרץ',
    });
    if (!ok) return;
    await withBusy(`retry:${e.name}`, async () => {
      const r = await api.resetSyncEntry(e.name);
      const started = r.started;
      const ex = started?.execution || r.execution || null;
      const parts = [`${he(r.reset ?? 0)} פריטים של '${e.name}' חזרו לתור`];
      if (r.no_listing) parts.push(`${he(r.no_listing)} מהם ללא רישום — יאותרו מחדש`);
      if (r.skipped) parts.push(`${he(r.skipped)} דולגו`);
      if (r.success === false) { push('bad', r.error || 'הניסיון החוזר נדחה'); return; }
      if (started?.status === 'ran') parts.push('הסבב התחיל');
      else if (started?.status === 'skipped') parts.push(`הסבב לא התחיל — ${started.detail || 'סבב אחר עדיין פעיל; הבא יתפוס'}`);
      else if (started?.status === 'error') parts.push(`הסבב לא התחיל: ${started.detail || 'שגיאה'}`);
      else parts.push('הסבב הבא ימסור אותם');
      const kind = started?.status === 'error' ? 'bad' : started?.status === 'skipped' ? 'warn' : 'ok';
      push(kind, parts.join(' · '), execAction(ex?.url, ex?.execution_id));
    });
  };

  const remove = async (e: SyncRegistryEntry) => {
    const c = countsOf(e);
    const known = e.counts != null && e.counts_computed !== false;
    const ok = await ask({
      title: `מחיקת המקור · ${e.name}`,
      danger: true,
      consequence: (
        <>
          ההגדרה תוסר מרשם הסנכרון ו<b>כל שורות ספר הסנכרון של המקור יימחקו</b> — ההיסטוריה של מה שהתגלה ונמסר
          ממנו. המסמכים שכבר נמסרו לטבלה נשארים; שום קובץ או הודעה במקור לא ייגעו. אין ביטול.
        </>
      ),
      facts: known ? [
        { label: 'שורות ספר שיימחקו', value: he(c.total), kind: c.total ? 'bad' : 'muted' },
        { label: 'מהן סונכרנו', value: he(c.delivered), kind: 'muted' },
        { label: 'לסנכרון · בתהליך', value: `${he(c.discovered)} · ${he(c.claimed)}`, kind: 'muted' },
        { label: 'נכשלו · דורשים בדיקה', value: `${he(c.failed)} · ${he(c.needs_review)}`, kind: c.failed + c.needs_review ? 'warn' : 'muted' },
      ] : undefined,
      unknown: known ? undefined : 'טבלת הסנכרון לא נקראה כרגע, ולכן לא ידוע כמה שורות ספר יימחקו עם המקור.',
      confirmLabel: 'מחק את המקור ואת שורותיו',
    });
    if (!ok) return;
    await withBusy(`del:${e.name}`, async () => {
      const r = await api.deleteSyncEntry(e.name);
      if (r && (r.success === false || r.deleted === false)) throw new Error(r.error || 'המחיקה לא בוצעה — מסד הנתונים אינו זמין');
      if (r.purge_error) push('warn', `'${e.name}' הוסר מהרשם, אך שורות הספר לא נמחקו: ${r.purge_error}`);
      else push('ok', `'${e.name}' נמחק${r.rows_removed != null ? ` · ${he(Number(r.rows_removed))} שורות ספר הוסרו` : ''}.`);
    });
  };

  const editing = editName ? registry.find((e) => e.name === editName) || null : null;
  const itemsEntry = itemsName ? registry.find((e) => e.name === itemsName) || null : null;
  const lastPass = summary?.last_pass || null;
  const nextAt = summary?.next_pass_at ? new Date(summary.next_pass_at) : null;
  const nowRef = summary?.as_of ? new Date(summary.as_of).getTime() : Date.now();
  const etaMin = nextAt && !Number.isNaN(nextAt.getTime()) ? Math.round((nextAt.getTime() - nowRef) / 60000) : null;
  const historySince = summary?.history_since || HISTORY_SINCE_FALLBACK;

  return (
    <div>
      {confirmUI}
      <div className="app-header">
        <div>
          <h1>סנכרון</h1>
          <div className="sub">
            מה התגלה בכל מקור, מה נמסר, מה נכשל ולמה — לפי ספר הסנכרון.{' '}
            {instance && <span className="tag" title="המופע שהרשם הזה שייך לו">{instance}</span>}{' '}
            <span className="tag" title={`ספר הסנכרון מתחיל ב-${fmtDay(historySince)} — היסטוריה ישנה יותר לא יובאה`}>
              היסטוריה מ-{fmtDay(historySince)}
            </span>
          </div>
        </div>
        <div className="actions">
          <Freshness asOf={summary?.as_of || null} fetchedAt={fetchedAt} err={err} frozen={overlayOpen} />
          <label className="switchlbl" title="המתג הראשי של הסנכרון: כבוי = שום סבב לא מגלה ולא מוסר (indoxSyncOn)">
            <button type="button" className={`switch${syncOn !== false ? ' on' : ''}`} role="switch" aria-checked={syncOn !== false}
                    aria-label="סנכרון פעיל" onClick={toggleGate} disabled={busy === 'gate' || syncOn === null}>
              <span className="knob" />
            </button>
            {busy === 'gate' ? <span className="spinner" /> : 'סנכרון פעיל'}
          </label>
          <button className="btn" onClick={runAll} disabled={!!busy || syncOn === false} title="מריץ סבב על כל המקורות הפעילים עכשיו">
            {busy === 'all' ? <span className="spinner" /> : <Ic p={IC.play} />} הרץ הכל
          </button>
          <button className="btn ghost" onClick={() => setP({ reconcile: registry[0]?.name || '' })} disabled={!registry.length}
                  title="משווה בדפדפן את הפריטים החדשים ביותר במקור מול ספר הסנכרון של מקור אחד">
            <Ic p={IC.gitCompare} /> בדיקת התאמה
          </button>
          <button className="btn ghost" onClick={() => setP({ new: '1' })} title="פותח את עורך המקור החדש — עם סקירה לפני היצירה">
            <Ic p={IC.plus} /> מקור חדש
          </button>
        </div>
      </div>

      {syncOn === false && <div className="callout warn">הסנכרון מושהה (indoxSyncOn=false). המקורות מוצגים, אך שום סבב לא ירוץ עד להפעלה.</div>}
      {err && <div className="callout bad">{err}</div>}
      {connErrors.length > 0 && <div className="callout warn">חלק מרשימת החיבורים לא נקרא מהאפליקציות השכנות: {connErrors.join(' · ')}</div>}
      {loading && <div className="spin">טוען…</div>}

      {!loading && registry.length > 0 && (
        <>
          <div className="sync-kpis" aria-label="סיכום כל המקורות">
            <div className="kpi to_sync" title="פריטים שהתגלו במקור וטרם נמסרו — הסבב הבא ימסור אותם"><div className="k"><span className="sw to_sync" />לסנכרון</div><div className="v num">{he(totals.to_sync)}</div></div>
            <div className="kpi in_progress" title="פריטים שנלקחו למסירה בסבב שרץ עכשיו"><div className="k"><span className="sw in_progress" />בתהליך</div><div className="v num">{he(totals.in_progress)}</div></div>
            <div className="kpi synced" title="פריטים שנמסרו לטבלת המסמכים"><div className="k"><span className="sw synced" />סונכרן</div><div className="v num">{he(totals.synced)}</div></div>
            <div className="kpi failed" title="פריטים שנכשלו — ייעשה ניסיון חוזר עם השהיה"><div className="k"><span className="sw failed" />נכשל</div><div className="v num">{he(totals.failed)}</div></div>
            <div className="kpi review" title="פריטים שהמנוע הפסיק לנסות — מצב סופי עד «נסה שוב»"><div className="k"><span className="sw review" />דורש בדיקה</div><div className="v num">{he(totals.needs_review)}</div></div>
          </div>
          <div className="passline" aria-label="הסבב">
            <div className="cell">
              <div className="k"><Ic p={IC.grid} /> מקורות</div>
              <div className="v num">{he(totals.sources)}</div>
              <div className="s">
                {he(registry.filter((e) => e.enabled !== false).length)} פעילים
                {registry.some((e) => e.enabled === false) && ` · ${he(registry.filter((e) => e.enabled === false).length)} מושהים`}
              </div>
            </div>
            <div className="cell">
              <div className="k"><Ic p={IC.activity} /> סבב אחרון</div>
              {lastPass ? (
                <>
                  <div className="v" title={fmtDateTime(lastPass.started_at)}>{ago(lastPass.started_at)}</div>
                  <div className="s">
                    {lastPass.seconds != null && <span className="num">{Math.round(Number(lastPass.seconds))} שנ׳</span>}
                    {lastPass.units != null && <span className="num">{he(Number(lastPass.units))} יחידות</span>}
                    {lastPass.note && <span>{NOTE_HE[String(lastPass.note)] || String(lastPass.note)}</span>}
                    {(lastPass.url || (lastPass.execution_id && n8nBase)) && (
                      <a className="link" href={lastPass.url || `${n8nBase.replace(/\/+$/, '')}/executions/${lastPass.execution_id}`}
                         target="_blank" rel="noreferrer" title="ההרצה במנוע האוטומציה">פתח ב-n8n <Ic p={IC.external} /></a>
                    )}
                  </div>
                </>
              ) : (
                <><div className="v muted">—</div><div className="s">לא נרשם סבב</div></>
              )}
            </div>
            <div className="cell">
              <div className="k"><Ic p={IC.clock} /> הסבב הבא</div>
              {nextAt && etaMin !== null ? (
                <>
                  <div className="v">{syncOn === false ? 'מושהה' : etaMin <= 0 ? 'עכשיו' : etaMin < 60 ? `בעוד ${etaMin} דק׳` : fmtClock(summary?.next_pass_at)}</div>
                  <div className="s"><span className="num">{fmtClock(summary?.next_pass_at)}</span><span>כל {summary?.cadence_min ?? SCHEDULER_MIN} דק׳</span></div>
                </>
              ) : (
                <><div className="v muted">—</div><div className="s">כל {summary?.cadence_min ?? SCHEDULER_MIN} דק׳ · המועד לא נקרא</div></>
              )}
            </div>
          </div>
        </>
      )}

      {!loading && !registry.length && !err && (
        <div className="callout">אין מקורות סנכרון עדיין. <button className="link" onClick={() => setP({ new: '1' })}>הוסיפו את הראשון</button>.</div>
      )}

      <div className="pipes">
        {registry.map((e) => (
          <PipeCard key={e.name} entry={e} busy={busy} conns={conns} n8nBase={n8nBase}
                    onRun={() => runOne(e.name)} onRetry={() => retry(e)} onToggle={() => toggle(e)}
                    onEdit={() => setP({ edit: e.name, new: null })} onDelete={() => remove(e)}
                    onItems={(status, reason) => setP({ items: e.name, status: status || null, reason: reason || null })} />
        ))}
      </div>

      {(creating || editing) && (
        <SyncEditor
          key={editing ? editing.name : 'new'}
          existing={editing}
          takenNames={registry.map((r) => r.name)}
          onClose={() => setP({ edit: null, new: null })}
          onSaved={(summaryText) => { push('ok', summaryText); load(); }}
        />
      )}
      {editName && !editing && !loading && (
        <div className="callout warn">
          המקור <span className="mono">{editName}</span> שבכתובת אינו ברשם.{' '}
          <button className="link" onClick={closeOverlays}>סגור</button>
        </div>
      )}
      {itemsEntry && (
        <ItemsDrawer
          entry={itemsEntry}
          status={itemsStatus}
          reason={itemsReason}
          onStatus={(s, reason) => setP({ status: s || null, reason: reason || null })}
          onClose={() => setP({ items: null, status: null, reason: null })}
          docsLink={(id) => link(`/documents/${encodeURIComponent(id)}`)}
        />
      )}
      {reconcileOpen && (
        <ReconcileModal
          entries={registry}
          initial={reconcileName || ''}
          onPick={(name) => setP({ reconcile: name })}
          onClose={() => setP({ reconcile: null })}
        />
      )}
    </div>
  );
}
