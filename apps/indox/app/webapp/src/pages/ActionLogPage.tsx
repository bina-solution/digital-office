import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  ActionClass,
  ActionDocResult,
  ActionEntry,
  ActionLogResult,
  api,
} from '../api';
import DataGrid, { GridColumn, GridFilterValue, GridRow, GridState, Ic, useToasts } from '../components/DataGrid';
import { useConfirm } from '../components/ConfirmModal';
import { IC } from '../icons';
import WindowPicker, { WIN_KEY, isWindow, saveWin, winLabel } from '../components/WindowPicker';
import { useInstances, useInstanceLink, useInstanceParam } from '../instancesContext';
import { statusKind, statusLabel } from '../vocab';

/**
 * יומן פעולות — THE PIPELINE'S PROGRESS TIMELINE, as a view of its own.
 *
 * Every other screen in INDOX shows documents in a STATE. This one shows the ACTS: every stamp
 * every n8n node appended to a document's ACTION_LOG, merged across documents, newest first.
 * It is the answer to "is it working right now, and on what" — measured on the live table at
 * ~6,300 actions an hour, 151,626 in a day, ~430,000 all-time.
 *
 * WHAT DECIDES THE SHAPE OF THIS PAGE
 *
 * 1. IT IS BIG, SO THE SERVER OWNS THE QUERY. DataGrid runs in `mode="server"`: it holds one
 *    page and emits page/size/search/sort/filters through `onState`, and this page turns that
 *    into `GET /dashboard/actions`. Nothing here filters or sorts a loaded array — a client-side
 *    sort of 100 rows out of 151,626 would look, from inside the page, exactly like a real one.
 *
 * 2. THE NUMBERS MUST BE CHECKABLE. `window_total` (every action in the window), `retained`
 *    (how many are pageable) and `matched` (how many survive the filters) are three different
 *    facts and are printed as three different facts. When the window is wider than the
 *    retention cap the header says so instead of letting a pager stop quietly at 200,000.
 *
 * 3. THE SOURCE ITSELF IS LOSSY, AND THAT IS NOT OURS TO HIDE. `incdoc_action_log_append`
 *    middle-trims any log past 6,000 characters, so the MIDDLE of a busy document's history is
 *    gone from the column before anyone reads it. The drill-down says so per document; the
 *    header says so for the view.
 */

const POLL_MS_NARROW = 15000;
const POLL_MS_WIDE = 60000;
const NARROW_WINDOWS = ['15m', '30m', '1h'];
const DEFAULT_PAGE = 100;

/**
 * THE OPENING WINDOW IS `today`, NEVER `all`.
 *
 * `all` is not "a wider view of the same thing" — it is a different order of work: the server
 * re-reads every dispatch row in the table before it can print a single number. Measured against
 * the live BFF, uncached, 2026-08-23:
 *
 *     win=today  6.67s   35,867 rows   rows_capped=false
 *     win=all   25.88s  250,000 rows   rows_capped=TRUE
 *
 * So the wide window costs four times the wait AND comes back capped — the `250,000` it prints is
 * the ceiling it stopped at, not a count, which is exactly what the `סריקה חלקית` badge means. It
 * is also within seconds of this client's own 30s abort, so on a busier table the default view of
 * this page would start failing on a perfectly healthy stack. `all` is therefore something you ASK
 * for here — by clicking it, or by arriving on a `?win=all` link — never something the page
 * assumes on your behalf.
 *
 * A window chosen anywhere in the app (the shared `win` key, which לוח בקרה also writes) is still
 * honoured; only `all` is substituted, and the substitution is stated on screen rather than done
 * quietly. Clicking `הכל` here writes it to the URL, so a reload keeps it.
 */
const DEFAULT_WIN = 'today';

/* ── the two incident filters ────────────────────────────────────────────────────────────────
   Both are properties of the DISPATCH BRACKET, not of the action: the router writes one row at
   Log Action Start and upserts ENDED_AT at Log Action End, so what a row's duration says is how
   long the bracket was open — which is a different fact from how long the work took whenever the
   execution did not survive to close it.

     פתוחות   ENDED_AT is still null N minutes after the start. In flight, or the execution died
              between the brackets and nothing will ever close this row.
     נסגרו בכפייה  a duration of 65 minutes or more. Measured on the live table (2026-08-23):
              120 rows land inside 65.1–65.2 minutes — a bulk close on a fixed cadence, not work
              that happened to take an hour — and 56,146 more sit between 4.5 and 94 HOURS. That
              is 18% of 308,956 rows. A row like that is the fingerprint of a killed router
              execution whose bracket was closed later; reading it as "this action took four
              hours" is the misreading this filter exists to end. */
const REAPED_MIN = 65;
const OPEN_MIN_DEFAULT = 10;

/** Bound on the incident scan. The endpoint has no server-side filter for either state (see
 *  `_ACTION_SORT_KEYS` — duration is not even sortable), so the page reads real pages of the SAME
 *  server query and filters them here. Two ends, not one: an over-due open bracket is at the OLD
 *  end of the window, a bracket that just went over the line is at the NEW end, and a newest-first
 *  scan would only ever find the second kind. When the two ends meet, the scan is COMPLETE and the
 *  panel says so instead of hedging. */
const SCAN_END = 2500;
const SCAN_PAGE = 1000; // the endpoint's own per-request ceiling

/** What one incident scan actually looked at — carried beside its rows so the panel states its
 *  own coverage instead of presenting a bounded read as a census. */
interface ScanResult {
  lens: 'open' | 'reaped';
  minutes: number;
  rows: ActionEntry[];
  /** dispatch rows READ (both ends, de-duplicated) */
  read: number;
  /** every dispatch in the window, per the server */
  windowTotal: number;
  /** the two ends met — this scan saw the whole window and the count is exact */
  complete: boolean;
  at: Date;
}

/** Newest-first identity of one dispatch bracket. (doc, action, execution) is the log's own
 *  primary key; `ts` joins the two scan ends without double-counting their overlap. */
const rowKeyOf = (r: ActionEntry) => `${r.ts}:${r.id}:${r.label}:${r.exec ?? ''}`;
/** Bound on the CSV export. The window can hold hundreds of thousands of actions; an export
 *  button that silently hands over the first page would be worse than none, and one that tries
 *  to stream 430,000 rows through 860 round trips would hang the tab. So it takes the newest
 *  `EXPORT_MAX` matching actions, and says exactly that before it starts. */
const EXPORT_MAX = 5000;
const EXPORT_PAGE = 500; // the endpoint's own per-request ceiling

const he = (n: number) => n.toLocaleString('he-IL');

const CLASSES: { id: ActionClass; he: string; pill: 'ok' | 'warn' | 'muted'; hint: string }[] = [
  { id: 'progress', he: 'התקדמות', pill: 'ok',
    hint: 'פעולה שקידמה את המסמך — חילוץ, עדכון שדה, קביעת סטטוס' },
  { id: 'blocked', he: 'נחסם', pill: 'warn',
    hint: 'מסלול שלא רץ כי מסלול אחר החזיק את הנעילה — עומס, לא תקלה' },
  { id: 'no_action', he: 'ללא פעולה', pill: 'muted',
    hint: 'מכונת המצבים בדקה והחליטה שאין מה לעשות כרגע' },
];
const CLASS_HE: Record<string, string> = Object.fromEntries(CLASSES.map((c) => [c.id, c.he]));

const fmtClock = (ts: number) =>
  new Date(ts).toLocaleTimeString('he-IL', { hour12: false });
const fmtDay = (ts: number) =>
  new Date(ts).toLocaleDateString('he-IL', { day: '2-digit', month: '2-digit' });
const sameDayAsNow = (ts: number) => {
  const a = new Date(ts);
  const b = new Date();
  return (
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
  );
};

/** A gap between two actions, in the shortest honest unit. The single most useful number in a
 *  per-document timeline: it is where the waiting actually happened. */
function fmtGap(ms: number): string {
  if (ms < 1000) return `+${ms} מ״ש`;
  const s = Math.round(ms / 1000);
  if (s < 90) return `+${s} שנ׳`;
  const m = Math.round(s / 60);
  if (m < 90) return `+${m} דק׳`;
  const h = Math.floor(m / 60);
  if (h < 36) return `+${h}ש ${m % 60}ד`;
  return `+${Math.round(h / 24)} ימים`;         // (36 hours and up: rounded it is never «+1 ימים»)
}

/* ── the drill-down: ONE document's whole history, oldest first ───────────────────────────────
   A merged timeline answers "what is the pipeline doing". It cannot answer "why is THIS document
   stuck", because that document's own steps are scattered through tens of thousands of rows
   belonging to everything else. This drawer is that second question: the same stamps, one
   document, in order, with the WAIT between each step — which is where the answer usually is. */
function ActionDocDrawer({ docId, onClose }: { docId: string; onClose: () => void }) {
  const { active } = useInstances();
  /* `active` is the REPO — it is what `api.patchDocument` takes. The INSTANCE is what document
     LINKS need; passing `active` to them produced /i/incoming-documents-main/documents/<id>. */
  const instance = useInstanceParam();
  const link = useInstanceLink();
  const [d, setD] = useState<ActionDocResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let dead = false;
    setD(null);
    setErr(null);
    api
      .dashboardActionsDocument(docId)
      .then((r) => {
        if (!dead) setD(r);
      })
      .catch((e: unknown) => {
        if (!dead) setErr(e instanceof Error ? e.message : String(e));
      });
    return () => {
      dead = true;
    };
  }, [docId]);

  /* Keyboard: focus lands INSIDE the drawer on open (so Tab walks the drawer, not the grid
     behind it) and Escape closes. Both are what a keyboard user expects of a modal surface, and
     neither happens by itself. */
  useEffect(() => {
    panelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const rows = d?.rows || [];
  const span =
    d?.first_ts && d?.last_ts && d.last_ts > d.first_ts ? d.last_ts - d.first_ts : 0;

  return (
    <div className="drawer-ov" role="dialog" aria-modal="true" aria-label="היסטוריית פעולות של מסמך">
      <div className="scrim" onClick={onClose} />
      <div className="drawer atl-drawer" ref={panelRef} tabIndex={-1}>
        <div className="drawer-h">
          <div style={{ minWidth: 0 }}>
            <h3>היסטוריית פעולות</h3>
            <div className="muted small mono num" style={{ direction: 'ltr' }}>{docId}</div>
          </div>
          <button className="link" onClick={onClose} title="סגירה (Esc)">
            <Ic p={IC.x} /> סגור
          </button>
        </div>

        <div className="drawer-body">
          {err && <div className="callout bad">{err}</div>}
          {!d && !err && <div className="spin">טוען היסטוריה…</div>}

          {d && d.reachable === false && (
            <div className="callout bad">{d.error || 'המקור אינו זמין'}</div>
          )}
          {d && d.reachable !== false && d.found === false && (
            <div className="callout warn">
              <b>המסמך לא נמצא.</b> ייתכן שנמחק או שהוא שייך למופע אחר.
            </div>
          )}

          {d && d.found && (
            <>
              <div className="atl-doc">
                <div className="atl-doc-name">{d.name || <span className="muted">ללא שם</span>}</div>
                <div className="atl-doc-meta">
                  {d.status && (
                    <span className={`pill ${statusKind(d.status)}`} title={d.status}>
                      {statusLabel(d.status)}
                    </span>
                  )}
                  <span className="muted small">
                    ‏{he(d.total ?? 0)} פעולות
                    {span > 0 ? ` · לאורך ${fmtGap(span).replace('+', '')}` : ''}
                  </span>
                  {instance && (
                    <Link className="link" to={link(`/documents/${encodeURIComponent(docId)}`)} title="מסך המסמך">
                      פתח את המסמך <Ic p={IC.arrowLeft} />
                    </Link>
                  )}
                </div>
                <div className="atl-doc-classes">
                  {CLASSES.map((c) => (
                    <span key={c.id} className={`pill ${c.pill}`} title={c.hint}>
                      {c.he} {he(d.classes?.[c.id] ?? 0)}
                    </span>
                  ))}
                </div>
              </div>

              {/* THE HONESTY LINES. Two independent ways this history can be less than whole,
                  and neither is ours to hide:
                    1. the 6,000-char middle-trim in the DB trigger — the gap it leaves is in the
                       MIDDLE, exactly where a "why is this stuck" answer would be;
                    2. entries written with no action name, which can be counted but not placed
                       on a timeline that has an action column. */}
              {d.trimmed && (
                <div className="callout warn">
                  <b>ההיסטוריה חלקית.</b> יומן הפעולות של המסמך הזה חרג מ-6,000 תווים, ומנגנון
                  הכתיבה במסד הנתונים גזם את האמצע. הפעולות המוקדמות והאחרונות שמורות — מה שביניהן
                  אינו קיים במקור, ולא ניתן לשחזר אותו מכאן.
                </div>
              )}
              {!!d.unparsed && (
                <div className="callout">
                  ‏{he(d.unparsed)} רשומות ביומן של המסמך הזה נכתבו בלי שם פעולה, ולכן אינן מוצגות
                  כשלבים בציר הזמן.
                </div>
              )}

              {rows.length === 0 && (
                <div className="callout warn">
                  <b>לא ניתן להציג ציר זמן למסמך הזה.</b>{' '}
                  {d.log_chars
                    ? 'יומן הפעולות שלו אינו ריק, אבל הרשומות בו נכתבו ללא חותמת זמן — למשל ' +
                      '"‏Extract Base Doc FAILED, 1128240" — ולכן אין להן מקום על ציר זמן. ' +
                      '13 מסמכים בטבלה במצב הזה.'
                    : 'לא נרשמה עליו אף פעולה.'}
                </div>
              )}

              <ol className="atl-list">
                {rows.map((r, i) => {
                  const prev = i > 0 ? rows[i - 1] : null;
                  const gap = prev ? r.ts - prev.ts : 0;
                  return (
                    <li key={`${r.ts}:${i}`} className={`atl-step cls-${r.cls}`}>
                      <span className="atl-dot" aria-hidden="true" />
                      <div className="atl-step-body">
                        <div className="atl-step-top">
                          <span className="mono num atl-step-time" title={new Date(r.ts).toLocaleString('he-IL')}>
                            {fmtDay(r.ts)} {fmtClock(r.ts)}
                          </span>
                          {/* the WAIT is the finding, so it is rendered as loudly as the step */}
                          {gap > 0 && <span className="atl-gap num">{fmtGap(gap)}</span>}
                          {r.exec && (
                            <span className="muted small mono num" title="מזהה הרצה ב-n8n">
                              #{r.exec}
                            </span>
                          )}
                          {/* an ISO-shaped raw stamp means a one-off repair script wrote this
                              step, not an n8n node — worth seeing when reading a history that
                              looks unlike the pipeline's usual shape */}
                          {r.ts_raw && !/^\d+$/.test(r.ts_raw) && (
                            <span className="tag" title={`נכתב כ-ISO: ${r.ts_raw}`}>
                              סקריפט
                            </span>
                          )}
                        </div>
                        <div className="atl-step-label">{r.label}</div>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** The action log's own view state. Deliberately narrower than the grid's `GridState`:
 *  a 1-based page and ONE sort, which is exactly what `/dashboard/actions` accepts. */
interface LogViewState {
  page: number;
  pageSize: number | null;
  search: string;
  sort: { key: string; dir: 'asc' | 'desc' } | null;
  filters?: Record<string, GridFilterValue> | null;
}

export default function ActionLogPage() {
  const { active } = useInstances();
  /* `active` is the REPO — it is what `api.patchDocument` takes. The INSTANCE is what document
     LINKS need; passing `active` to them produced /i/incoming-documents-main/documents/<id>. */
  const instance = useInstanceParam();
  const link = useInstanceLink();
  const [params, setParams] = useSearchParams();

  /* THE WINDOW LIVES IN THE URL. This is a standalone view now, so a link to it has to be able
     to carry what it is showing — "the last hour of actions" is the whole content of the page,
     and a link that dropped it would open on something else. localStorage is the fallback (and
     is written on every change), which is what keeps the window shared with לוח בקרה: moving
     between the two tabs keeps the range you were already reading. URL wins when present. */
  const urlWin = params.get('win');
  /* read ONCE per visit: the shared key is written by this page's own picker, and re-reading it
     every render would make the substitution below flicker back the moment `הכל` was saved. */
  const [storedWin] = useState<string | null>(() => {
    try {
      return localStorage.getItem(WIN_KEY);
    } catch {
      return null; // private mode — the default below is the whole fallback
    }
  });
  const win = isWindow(urlWin)
    ? (urlWin as string)
    : isWindow(storedWin) && storedWin !== 'all'
      ? (storedWin as string)
      : DEFAULT_WIN;
  /** the shared window said `הכל` and this page opened narrower on purpose — stated, not silent */
  const winSubstituted = !isWindow(urlWin) && storedWin === 'all';
  const setWin = useCallback(
    (id: string) => {
      saveWin(id);
      setParams(
        (p) => {
          const next = new URLSearchParams(p);
          next.set('win', id);
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  /* The class filter is the page's own, not the grid's: it needs the SERVER's exact per-class
     counts beside each option (the grid computes chip counts from loaded rows, which under
     server mode is one page of 100), and it is the one filter an operator toggles constantly.
     It lives in the URL for the same reason the window does. */
  const clsSel = useMemo(
    () => (params.get('cls') || '').split(',').filter(Boolean),
    [params],
  );

  /* duplicate-pair filter (owner order): the same (doc, action) in more than one execution
     should never happen — the badge carries the server's count on every response, turns
     red the moment it is positive, and clicking it shows exactly those rows, grouped. */
  const dupOnly = params.get('dup') === '1';
  const setDupOnly = useCallback(
    (v: boolean) => {
      setParams(
        (p) => {
          const q = new URLSearchParams(p);
          if (v) q.set('dup', '1');
          else q.delete('dup');
          return q;
        },
        { replace: true },
      );
    },
    [setParams],
  );
  const [d, setD] = useState<ActionLogResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [live, setLive] = useState(true);
  const [openDoc, setOpenDoc] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const navigate = useNavigate();
  const { ask, confirmUI } = useConfirm();
  const { push } = useToasts();

  /* the incident lens: 'open' = brackets still open past `openMin` minutes, 'reaped' = brackets
     closed at/after REAPED_MIN. null = the normal server-paged timeline. */
  const [focus, setFocus] = useState<null | 'open' | 'reaped'>(null);
  const [openMin, setOpenMin] = useState(OPEN_MIN_DEFAULT);
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanErr, setScanErr] = useState<string | null>(null);

  /* The grid's own query state (server mode), in THIS page's shape rather than the grid's.
     Ten call sites below read `page`/`sort`, so the grid's `GridState` is adapted once at
     `onStateChange` instead of being threaded through all of them — a 1-based page and a
     single sort are what the log's query actually takes. */
  const [gs, setGs] = useState<LogViewState>({
    page: 1,
    pageSize: DEFAULT_PAGE,
    search: '',
    sort: null,
  });
  const reqRef = useRef(0);

  /** the LABEL filter is the grid's — a multi-select on its own column header, where a user
   *  looking at an action name would reach for it. Pulled out of the grid's state so the
   *  request can carry it; without this the popover would apply, show its chip, and change
   *  nothing (the failure DocumentBrowserPage's own translation comment records). */
  const labelSel = useMemo(() => {
    const f = gs.filters?.label;
    return f && f.kind === 'enum' ? f.values : [];
  }, [gs.filters]);

  const pageSize = gs.pageSize ?? DEFAULT_PAGE;
  const page = gs.page ?? 1;

  const load = useCallback(async () => {
    const myReq = ++reqRef.current;
    setLoading(true);
    try {
      const r = await api.dashboardActions({
        win,
        limit: pageSize,
        offset: (page - 1) * pageSize,
        cls: clsSel,
        label: labelSel,
        q: gs.search || undefined,
        sort: gs.sort?.key,
        dir: gs.sort?.dir,
        dup: dupOnly || undefined,
      });
      if (myReq !== reqRef.current) return; // stale response — a newer query is in flight
      setD(r);
      setErr(r.reachable === false ? r.error || 'יומן הפעולות אינו זמין' : null);
      setUpdated(new Date());
    } catch (e: unknown) {
      if (myReq !== reqRef.current) return;
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      if (myReq === reqRef.current) setLoading(false);
    }
  }, [win, pageSize, page, clsSel, labelSel, gs.search, gs.sort, dupOnly]);

  useEffect(() => {
    load();
  }, [load]);

  /* ── THE INCIDENT SCAN ─────────────────────────────────────────────────────────────────────
     `GET /dashboard/actions` can filter by class, by label and by free text, and can sort by six
     keys — none of which is the duration or the open/closed state (see `_ACTION_SORT_KEYS`
     server-side). So the two states that actually matter during an incident cannot be asked for.

     They are found here instead, by reading REAL PAGES of the same server query and testing each
     row. That is a bounded read, and the panel says exactly how bounded: `read` of `windowTotal`.
     What it must never do is print a count as if it were the window's — a filter that quietly
     measured the loaded page would look, from inside this screen, precisely like a real one, which
     is the failure this file's header comment already names for sorting.

     Two ends, because the two lenses live at opposite ends of the window: a bracket that has been
     open for hours is among the OLDEST rows, one that just crossed the line is among the newest.
     When the ends meet (a narrow window, or a quiet one) the scan is complete and says so — which
     is also the page's advice when it is not: narrow the window and the answer becomes exact. */
  const runScan = useCallback(
    async (lens: 'open' | 'reaped', minutes: number) => {
      setScanning(true);
      setScanErr(null);
      try {
        const base = {
          win,
          cls: clsSel,
          label: labelSel,
          q: gs.search || undefined,
          dup: dupOnly || undefined,
        };
        const seen = new Map<string, ActionEntry>();
        let windowTotal = 0;
        let exhausted = false;
        for (const dir of ['desc', 'asc'] as const) {
          for (let off = 0; off < SCAN_END; off += SCAN_PAGE) {
            const r = await api.dashboardActions({
              ...base,
              limit: Math.min(SCAN_PAGE, SCAN_END - off),
              offset: off,
              sort: 'ts',
              dir,
            });
            windowTotal = r.matched ?? r.retained ?? windowTotal;
            const batch = r.rows || [];
            for (const x of batch) seen.set(rowKeyOf(x), x);
            // fewer rows than asked for ⇒ this end reached the other one
            if (batch.length < Math.min(SCAN_PAGE, SCAN_END - off)) {
              exhausted = true;
              break;
            }
          }
          // one end already covered everything — the second pass would re-read the same rows
          if (exhausted && seen.size >= windowTotal) break;
        }
        const now = Date.now();
        const all = [...seen.values()];
        const rows = all
          .filter((r) =>
            lens === 'open'
              ? r.done === false && now - r.ts >= minutes * 60_000
              : r.done === true && (r.dur_s ?? 0) >= REAPED_MIN * 60,
          )
          .sort((a, b) =>
            lens === 'open' ? a.ts - b.ts : (b.dur_s ?? 0) - (a.dur_s ?? 0),
          );
        setScan({
          lens,
          minutes,
          rows,
          read: all.length,
          windowTotal,
          complete: all.length >= windowTotal,
          at: new Date(),
        });
      } catch (e: unknown) {
        setScanErr(e instanceof Error ? e.message : String(e));
        setScan(null);
      } finally {
        setScanning(false);
      }
    },
    [win, clsSel, labelSel, gs.search, dupOnly],
  );

  /* re-scan when the lens or the query underneath it changes; drop the result when the lens is
     turned off, so a stale finding can never be read as a current one */
  useEffect(() => {
    if (!focus) {
      setScan(null);
      setScanErr(null);
      return;
    }
    runScan(focus, openMin);
  }, [focus, openMin, runScan]);

  /* AUTO-REFRESH ONLY ON PAGE 1. A timeline that reorders under you while you are reading page 4
     is worse than a stale one: the row you were looking at moves. The interval follows what the
     server can actually recompute — a narrow window re-scans ~1,300 documents (cached 10s), the
     wide ones re-scan the whole 19.7 MB table (cached 60s), so polling those faster would only
     queue round trips through the console's single-threaded proxy to be handed the same
     snapshot back. */
  /* An incident lens also pauses it: those rows come from a bounded scan the operator asked for
     by name, and silently replacing a finding under the cursor with a newer one would make a
     stable page look unstable at exactly the wrong moment. The scan is re-run on demand. */
  useEffect(() => {
    if (!live || page !== 1 || focus) return;
    const id = setInterval(
      () => {
        if (!document.hidden) load();
      },
      NARROW_WINDOWS.includes(win) ? POLL_MS_NARROW : POLL_MS_WIDE,
    );
    return () => clearInterval(id);
  }, [live, page, load, win, focus]);

  /* PAGE-LEVEL KEYBOARD. Deliberately single keys with no modifier and deliberately inert while
     you are typing — the grid's own search box and the filter popovers are inputs, and a
     shortcut that fires mid-word is a bug, not a feature. Escape is handled by the drawer
     itself while it is open. */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      const tag = (t?.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || t?.isContentEditable) return;
      if (e.key === 'r' || e.key === 'ר') {
        e.preventDefault();
        load();
        if (focus) runScan(focus, openMin);
      } else if (e.key === 'p' || e.key === 'פ') {
        e.preventDefault();
        setLive((v) => !v);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [load, focus, openMin, runScan]);

  /* ── MEASURED, OR NOT SHOWN ────────────────────────────────────────────────────────────────
     The header used to print `0 פעולות בטווח · נסרקו 0 מסמכים` for the ten seconds a wide scan
     takes, then flip to 250,000. Those zeros were not a loading state — they were an assertion,
     in the same words and the same weight as the real answer, and the one moment an operator
     looks hardest at this line is while it is still lying.

     The server echoes the window it actually applied, so "do these numbers describe what I am
     asking about" is checkable rather than assumed: until the echo matches the current window
     every count here renders `—`. */
  const answered = Boolean(d) && (d?.win ?? 'all') === win;
  const matched = d?.matched ?? 0;
  const windowTotal = d?.window_total ?? 0;
  const retained = d?.retained ?? 0;
  const filtered = Boolean(clsSel.length || labelSel.length || gs.search);
  /** a count, or an explicit "not measured yet" — never a placeholder zero */
  const meas = (v: number | null | undefined) => (answered && v != null ? he(v) : '—');

  /* WHICH ROW SET THE GRID IS SHOWING. Normally the server's page. Under an incident lens it is
     the scan's own rows — a set this page holds whole — so THERE the sort and the paging are
     local, applied to everything found rather than to a hundred rows out of it. The two never mix:
     server paging on a client-held set is exactly how a partial answer starts looking total. */
  const lensRows = useMemo(() => {
    if (!focus || !scan) return null;
    const s = gs.sort;
    if (!s) return scan.rows;
    const dir = s.dir === 'asc' ? 1 : -1;
    const val = (r: ActionEntry): string | number =>
      s.key === 'ts' ? r.ts
        : s.key === 'dur_s' ? (r.dur_s ?? -1)
          : s.key === 'exec' ? (r.exec && /^\d+$/.test(r.exec) ? Number(r.exec) : -1)
            : String((r as unknown as Record<string, unknown>)[s.key] ?? '');
    return [...scan.rows].sort((a, b) => {
      const x = val(a);
      const y = val(b);
      if (typeof x === 'number' && typeof y === 'number') return (x - y) * dir;
      return String(x).localeCompare(String(y)) * dir;
    });
  }, [focus, scan, gs.sort]);

  const pageRows: ActionEntry[] = useMemo(() => {
    if (lensRows) return lensRows.slice((page - 1) * pageSize, page * pageSize);
    // a lens is on but its scan has not landed: EMPTY, never the unfiltered timeline. Showing
    // the normal rows under a lens banner would attribute them to the lens.
    if (focus) return [];
    return d?.rows || [];
  }, [lensRows, d, page, pageSize, focus]);

  /* rows → the grid's shape. `_k` is a synthetic row key: two stamps CAN share a millisecond,
     a document and a label (a node acting on a batch), so nothing here may key off the data. */
  const rows = useMemo(
    () =>
      pageRows.map((r, i) => ({
        _k: `${r.ts}:${r.id}:${i}`,
        ts: r.ts,
        cls: r.cls,
        label: r.label,
        id: r.id,
        name: r.name,
        status: r.status,
        exec: r.exec || '',
        // the משך column reads these two; dropping them here rendered it "—" forever
        dur_s: r.dur_s ?? null,
        done: r.done ?? null,
        // the two row VERBS. Empty values on purpose: the cells render a button rather than
        // data, and each button stops the click from also reaching the row.
        _open: '',
        _retry: '',
      })),
    [pageRows],
  );

  /* The label vocabulary the SERVER counted for this window — so the filter offers exactly the
     actions that actually happened in it, with how many, and never a hard-coded list that goes
     stale the next time a workflow gains a node. */
  const labelOptions = useMemo(() => (d?.labels || []).map((l) => l.label), [d]);
  const labelOptionLabels = useMemo(
    () =>
      Object.fromEntries((d?.labels || []).map((l) => [l.label, `${l.label} · ${he(l.count)}`])),
    [d],
  );

  /** late-bound handle to `restartDoc`, which is defined further down: the verb column needs
   *  it, and a ref keeps the columns memo out of that callback's identity churn. */
  const restartDocRef = useRef<((row: { id: string; name?: string; label?: string; status?: string }) => void) | null>(
    null,
  );

  const columns: GridColumn[] = useMemo(
    () => [
      {
        key: 'ts',
        header: 'זמן',
        width: 165,
        sortable: true,
        // the WINDOW is this view's time filter, and it is a server-side one. A second,
        // client-shaped date filter on the same axis would be a second answer to one question.
        filter: false,
        render: (v: unknown) => {
          const ts = Number(v);
          if (!Number.isFinite(ts)) return <span className="dg-null">—</span>;
          return (
            <span className="mono num" title={new Date(ts).toLocaleString('he-IL')}>
              {!sameDayAsNow(ts) && <span className="atl-date">{fmtDay(ts)} </span>}
              {fmtClock(ts)}
            </span>
          );
        },
      },
      /* the 'cls'/סוג column was REMOVED (owner order 2026-08-16): in the dispatch table every
         row is a real dispatch, so the old three-way classification is constant 'progress' and
         says nothing. The drill-down drawer keeps its classes — since 2026-08-21 its source
         still has real blocked/no_action stamps. */
      {
        key: 'label',
        header: 'פעולה',
        width: 320,
        sortable: true,
        // 30 labels in a 15-minute window, 155 over the table — a corpus, not a menu.
        // DataGrid's enum popover carries its own search box, so the corpus stays navigable.
        options: labelOptions.map((v) => ({ value: v, label: labelOptionLabels[v] ?? v })),
        /* RAW, on purpose: this is the vocabulary you search n8n with, and a translation table
           for 155 machine-written labels that grows with every new node is one nobody can keep
           honest. The Hebrew lives in the סוג column beside it. */
        render: (v: unknown) => <span className="mono atl-label">{String(v ?? '')}</span>,
      },
      {
        key: 'id',
        header: 'מזהה שורה',
        width: 185,
        sortable: true,
        filter: false,
        render: (v: unknown) =>
          v ? <span className="link mono num">{String(v)}</span> : <span className="dg-null">—</span>,
      },
      { key: 'name', header: 'מסמך', width: 260, sortable: true, filter: false },
      {
        key: 'status',
        header: 'סטטוס נוכחי',
        width: 130,
        sortable: true,
        filter: false,
        render: (v: unknown) =>
          v ? <span className={`pill ${statusKind(v)}`}>{statusLabel(v)}</span> : <span className="dg-null">—</span>,
      },
      {
        key: 'exec',
        header: 'הרצה n8n',
        width: 110,
        sortable: true,
        filter: false,
        render: (v: unknown) =>
          v ? <span className="mono num muted">{String(v)}</span> : <span className="dg-null">—</span>,
      },
      {
        // start→end duration + completion state, straight off the pg bracket row:
        // ✓ + seconds = the End upsert landed; "רץ…" = started, no end yet (in flight or
        // the execution died mid-dispatch); "—" = legacy ACTION_LOG source (no brackets).
        key: 'dur_s',
        header: 'משך',
        width: 90,
        sortable: false,
        filter: false,
        render: (v: unknown, row: GridRow) => {
          if (row.done === true) {
            const secs = Number(v);
            // a bracket that stayed open 65 minutes or more was closed in bulk, not by the work
            // finishing — flagged in the cell itself, because this column is where the wrong
            // reading ("that action took four hours") is made
            const reaped = Number.isFinite(secs) && secs >= REAPED_MIN * 60;
            const txt = Number.isFinite(secs)
              ? secs >= 3600
                ? `${(secs / 3600).toFixed(1)}ש`
                : secs >= 90
                  ? `${Math.round(secs / 60)} דק׳`
                  : `${secs}s`
              : '?';
            return reaped ? (
              <span
                className="mono num"
                style={{ color: 'var(--red)', display: 'inline-flex', alignItems: 'center', gap: 4 }}
                title={`נסגר ${String(v)} שניות אחרי הפתיחה — סגירה בכפייה, לא סיום עבודה`}
              >
                <Ic p={IC.flag} /> {txt}
              </span>
            ) : (
              <span className="mono num" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }} title="הסוגריים נסגרו — הפעולה הסתיימה">
                <Ic p={IC.check} /> {txt}
              </span>
            );
          }
          return row.done === false ? (
            <span className="muted">רץ…</span>
          ) : (
            <span className="dg-null">—</span>
          );
        },
      },
      /* ── ROW VERBS ─────────────────────────────────────────────────────────────────────────
         Reading a row of this log and being unable to act on the document it names was the gap —
         the timeline could show a document parked for an hour and offer nothing but a drawer
         about it. Each verb is a real <button> in its own cell, and stops the click from also
         reaching the row: previously the two were told apart by WHICH COLUMN the click landed
         on, which made the affordance invisible to the keyboard and to a screen reader. */
      {
        key: '_open',
        header: 'מסמך',
        width: 92,
        sortable: false,
        filter: false,
        text: () => 'פתח',
        render: (_v: unknown, row: GridRow) => (
          <button
            type="button"
            className="link dg-verb"
            onClick={(e) => {
              e.stopPropagation();
              const id = String(row.id ?? '');
              if (id && instance) {
                navigate(link(`/documents/${encodeURIComponent(id)}`));
              }
            }}
            title="פתיחת מסך המסמך"
          >
            פתח <Ic p={IC.arrowLeft} />
          </button>
        ),
      },
      {
        key: '_retry',
        header: 'הרצה מחדש',
        width: 140,
        sortable: false,
        filter: false,
        text: () => 'בקש עיבוד מחדש',
        render: (_v: unknown, row: GridRow) => (
          <button
            type="button"
            className="link dg-verb"
            onClick={(e) => {
              e.stopPropagation();
              const id = String(row.id ?? '');
              if (!id) return;
              restartDocRef.current?.({
                id,
                name: String(row.name ?? ''),
                label: String(row.label ?? ''),
                status: String(row.status ?? ''),
              });
            }}
          >
            בקש עיבוד מחדש
          </button>
        ),
      },
    ],
    [labelOptions, labelOptionLabels, instance, link, navigate],
  );

  /* EXPORT — bounded, and it says so before it runs. A grid's built-in export writes the
     rows it holds, which under server mode is the current page; on a view whose header says
     151,626 actions, a file with 100 rows in it is a lie the file cannot correct. So this walks
     the same filtered query server-side up to EXPORT_MAX and writes what it actually got. */
  const exportCsv = useCallback(async () => {
    if (exporting) return;
    const take = Math.min(matched, EXPORT_MAX);
    if (take === 0) return;
    const ok = await ask({
      title: 'ייצוא יומן הפעולות',
      consequence: (
        <>
          ייווצר קובץ CSV עם <b className="num">{he(take)}</b> שיגורים
          {matched > take ? (
            <>
              {' '}— <b className="num">{he(EXPORT_MAX)}</b> החדשים ביותר מתוך{' '}
              <b className="num">{he(matched)}</b> התואמים לסינון הנוכחי
            </>
          ) : (
            ' — כל התואמים לסינון הנוכחי'
          )}
          , בטווח <b>{winLabel(win)}</b>.
        </>
      ),
      facts: [
        { label: 'שורות בקובץ', value: he(take) },
        { label: 'תואמות לסינון', value: he(matched) },
        { label: 'טווח', value: winLabel(win) },
      ],
      unknown:
        matched > take
          ? 'הייצוא חסום בתקרה — מה שמעבר לה אינו בקובץ. לייצוא מלא צמצמו את הטווח או את הסינון.'
          : undefined,
      confirmLabel: 'ייצא',
    });
    if (!ok) return;
    setExporting(true);
    try {
      const out: string[][] = [];
      for (let off = 0; off < take; off += EXPORT_PAGE) {
        const r = await api.dashboardActions({
          win,
          limit: Math.min(EXPORT_PAGE, take - off),
          offset: off,
          cls: clsSel,
          label: labelSel,
          q: gs.search || undefined,
          sort: gs.sort?.key,
          dir: gs.sort?.dir,
        });
        const batch = r.rows || [];
        if (!batch.length) break; // the window moved under us — write what is real
        for (const x of batch) {
          out.push([
            new Date(x.ts).toISOString(),
            String(x.ts),
            CLASS_HE[x.cls] ?? x.cls,
            x.label,
            x.id,
            x.name || '',
            x.status || '',
            x.exec || '',
          ]);
        }
      }
      const esc = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
      const head = ['זמן (ISO)', 'epoch_ms', 'סוג', 'פעולה', 'מזהה שורה', 'מסמך', 'סטטוס', 'הרצה n8n'];
      const csv = [head, ...out].map((r) => r.map(esc).join(',')).join('\n');
      // UTF-8 BOM — so Hebrew opens right in Excel
      const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `action-log-${win}-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
      push('ok', `יוצאו ${he(out.length)} שיגורים לקובץ CSV`);
    } catch (e: unknown) {
      push('bad', `הייצוא נכשל: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setExporting(false);
    }
  }, [exporting, matched, win, clsSel, labelSel, gs.search, gs.sort, ask, push]);

  /* ── ROW VERB: ask the state machine to run this document again ────────────────────────────
     The SAME sanctioned path the document page uses — STATUS=ACTION_RESTART through the BFF's
     PATCH endpoint. There is no "re-dispatch" button anywhere in this product and there must not
     be one: the state machine is the only writer, and ACTION_RESTART is the one signal an
     operator is allowed to raise. What is new here is only the REACH — asking for it from the
     row that shows the document is stuck, instead of copying an id into another screen. */
  const restartDoc = useCallback(
    async (row: { id: string; name?: string; label?: string; status?: string }) => {
      if (!active) return;
      const ok = await ask({
        title: 'בקשת עיבוד מחדש',
        danger: false,
        consequence: (
          <>
            הסטטוס של המסמך ישונה ל־<b className="mono">ACTION_RESTART</b>, ומכונת המצבים תיקח אותו
            במחזור הבא. זו הבקשה היחידה המאושרת להרצה חוזרת — הראוטר לא משוגר ישירות מכאן.
          </>
        ),
        facts: [
          { label: 'מסמך', value: row.name || row.id },
          { label: 'מזהה שורה', value: <span className="mono">{row.id}</span> },
          {
            label: 'סטטוס נוכחי',
            value: row.status ? statusLabel(row.status) : '—',
            kind: row.status ? statusKind(row.status) : 'muted',
          },
          ...(row.label ? [{ label: 'הפעולה בשורה זו', value: row.label }] : []),
        ],
        unknown:
          'הבקשה נרשמת מיד; מתי היא תילקח תלוי במחזור הניקוז. מסך המסמך עוקב אחרי ההרצה בזמן אמת.',
        confirmLabel: 'בקש עיבוד מחדש',
      });
      if (!ok) return;
      try {
        await api.patchDocument(active, row.id, { STATUS: 'ACTION_RESTART' });
        push('ok', `${row.name || row.id} הועבר ל-ACTION_RESTART — ייתפס במחזור הניקוז הבא`);
        load();
      } catch (e: unknown) {
        push('bad', `הבקשה עבור ${row.id} נכשלה: ${e instanceof Error ? e.message : String(e)}`);
      }
    },
    [active, ask, load, push],
  );
  restartDocRef.current = restartDoc;

  /* delete the log rows of the CURRENT window (owner button) — irreversible, so the confirm
     names the window and the row count it is about to remove. */
  const [purging, setPurging] = useState(false);
  const purgeWindow = useCallback(async () => {
    if (purging) return;
    const ok = await ask({
      title: 'מחיקת שורות מיומן השיגורים',
      danger: true,
      consequence: (
        <>
          יימחקו <b className="num">{he(windowTotal)}</b> שורות מטבלת{' '}
          <span className="mono">indox_action_execution_log</span>
          {win === 'all' ? ' — כלומר כל הטבלה' : <> — כל השיגורים בטווח <b>{winLabel(win)}</b></>}.
          המסמכים עצמם לא נוגעים; מה שנמחק הוא העדות למה שרץ עליהם. בלתי הפיך.
        </>
      ),
      facts: [
        {
          label: 'שורות שיימחקו',
          value: d?.rows_capped ? `${he(windowTotal)}+` : he(windowTotal),
          kind: 'bad',
        },
        { label: 'טווח', value: win === 'all' ? 'כל הטבלה' : winLabel(win) },
        { label: 'טבלה', value: <span className="mono">indox_action_execution_log</span> },
      ],
      unknown: !answered
        ? 'המספר שלמעלה עדיין לא נמדד בטווח הזה — המתינו לסיום הטעינה לפני מחיקה.'
        : d?.rows_capped
          ? 'הסריקה נעצרה בתקרת השורות, ולכן המספר שלמעלה הוא רצפה: המחיקה עצמה רצה על הטווח בשרת ותסיר גם את מה שמעבר לתקרה — כלומר יותר שורות ממה שכתוב כאן.'
          : undefined,
      confirmLabel: 'מחק',
    });
    if (!ok) return;
    setPurging(true);
    try {
      const r = await api.purgeActions({
        win,
        tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
      // the result goes to the one notice channel — with the number the server actually deleted
      if (r.ok) push('ok', `נמחקו ${r.deleted != null ? he(r.deleted) : 'כל'} שורות השיגור בטווח ${winLabel(win)}`);
      else push('bad', `המחיקה נכשלה: ${r.error || 'ללא פירוט'}`);
      await load();
    } catch (e) {
      push('bad', `המחיקה נכשלה: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setPurging(false);
    }
  }, [purging, win, windowTotal, load, ask, answered, d?.rows_capped, push]);

  return (
    <div className="page-fill">
      <div className="app-header">
        <div>
          <h1>יומן פעולות</h1>
          {/* THE ONE SENTENCE THAT PREVENTS THE STANDARD MISREADING (source swapped
              2026-08-16, owner order): rows are the Action Router's OWN dispatch brackets —
              `Log Action Start` INSERTs a row and `Log Action End` upserts its ENDED_AT, one row
              per (document · action · execution) in public.indox_action_execution_log. Only real
              dispatches appear here: no no_action verdicts, no BLOCKED stamps. The old
              cumulative-ACTION_LOG parser was retired with that column on 2026-08-21.

              The old sub-line said "written to redis, kept 24 hours". Both halves were wrong: the
              brackets are POSTGRES rows (the redis wording survived an earlier draft), and the
              live table holds 308,956 rows going back to 2026-08-17 — six days, measured
              2026-08-23, not one. */}
          <div className="sub">
            שיגורי פעולות אמיתיים של הראוטר — שורה אחת לכל (מסמך · פעולה · ריצה), נפתחת לפני
            השיגור ונסגרת אחריו. «רץ…» = שיגור שטרם נסגר; משך של{' '}
            {REAPED_MIN} דק׳ ומעלה = סוגריים שנסגרו בכפייה, לא עבודה שארכה שעה.
          </div>
        </div>
        <div className="actions">
          <WindowPicker value={win} onChange={setWin} />
          {winSubstituted && (
            <span
              className="muted small"
              title={
                'הטווח המשותף שנשמר הוא "הכל". במסך הזה "הכל" סורק את כל טבלת השיגורים לפני ' +
                'שמוצג מספר אחד — נמדד חי: 25.9 שניות, ועצירה בתקרת 250,000 שורות (סריקה ' +
                'חלקית), מול 6.7 שניות ו-35,867 שורות מלאות ב"היום". לכן הוא נבחר בלחיצה ' +
                'ולא נפתח מעצמו. לחיצה על "הכל" תפעל כרגיל.'
              }
            >
              <Ic p={IC.info} /> נפתח על {winLabel(DEFAULT_WIN)}
            </span>
          )}
          <button
            className="btn sm danger"
            disabled={purging || !answered || windowTotal === 0}
            onClick={purgeWindow}
            title="מחיקת כל שורות הלוג בטווח הנבחר — אחרי אישור עם מספר השורות; בלתי הפיך"
          >
            {purging ? <span className="spinner" /> : <><Ic p={IC.trash} /> מחק טווח</>}
          </button>
          {updated && (
            <span className="muted small">עודכן {updated.toLocaleTimeString('he-IL')}</span>
          )}
          <button
            className={`live${live ? '' : ' paused'}`}
            onClick={() => setLive((v) => !v)}
            title={
              live
                ? 'רענון אוטומטי פעיל — לחצו להשהיה (P). מושהה ממילא כשלא בעמוד הראשון.'
                : 'רענון אוטומטי מושהה — לחצו להפעלה (P)'
            }
          >
            <span className="beat" />
            {live ? 'חי' : 'מושהה'}
          </button>
        </div>
      </div>

      {err && (
        <div className="callout warn">
          <b>שגיאת רענון.</b> {err}
          {d ? '. מוצג הנתון האחרון.' : ''}
        </div>
      )}

      {/* ── the header line: what this view is showing, and how complete it is ─────────────── */}
      <div className="toolbar atl-bar">
        {/* the class chips were removed with the סוג column (same reason: constant value
            on the dispatch source). clsSel still reads the URL so a legacy ?source=log link
            with ?cls= keeps filtering server-side. In their place: the double-run alarm. */}
        <div className="atl-chips">
          {/* THE DOUBLE-RUN ALARM. It says PAIRS, and a pair is not a row — 31,728 pairs on a
              window holding hundreds of thousands of rows is a different (and much larger) fact
              than 31,728 rows, and the chip used to make the reader guess which. Both numbers
              are on it now, the tooltip says what a pair IS, and clicking shows exactly those
              rows grouped so the claim can be read row by row. */}
          <button
            className={`chip${dupOnly ? ' active' : answered && (d?.dup_pairs ?? 0) > 0 ? ' bad' : ''}`}
            disabled={!answered || ((d?.dup_pairs ?? 0) === 0 && !dupOnly)}
            onClick={() => setDupOnly(!dupOnly)}
            title={
              'כפילות = אותו (מסמך + פעולה) ששוגר ביותר מהרצה אחת אחת בטווח הזה. ' +
              'מזהה ההרצה נמצא במפתח הראשי של טבלת השיגורים, ולכן שורה שנייה לאותו צמד היא ' +
              'הרצה כפולה אמיתית ולא רישום כפול.\n' +
              (answered
                ? `בטווח ${winLabel(win)}: ${he(d?.dup_pairs ?? 0)} צמדים, ${he(d?.dup_rows ?? 0)} שורות.\n`
                : 'עדיין לא נמדד בטווח הזה.\n') +
              'לחיצה מציגה בדיוק את השורות האלה, מקובצות לפי מסמך ופעולה.'
            }
            aria-pressed={dupOnly}
          >
            כפילויות
            <span className="num">{meas(d?.dup_pairs)}</span>
          </button>

          {/* ── THE TWO INCIDENT LENSES ─────────────────────────────────────────────────────
              Not filters over the loaded page — bounded scans that say what they read. */}
          <button
            className={`chip${focus === 'open' ? ' active' : ''}`}
            onClick={() => setFocus(focus === 'open' ? null : 'open')}
            aria-pressed={focus === 'open'}
            title={
              'שיגורים שנפתחו ולא נסגרו — ENDED_AT ריק — מעל מספר הדקות שמימין. ' +
              'או שהם רצים כרגע, או שההרצה מתה בין הסוגריים ואף אחד כבר לא יסגור אותם.'
            }
          >
            פתוחות מעל {openMin} דק׳
            {focus === 'open' && !scanning && <span className="num">{he(scan?.rows.length ?? 0)}</span>}
            {focus === 'open' && scanning && <span className="num">…</span>}
          </button>
          <input
            className="num"
            type="number"
            min={1}
            max={720}
            value={openMin}
            onChange={(e) => setOpenMin(Math.max(1, Math.min(720, Number(e.target.value) || 1)))}
            style={{ width: 62 }}
            aria-label="דקות לסינון שיגורים פתוחים"
            title="מעל כמה דקות שיגור פתוח נחשב חריג"
          />
          <button
            className={`chip${focus === 'reaped' ? ' active' : ''}`}
            onClick={() => setFocus(focus === 'reaped' ? null : 'reaped')}
            aria-pressed={focus === 'reaped'}
            title={
              `שיגורים שנסגרו ${REAPED_MIN} דקות או יותר אחרי שנפתחו. זו לא עבודה שארכה שעה — ` +
              'זו סגירה קבוצתית של סוגריים שהרצת הראוטר שלהם כבר מתה. נמדד בטבלה החיה: ' +
              '120 שורות בדיוק בטווח 65.1–65.2 דקות, ועוד 56,146 בין 4.5 ל-94 שעות.'
            }
          >
            נסגרו בכפייה ≥ {REAPED_MIN} דק׳
            {focus === 'reaped' && !scanning && (
              <span className="num">{he(scan?.rows.length ?? 0)}</span>
            )}
            {focus === 'reaped' && scanning && <span className="num">…</span>}
          </button>
        </div>

        <div className="atl-summary">
          <span>
            <b className="num">{meas(matched)}</b> {filtered ? 'פעולות תואמות' : 'פעולות'} בטווח{' '}
            <b>{winLabel(win)}</b>
          </span>
          {filtered && (
            <span className="muted">
              מתוך <b className="num">{meas(retained)}</b>
            </span>
          )}
          {/* "נסרקו N מסמכים" was written for the retired ACTION_LOG parser, which really did read
              DOCUMENTS to build a timeline out of their log column. The dispatch table reads ROWS,
              and on this source `scanned_rows` is `window_total` by construction — so the old line
              printed the same number twice under two names, one of which named the wrong unit.
              Shown now only when the pre-filter genuinely read more than it kept. */}
          {answered && d?.scanned_rows != null && d.scanned_rows !== windowTotal && (
            <span className="muted small" title="שורות שיגור שנקראו כדי לבנות את הטווח הזה">
              נקראו {he(d.scanned_rows)} שורות
            </span>
          )}
          {/* completeness, stated — never implied. Gated on `answered` like every other number
              here: a truncation badge carried over from the PREVIOUS window is a claim about a
              range nobody is looking at any more. */}
          {answered && d?.truncated && (
            <span
              className="pill warn"
              title={`הטווח מכיל ${he(windowTotal)} פעולות. ניתן לדפדף ולסנן ${he(retained)} מהן — האחרונות. לצפייה בכולן בחרו טווח צר יותר.`}
            >
              ‏{he(windowTotal)} בטווח — ניתן לדפדף ב-{he(retained)} האחרונות
            </span>
          )}
          {answered && d?.rows_capped && (
            <span
              className="pill warn"
              title={
                'הסריקה נעצרה בתקרת השורות של השרת. כל מספר על השורה הזו הוא רצפה, לא ספירה ' +
                'מלאה — הטווח מכיל לפחות כך, וייתכן שיותר. טווח צר יותר נכנס כולו מתחת לתקרה.'
              }
            >
              סריקה חלקית — המספרים הם רצפה
            </span>
          )}
          {/* COMPLETENESS — for the source this page ACTUALLY reads.
              The old note here listed three limits of the ACTION_LOG column parser (a 6,000-char
              middle-trim, stamps with no action name, entries with no timestamp) and printed a
              coverage percentage from `stamps_parsed / ts_tokens`. That source was retired with
              the column on 2026-08-21. On the dispatch table those two fields are both simply the
              row count — measured live 2026-08-23: ts_tokens 35,867, stamps_parsed 35,867,
              unparsed 0 — so the line rendered a permanent "100.00% מהחותמות שויכו", which is a
              number divided by itself presented as a quality measure, under a tooltip describing
              limits that no longer exist. A reassurance nobody measured is worse than no line.
              What IS real here: rows the scan could not read at all (bad STARTED_AT / no ACTION),
              which is a defect worth shouting about on the day it stops being zero — and the
              scan ceiling, which has its own badge above. */}
          {answered && !!d?.unparsed && (
            <span
              className="pill bad"
              title={
                'שורות בטבלת השיגורים שלא ניתן היה לקרוא — חותמת זמן פגומה או שם פעולה חסר. ' +
                'הן אינן מופיעות בשום מספר על המסך הזה. זו תקלת כתיבה בצינור, לא מגבלת תצוגה.'
              }
            >
              ‏{he(d.unparsed)} שורות לא קריאות
            </span>
          )}
        </div>
      </div>

      {openDoc && <ActionDocDrawer docId={openDoc} onClose={() => setOpenDoc(null)} />}
      {confirmUI}

      {/* what the duplicates chip actually opened, in words, beside the rows it opened */}
      {dupOnly && (
        <div className="callout warn">
          <b>מוצגות רק כפילויות.</b> כל שורה כאן היא שיגור של צמד (מסמך + פעולה) שכבר שוגר בהרצה
          אחרת באותו טווח, והשורות מקובצות כך שכל צמד יושב יחד. בטווח {winLabel(win)}:{' '}
          <b className="num">{meas(d?.dup_pairs)}</b> צמדים על פני{' '}
          <b className="num">{meas(d?.dup_rows)}</b> שורות. השוו את עמודת «הרצה n8n» בין השורות של
          אותו צמד — שתי הרצות שונות על אותה פעולה הן ריצה כפולה אמיתית.{' '}
          <button className="link" onClick={() => setDupOnly(false)}>
            הצג הכל
          </button>
        </div>
      )}

      {/* THE LENS PANEL — a bounded scan states its own bounds, every time it renders */}
      {focus && (
        <div className={`callout${scanErr ? ' bad' : scan && scan.rows.length ? ' warn' : ''}`}>
          {scanning && <span className="spinner" style={{ marginInlineEnd: 8 }} />}
          {scanErr ? (
            <>
              <b>הסריקה נכשלה.</b> {scanErr}
            </>
          ) : scanning ? (
            <>סורק את שני קצות הטווח…</>
          ) : scan ? (
            <>
              <b>
                {scan.lens === 'open'
                  ? `${he(scan.rows.length)} שיגורים פתוחים מעל ${scan.minutes} דק׳`
                  : `${he(scan.rows.length)} שיגורים שנסגרו ${REAPED_MIN} דק׳ או יותר אחרי הפתיחה`}
              </b>{' '}
              {scan.lens === 'open'
                ? 'שורה כזו היא או עבודה שרצה עכשיו, או הרצת ראוטר שמתה בין «Log Action Start» ל-«Log Action End» — אף אחד כבר לא יסגור אותה.'
                : 'סוגריים שנסגרו כך לא מודדים עבודה: הם נסגרו בקבוצה אחרי שההרצה שלהם כבר לא הייתה בחיים. אל תקראו את עמודת «משך» כזמן הפעולה.'}
              <div className="muted small" style={{ marginTop: 6 }}>
                {scan.complete ? (
                  <>
                    סריקה מלאה: נבדקו כל <b className="num">{he(scan.read)}</b> השיגורים בטווח{' '}
                    {winLabel(win)}. המספר מדויק.
                  </>
                ) : (
                  <>
                    סריקה תחומה: נבדקו <b className="num">{he(scan.read)}</b> שיגורים —{' '}
                    {/* under ?dup=1 the server orders rows GROUPED by (doc, action), not by time,
                        so "oldest / newest" would be the wrong description of the same two ends */}
                    {dupOnly
                      ? `${he(SCAN_END)} מכל קצה של הרשימה המקובצת`
                      : `${he(SCAN_END)} הישנים ביותר ו-${he(SCAN_END)} החדשים ביותר`}{' '}
                    — מתוך <b className="num">{he(scan.windowTotal)}</b> בטווח. המספר הוא רצפה, לא
                    ספירה מלאה; לתשובה מדויקת צמצמו את הטווח.
                  </>
                )}{' '}
                · נסרק ב-{scan.at.toLocaleTimeString('he-IL')}{' '}
                <button className="link" onClick={() => runScan(scan.lens, scan.minutes)}>
                  סרוק שוב
                </button>
              </div>
            </>
          ) : null}
        </div>
      )}

      {/* Empty is a STATE WORTH EXPLAINING, not a blank table: "nothing happened" and "your
          filter excludes everything" are different findings and lead to different next steps. */}
      {!focus && d && d.reachable !== false && matched === 0 && !loading && (
        <div className="callout">
          {filtered ? (
            <>
              <b>אין פעולות התואמות לסינון</b> בטווח {winLabel(win)} — בטווח הזה בוצעו{' '}
              {meas(retained)} פעולות. נקו סינון או הרחיבו את הטווח.
            </>
          ) : (
            <>
              <b>לא בוצעה אף פעולה בטווח {winLabel(win)}.</b> אם הצינור אמור לרוץ עכשיו, זו
              עצמה תשובה — הרחיבו את הטווח כדי לראות מתי בוצעה הפעולה האחרונה.
            </>
          )}
        </div>
      )}

      <DataGrid
        mode="server"
        tableId="indox:actionlog"
        columns={columns}
        rows={rows}
        getRowId={(r) => String(r._k ?? '')}
        rowCount={lensRows ? lensRows.length : matched}
        loading={focus ? scanning : loading}
        initialPageSize={DEFAULT_PAGE}
        height={620}
        label="יומן פעולות"
        searchPlaceholder="חיפוש בפעולה, במזהה השורה או בשם המסמך…"
        /* EXPORT sits in the toolbar rather than inside the grid. It was never the grid's to
           do: a built-in export writes the rows the component holds, which under server mode
           is the current page — a 100-row file on a view whose header says 151,626 actions is
           a lie the file cannot correct. `exportCsv` walks the same filtered query server-side. */
        toolbarEnd={
          <button type="button" className="btn" onClick={exportCsv} disabled={exporting}
                  title={`ייצוא עד ${he(EXPORT_MAX)} השיגורים החדשים התואמים לסינון — אחרי אישור עם המספרים`}>
            {exporting ? <><span className="spinner" /> מייצא…</> : 'ייצוא'}
          </button>
        }
        onStateChange={(s: GridState) => {
          const next: LogViewState = {
            page: s.pageIndex + 1,
            pageSize: s.pageSize,
            search: s.search,
            sort: s.sorting[0] ?? null,
            filters: s.filters,
          };
          // identity-compare so an unchanged state (the grid re-emits on its own renders)
          // does not restart the fetch — and with it the poll's clock
          setGs((prev) =>
            prev.page === next.page &&
            prev.pageSize === next.pageSize &&
            prev.search === next.search &&
            JSON.stringify(prev.sort) === JSON.stringify(next.sort) &&
            JSON.stringify(prev.filters || null) === JSON.stringify(next.filters || null)
              ? prev
              : next,
          );
        }}
        /* The row itself opens the history drawer. The two verbs are buttons in their own
           cells and stop propagation, so they no longer depend on the grid reporting which
           column a click landed on. */
        onRowOpen={(r) => {
          const id = String(r.id ?? '');
          if (id) setOpenDoc(id);
        }}
      />

      <div className="atl-foot muted small">
        <span>
          לחיצה על שורה פותחת את ההיסטוריה המלאה של המסמך; «פתח» מוביל למסמך עצמו ו«בקש עיבוד
          מחדש» מעביר אותו ל-ACTION_RESTART. קיצורים: <kbd>R</kbd> רענון ·{' '}
          <kbd>P</kbd> השהיית רענון · <kbd>Esc</kbd> סגירה
        </span>
        {instance && (
          <Link className="link" to={link('/documents')} title="טבלת המסמכים של המופע">
            לטבלת המסמכים <Ic p={IC.arrowLeft} />
          </Link>
        )}
      </div>
    </div>
  );
}
