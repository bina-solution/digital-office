import {
  useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode,
} from 'react';
import { Link, useParams } from 'react-router-dom';
import { InstancesContext, useInstanceLink } from '../instancesContext';
import DocumentStage from '../components/DocumentStage';
import {
  api, RepoConfig, DOCUMENT_STATUS_VALUES,
  ActionDocResult,
  ExtractionHistoryEntry,
} from '../api';
import { useConfirm } from '../components/ConfirmModal';
import { Ic, useToasts } from '../components/DataGrid';
import { IC } from '../icons';
import { statusKind, statusLabel, typeLabel, sourceLabel, actionLabel } from '../vocab';

/** THE constructors of document routes in this file — INSTANCE and id encoded once, identically,
 *  at every link (the nav audit found raw interpolation at 6 sites here). They take the instance
 *  now, not the repo: the repo never belonged in a URL a person reads. */
const docsRoute = (instance: string | undefined) =>
  `/i/${encodeURIComponent(instance ?? '')}/documents`;
const docRoute = (instance: string | undefined, docId: string) =>
  `${docsRoute(instance)}/${encodeURIComponent(docId)}`;

/* GROUPED FIELDS. The repo's schema carries ~80 columns (identity, AI extraction,
   selection/matching, balance-sheet lines, completion flags…) — a flat list of
   inputs read as noise, not a document. Each column is bucketed once by name into
   a labeled, collapsible section (`.rosetting`, the same collapsible-setting
   pattern the settings page already uses) so the page reads as a document with
   sections, not a table turned sideways. STATUS lives in its own control above
   (not repeated here) since it is the one field with real day-to-day write
   traffic and its own enum semantics. */
const GROUP_ORDER = [
  'זיהוי', 'תאריכים וסכומים', 'עיבוד ומצב', 'מקור',
  'זיהוי AI', 'התאמה ובחירה', 'דף מאזן (BS)', 'דגלי השלמה', 'אחר',
];
const IDENTITY_FIELDS = new Set(['NAME', 'COMPANY_ID', 'COMPANY_NAME', 'SHORT_DOC_ID', 'DOC_ID', 'TYPE', 'API_TOOLS_ID']);
// ACTION_LOG dropped from the table 2026-08-21; the document's history now comes from
// public.indox_action_execution_log via /dashboard/actions/document/<id>.
const STATE_FIELDS = new Set(['REQUIRED_ACTION', 'ERROR', 'RETRY_COUNT', 'ITERATION_COUNT', 'NEXT_RETRY_AT']);
const SOURCE_FIELDS = new Set(['SOURCE_TYPE', 'SOURCE_ID', 'SOURCE_LINK', 'LINK', 'FROM_OFFICE', 'FROM_OFFICE_CHECK', 'CONNECTION', 'SYNC_NAME', 'SIZE', 'HASH']);

function fieldGroup(name: string): string {
  const n = name.toUpperCase();
  if (n === 'STATUS' || STATE_FIELDS.has(n)) return 'עיבוד ומצב';
  if (n.startsWith('AI_')) return 'זיהוי AI';
  if (n.startsWith('SELECTED_') || n.startsWith('SELECTION_')) return 'התאמה ובחירה';
  if (n.startsWith('BS_')) return 'דף מאזן (BS)';
  if (n.endsWith('_COMPLETED')) return 'דגלי השלמה';
  if (/DATE|TIMESTAMP|AMOUNT/.test(n)) return 'תאריכים וסכומים';
  if (SOURCE_FIELDS.has(n)) return 'מקור';
  if (IDENTITY_FIELDS.has(n)) return 'זיהוי';
  return 'אחר';
}

/* ── THE COLUMNS, IN HEBREW ───────────────────────────────────────────────────────────────────
   This page is read by bookkeepers, and it was labelling their fields `DOC_DATE (string)` —
   the column name and its SQL type, which is the schema talking to itself. The type in
   particular says nothing here: every column on this table is TEXT, so `(string)` appeared 90-odd
   times and distinguished nothing.

   THE LABEL COMES FROM THE SCHEMA, not from a map in the frontend. The BFF merges
   blueprint/schema/display.json into the columns it serves, so this page and the grid read the
   same word for the same column and cannot drift — which two separate label maps allowed for
   as long as they both existed. An unlabelled column shows its raw name.

   The raw column name stays visible beside the label in mono: the people triaging a stuck
   document also read SQL and n8n node names, and taking their anchor away would be a downgrade
   dressed as a translation. */
const fieldLabelFrom = (cols: { name: string; label?: string | null }[], name: string) =>
  cols.find((c) => c.name === name)?.label || name;

function fmtEpochSeconds(ts?: number | null): string {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleString('he-IL', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}
function fmtMaybeDate(v: unknown): string {
  if (v == null || v === '') return '—';
  const d = new Date(String(v));
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString('he-IL');
}

/* ── VALUE NORMALIZERS FOR THE ENGINE-COMPARISON VIEW ─────────────────────────────────────────
   The comparison here uses the SAME rules the data-quality censuses use, so the screen and the
   SQL agree about what counts as "the engines agree":
   - ids compare on their last 5 alphanumerics (the table's SHORT_DOC_ID convention);
   - amounts go through the strict normalizer (junk stripped, a trailing minus moved to the
     front — supplier exports really do write "56387.00-" — and anything that still is not a
     number is treated as unparseable rather than as 0);
   - dates compare digits-only, both directions, because the engines write dd/mm/yy and ISO. */
const EMPTYISH = new Set(['', 'null', 'none', 'unknown', 'undefined', '[]', '{}']);
function rawVal(v: unknown): string {
  const s = String(v ?? '').trim();
  return EMPTYISH.has(s.toLowerCase()) ? '' : s;
}
/** display form: JSON arrays ("[\"a\",\"b\"]") flatten to "a, b"; everything else verbatim */
function showVal(v: unknown): string {
  const s = rawVal(v);
  if (s.startsWith('[') && s.endsWith(']')) {
    try {
      const a = JSON.parse(s);
      if (Array.isArray(a)) return a.map((x) => String(x)).filter(Boolean).join(', ');
    } catch { /* raw */ }
  }
  return s;
}
function normId5(v: unknown): string {
  const s = rawVal(v).replace(/[^a-zA-Z0-9]/g, '').toUpperCase();
  return s ? s.slice(-5).padStart(5, '0') : '';
}
function normAmt(v: unknown): number | null {
  let s = rawVal(v).replace(/[^0-9.\-]/g, '');
  if (!s) return null;
  if (s.endsWith('-') && !s.startsWith('-')) s = '-' + s.slice(0, -1);
  if (!/^-?[0-9]+(\.[0-9]+)?$/.test(s)) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}
const onlyDigits = (v: unknown): string => rawVal(v).replace(/[^0-9]/g, '');
function fmtAmount(v: unknown): string {
  const n = typeof v === 'number' ? v : normAmt(v);
  if (n == null) return showVal(v) || '—';
  return n.toLocaleString('he-IL', { maximumFractionDigits: 2 });
}
const isTrue = (v: unknown): boolean => String(v ?? '').trim().toLowerCase() === 'true';
/** hero-strip date: a business date, worn like one. The engines write everything from
 *  `26/05/2026` to `2026-04-27T00:00:00.000Z`; the fact cell shows the day (he-IL), and the
 *  raw string stays one hover away via the cell's own column tooltip. Unparseable → verbatim. */
function fmtDocDate(v: unknown): string {
  const s = rawVal(v);
  if (!s) return '';
  if (/^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$/.test(s)) return s; // already a human day
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s : d.toLocaleDateString('he-IL');
}

/* ── AFTER THE RESTART, SOMETHING HAS TO HAPPEN ON SCREEN ─────────────────────────────────────
 *
 * Pressing "בקש עיבוד מחדש" used to print a checkmark and go quiet. The operator was then holding
 * the only two questions that matter — was it picked up, and what did it do — with no way to
 * answer either except to reload the page and guess from the STATUS. A restart that produced
 * nothing and a restart still waiting for the next drain tick looked identical.
 *
 * This follows the same shape RunProgress.tsx established, for the same reasons:
 *
 *   1. LEDGER-DRIVEN, NOT n8n-DRIVEN. Progress comes from `/dashboard/actions/document/<id>` —
 *      the dispatch-bracket rows the Action Router writes as it goes, plus the document's own
 *      STATUS, in ONE read. INDOX is deliberately not coupled to n8n's database, and a follow
 *      panel is not worth buying that coupling.
 *   2. INDETERMINATE UNTIL THERE IS SOMETHING TO COUNT. A restart that has not been picked up has
 *      no denominator; drawing 0% would be inventing one. The bar says "working, extent unknown"
 *      until the first new dispatch appears, and ends EMPTY (not full) when nothing ever did —
 *      a full bar there would claim work that never happened.
 *   3. THE n8n LINK FROM THE FIRST POLL. The execution you most want to open is the one that has
 *      not come back yet. Base URL from the same place every other link in this app gets it
 *      (`n8n_base`); with no base configured the id is rendered as text, because an id you can
 *      paste beats a link that goes nowhere.
 *   4. PAUSES WHEN THE TAB IS HIDDEN — and the two-minute budget pauses with it, so switching
 *      tabs for a minute does not silently eat half the follow.
 *
 * It never re-dispatches and never writes: it watches. ACTION_RESTART is the only signal raised,
 * once, by the button that opened this.
 */
const FOLLOW_BUDGET_MS = 120_000;
const FOLLOW_TICK_MS = 3000;

function RestartFollow({
  id,
  since,
  onClose,
}: {
  id: string;
  /** the newest dispatch stamp that existed BEFORE the restart — anything later is new work.
   *  `0` when the document had no dispatch history at all. */
  since: number;
  onClose: () => void;
}) {
  const [d, setD] = useState<ActionDocResult | null>(null);
  const [n8nBase, setN8nBase] = useState<string>('');
  const [err, setErr] = useState<string | null>(null);
  const [spent, setSpent] = useState(0);
  const [live, setLive] = useState(true);
  const spentRef = useRef(0);

  // one read, once: the browser-reachable n8n address (never the in-cluster one)
  useEffect(() => {
    let dead = false;
    api
      .getSyncRegistry()
      .then((r) => {
        if (!dead) setN8nBase(r.n8n_base || '');
      })
      .catch(() => {
        /* no base → ids render as text; not a failure of the follow */
      });
    return () => {
      dead = true;
    };
  }, []);

  // a poll whose request outlives the panel must not write into it
  const deadRef = useRef(false);
  useEffect(() => {
    deadRef.current = false;
    return () => {
      deadRef.current = true;
    };
  }, []);

  const tick = useCallback(async () => {
    if (document.hidden) return; // paused: no request, and no budget spent either
    try {
      const r = await api.dashboardActionsDocument(id);
      if (deadRef.current) return;
      setD(r);
      setErr(r.reachable === false ? r.error || 'יומן השיגורים אינו זמין' : null);
    } catch (e: unknown) {
      if (deadRef.current) return;
      setErr(e instanceof Error ? e.message : String(e));
    }
    spentRef.current += FOLLOW_TICK_MS;
    if (deadRef.current) return;
    setSpent(spentRef.current);
    if (spentRef.current >= FOLLOW_BUDGET_MS) setLive(false);
  }, [id]);

  useEffect(() => {
    if (!live) return;
    tick();
    const t = window.setInterval(tick, FOLLOW_TICK_MS);
    return () => window.clearInterval(t);
  }, [live, tick]);

  const fresh = (d?.rows || []).filter((r) => r.ts > since);
  const newest = fresh.length ? fresh[fresh.length - 1] : null;
  const status = d?.status || '';
  const pickedUp = fresh.length > 0 || (Boolean(status) && status !== 'ACTION_RESTART');
  const secs = Math.round(spent / 1000);
  const execUrl = (ex?: string | null) =>
    ex && n8nBase ? `${n8nBase.replace(/\/+$/, '')}/executions/${ex}` : null;

  return (
    <div className="card">
      <h3>
        מעקב אחרי ההרצה{' '}
        <span className={`tag ${live ? 'run' : pickedUp ? 'ok' : ''}`}>
          {live ? 'עוקב' : pickedUp ? 'הסתיים' : 'לא נראתה פעילות'}
        </span>
      </h3>

      {err && <div className="callout bad" style={{ marginTop: 0 }}>{err}</div>}

      {/* indeterminate until there is a dispatch to point at; empty — never full — if none came */}
      <div
        className={`progress${live && !pickedUp ? ' indet' : ''}`}
        role="progressbar"
        aria-label="מעקב אחרי בקשת ההרצה מחדש"
      >
        <div
          className="bar"
          style={pickedUp ? { width: '100%' } : live ? undefined : { width: '0%' }}
        />
      </div>

      <div className="kv" style={{ marginTop: 10 }}>
        <dt>נלקח לעיבוד?</dt>
        <dd>
          {pickedUp ? (
            <span className="pill ok">כן{newest ? ` · ${fmtClock(newest.ts)}` : ''}</span>
          ) : live ? (
            <span className="muted">ממתין לתור הניקוז…</span>
          ) : (
            <span className="pill warn">לא, בשתי הדקות שנצפו</span>
          )}
        </dd>
      </div>
      <div className="kv">
        <dt>פעולה ששוגרה</dt>
        <dd>
          {newest ? (
            <ActionName name={newest.label} />
          ) : (
            <span className="muted">—</span>
          )}
        </dd>
      </div>
      <div className="kv">
        <dt>סטטוס עכשיו</dt>
        <dd>
          {status ? (
            <span className={`pill ${statusKind(status)}`} title={status}>
              {statusLabel(status)}
            </span>
          ) : (
            <span className="muted">—</span>
          )}
        </dd>
      </div>
      <div className="kv">
        <dt>הרצה ב-n8n</dt>
        <dd>
          {newest?.exec ? (
            execUrl(newest.exec) ? (
              <a className="link" href={execUrl(newest.exec)!} target="_blank" rel="noreferrer" title="ההרצה במנוע האוטומציה, בלשונית חדשה">
                {newest.exec} <Ic p={IC.external} />
              </a>
            ) : (
              <span className="mono num" title="לא הוגדרה כתובת n8n ציבורית">
                {newest.exec}
              </span>
            )
          ) : (
            <span className="muted">—</span>
          )}
        </dd>
      </div>

      {/* every dispatch since the request, not just the last — a restart usually runs a few */}
      {fresh.length > 1 && (
        <ol className="atl-list" style={{ marginTop: 10 }}>
          {fresh.map((r, i) => (
            <li key={`${r.ts}:${i}`} className={`atl-step cls-${r.cls}`}>
              <span className="atl-dot" aria-hidden="true" />
              <div className="atl-step-body">
                <div className="atl-step-top">
                  <span className="mono num atl-step-time">{fmtClock(r.ts)}</span>
                  {r.exec &&
                    (execUrl(r.exec) ? (
                      <a className="link small" href={execUrl(r.exec)!} target="_blank" rel="noreferrer">
                        #{r.exec}
                      </a>
                    ) : (
                      <span className="muted small mono num">#{r.exec}</span>
                    ))}
                </div>
                <ActionName name={r.label} />
              </div>
            </li>
          ))}
        </ol>
      )}

      <div className="muted small" style={{ marginTop: 10 }}>
        {live ? (
          <>
            נצפה {secs} שניות מתוך {FOLLOW_BUDGET_MS / 1000}; המעקב נעצר כשהלשונית מוסתרת וממשיך
            כשחוזרים אליה.
          </>
        ) : pickedUp ? (
          <>המעקב הסתיים. ההיסטוריה המלאה של המסמך ממשיכה להתעדכן בכרטיס «שיגורים אחרונים».</>
        ) : (
          <>
            שתי דקות של צפייה ולא נרשם שיגור. זו תשובה, לא תקלה: הבקשה נרשמה, ומה שלא קרה הוא
            שהניקוז עדיין לא הגיע למסמך. בדקו את מתג <span className="mono">indoxDrainOn</span> ואת
            תקרות הראוטר במסך ההגדרות.
          </>
        )}{' '}
        <button className="link" onClick={live ? () => setLive(false) : onClose}>
          {live ? 'עצור מעקב' : 'סגור'}
        </button>
      </div>
    </div>
  );
}

/* WHAT THE ROUTER DID, READ BY A PERSON. The ledger used to print the engine's own identifier
   (`source_feedback_0`) as the reading line of every row — English machine vocabulary on a
   Hebrew page, which reads as a log file rather than as this document's history. Translated
   where we have a translation, and where we do not the raw name is shown AS a raw name: mono,
   LTR, visibly the machine's word. Either way the identifier is in the tooltip, because the
   people triaging a stuck document also read n8n node names. */
function ActionName({ name }: { name: string }) {
  const he = actionLabel(name);
  return he ? (
    <span className="atl-step-label" title={name}>{he}</span>
  ) : (
    <span className="atl-step-label mono" title={name}
          style={{ direction: 'ltr', unicodeBidi: 'isolate', fontSize: 12 }}>
      {name}
    </span>
  );
}

/** clock-only time, the shape the action log uses for a stamp inside today. */
const fmtClock = (ts: number) => new Date(ts).toLocaleTimeString('he-IL', { hour12: false });

/* ── HOW MUCH ROOM THE DOCUMENT GETS — the operator's call, remembered ────────────────────────
   The split was 10:9 in code, which is a number nobody chose for a particular document. Some
   documents are read from the facts (a dense aging report), some from the paper (a photo of a
   delivery note), and the same person wants different splits for each. So the gutter is real:
   drag it, or focus it and use the arrows, and the choice survives the next document and the
   next session.

   RTL, and it matters: the data column is the FIRST grid column, which in this page renders on
   the RIGHT. The fraction it owns is therefore measured from the right edge, and ArrowLeft —
   which moves the divider left on screen — GROWS it. Getting this backwards produces a control
   that fights the hand holding it. */
const SPLIT_KEY = 'indox:doc-split';
const SPLIT_MIN = 0.22;
const SPLIT_MAX = 0.78;

function useSplitRatio() {
  const [ratio, setRatio] = useState<number>(() => {
    try {
      const v = Number(window.localStorage.getItem(SPLIT_KEY));
      return v >= SPLIT_MIN && v <= SPLIT_MAX ? v : 0.5;
    } catch {
      return 0.5; // private mode / blocked storage — a default is fine, a crash is not
    }
  });
  const splitRef = useRef<HTMLDivElement | null>(null);

  const persist = useCallback((v: number) => {
    try {
      window.localStorage.setItem(SPLIT_KEY, v.toFixed(3));
    } catch {
      /* not being able to remember the split is not a reason to fail the drag */
    }
  }, []);

  const isRtl = () => {
    const el = splitRef.current;
    return el ? getComputedStyle(el).direction === 'rtl' : true;
  };

  const onPointerDown = useCallback((e: React.PointerEvent<HTMLElement>) => {
    const el = splitRef.current;
    if (!el || e.button !== 0) return;
    e.preventDefault();
    const rect = el.getBoundingClientRect();
    const rtl = getComputedStyle(el).direction === 'rtl';
    let last = ratio;
    const move = (ev: PointerEvent) => {
      const x = ev.clientX - rect.left;
      const frac = rtl ? 1 - x / rect.width : x / rect.width;
      last = Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, frac));
      setRatio(last);
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      document.body.style.removeProperty('user-select');
      persist(last);
    };
    // while dragging over a text-heavy column the browser would otherwise select it all
    document.body.style.setProperty('user-select', 'none');
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }, [ratio, persist]);

  const onKeyDown = useCallback((e: React.KeyboardEvent) => {
    const step = e.key === 'ArrowLeft' ? 1 : e.key === 'ArrowRight' ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const dir = isRtl() ? step : -step;
    setRatio((r) => {
      const next = Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, r + dir * 0.02));
      persist(next);
      return next;
    });
  }, [persist]);

  return { ratio, splitRef, onPointerDown, onKeyDown };
}

/* ── ONE FACT CELL OF THE HERO STRIP ──────────────────────────────────────────────────────────
   label (Hebrew) + the raw column in the tooltip; a missing KEY fact renders as an amber "—" —
   on this screen an absence is a finding, not blank space. */
function Fact({
  k, col, v, sub, missing, children,
}: {
  k: string; col?: string; v?: string; sub?: string;
  /** mark the cell as a gap when the value is empty (only for fields this TYPE should have) */
  missing?: boolean;
  children?: ReactNode;
}) {
  const empty = !children && !(v && v.trim());
  return (
    <div className={`doc-fact${empty && missing ? ' miss' : ''}`}>
      <div className="k" title={col}>{k}</div>
      <div className="v">{children ?? (empty ? '—' : v)}</div>
      {sub ? <div className="s">{sub}</div> : null}
    </div>
  );
}

/* ── BALANCE-SHEET LINES, READABLE ────────────────────────────────────────────────────────────
   `BS_EXTRACTED_LINES` is a JSON blob nobody can read in a text input. An aging report's whole
   value IS its lines, so for BALANCE_SHEET documents they render as a real table — id, date,
   amount, balance, notes — plus the extractor's own totals arithmetic, and per line whether a
   live document with that id exists in the table (the same COMPANY_ID + last-5-alnum rule the
   linker uses). Suspicious extractions (most ids blank, or one id repeated down the column —
   the measured junk shapes) are flagged loudly: those are exactly the reports whose lines
   matched nothing. */
interface BsLine { id: string; date: string; amount: unknown; balanceAmount?: unknown; notes?: string; refrences?: unknown }
interface BsParsed {
  lines: BsLine[];
  summary: Record<string, unknown> | null;
  documentDate: string;
  processedAt: string;
  parseError: boolean;
}
function parseBsLines(raw: unknown): BsParsed | null {
  const s = String(raw ?? '').trim();
  if (!s) return null;
  try {
    const j = JSON.parse(s);
    const lines = Array.isArray(j?.data?.lines) ? j.data.lines : [];
    return {
      lines,
      summary: j?.data?.summary && typeof j.data.summary === 'object' ? j.data.summary : null,
      documentDate: String(j?.data?.documentDate ?? ''),
      processedAt: String(j?.processedAt ?? ''),
      parseError: false,
    };
  } catch {
    return { lines: [], summary: null, documentDate: '', processedAt: '', parseError: true };
  }
}

/* LINKED_BS holds the aging report's NAME (its file name), not a row id — measured live:
   0 of 500 non-empty LINKED_BS values exist as an ID. A link built on the raw value therefore
   404s on every document. Resolve it: one NAME-equality query, the row's real ID, a link that
   opens. `null` while resolving, '' when nothing matched (render text, not a dead link). */
function useLinkedBsId(repo: string | undefined, linkedBs: string) {
  const [bsId, setBsId] = useState<string | null>(null);
  useEffect(() => {
    if (!repo || !linkedBs) return;
    let dead = false;
    api
      .queryDocuments(repo, {
        mode: 'filter',
        filter: { NAME: { op: 'eq', value: linkedBs } },
        select: ['ID'],
        limit: 2,
      })
      .then((r) => {
        if (!dead) setBsId(r.rows.length ? String(r.rows[0].ID ?? '') : '');
      })
      .catch(() => {
        if (!dead) setBsId('');
      });
    return () => {
      dead = true;
    };
  }, [repo, linkedBs]);
  return bsId;
}

/** one company read, shared by every line: SHORT_DOC_ID → the live/placeholder doc it matches */
interface MatchTarget { id: string; status: string; hasFile: boolean }
function useCompanyDocIndex(repo: string | undefined, companyId: string, enabled: boolean) {
  const [index, setIndex] = useState<Map<string, MatchTarget> | null>(null);
  const [capped, setCapped] = useState(false);
  useEffect(() => {
    if (!repo || !companyId || !enabled) return;
    let dead = false;
    api
      .queryDocuments(repo, {
        mode: 'filter',
        filter: { COMPANY_ID: { op: 'eq', value: companyId } },
        select: ['ID', 'SHORT_DOC_ID', 'STATUS', 'HASH'],
        limit: 3000,
      })
      .then((r) => {
        if (dead) return;
        const m = new Map<string, MatchTarget>();
        for (const row of r.rows) {
          const sid = normId5(row.SHORT_DOC_ID);
          if (!sid) continue;
          const cand: MatchTarget = {
            id: String(row.ID ?? ''),
            status: String(row.STATUS ?? ''),
            hasFile: String(row.HASH ?? '').trim() !== '',
          };
          const prev = m.get(sid);
          // a real file beats a placeholder; a non-merged row beats a tombstone
          if (!prev || (cand.hasFile && !prev.hasFile) || (prev.status === 'MERGED' && cand.status !== 'MERGED')) {
            m.set(sid, cand);
          }
        }
        setIndex(m);
        setCapped(Boolean(r.truncated));
      })
      .catch(() => {
        if (!dead) setIndex(new Map());
      });
    return () => {
      dead = true;
    };
  }, [repo, companyId, enabled]);
  return { index, capped };
}

function BsLinesPanel(
  { repo, instance, row }:
  { repo: string; instance: string | undefined; row: Record<string, unknown> },
) {
  const parsed = useMemo(() => parseBsLines(row.BS_EXTRACTED_LINES), [row.BS_EXTRACTED_LINES]);
  const companyId = String(row.COMPANY_ID ?? '').trim();
  const { index, capped } = useCompanyDocIndex(repo, companyId, Boolean(parsed?.lines.length));

  if (!parsed) {
    return (
      <div className="card">
        <h3>שורות הדוח</h3>
        <div className="muted small">לדוח הזה עוד לא חולצו שורות (BS_EXTRACTED_LINES ריק).</div>
      </div>
    );
  }
  if (parsed.parseError) {
    return (
      <div className="card">
        <h3>שורות הדוח</h3>
        <div className="callout bad" style={{ marginTop: 0 }}>
          BS_EXTRACTED_LINES קיים אך אינו JSON תקין — הערך הגולמי זמין בעורך השדות למטה.
        </div>
      </div>
    );
  }

  const lines = parsed.lines;
  const n = lines.length;
  const blank = lines.filter((l) => !rawVal(l?.id)).length;
  const idCounts = new Map<string, number>();
  for (const l of lines) {
    const idv = rawVal(l?.id);
    if (idv) idCounts.set(idv, (idCounts.get(idv) ?? 0) + 1);
  }
  const distinct = idCounts.size;
  // the two measured junk shapes: a mostly-blank id column, or one value repeated down it
  const junkShape = n >= 5 && (blank >= n / 2 || distinct <= 2);
  const repeatedIds = new Set(
    [...idCounts.entries()].filter(([, c]) => c >= 3 && n >= 5).map(([idv]) => idv),
  );

  const sum = parsed.summary || {};
  const docTotal = normAmt(sum.documentTotal);
  const calcSum = normAmt(sum.calculatedAmountSum);
  /* OUR arithmetic, not the extractor's flag. The extractor's `totalsMatch` compares against its
     balance sum, so it can say "match" while documentTotal (15,818) and the amount sum (13,404.85)
     sit visibly apart in the two chips beside it — a green light contradicting the numbers it
     stands between. The chip now states the comparison the reader is already making; the
     extractor's own verdict stays available in the tooltip. */
  const totalsMatch = docTotal != null && calcSum != null && Math.abs(docTotal - calcSum) <= 1;
  const totalsDiff = docTotal != null && calcSum != null ? docTotal - calcSum : null;

  let matched = 0;
  let placeholders = 0;
  const matchFor = (l: BsLine): MatchTarget | null => {
    if (!index) return null;
    const sid = normId5(l?.id);
    if (!sid) return null;
    return index.get(sid) ?? null;
  };
  if (index) for (const l of lines) {
    const m = matchFor(l);
    if (m && m.hasFile && m.status !== 'MERGED') matched += 1;
    else if (m && !m.hasFile) placeholders += 1;
  }

  return (
    <div className="card">
      <h3>
        שורות הדוח <span className="muted small num">({n})</span>
      </h3>

      <div className="bschips">
        <span className="stat"><span>שורות</span><b className="num">{n}</b></span>
        <span className="stat"><span>מזהים ייחודיים</span><b className="num">{distinct}</b></span>
        {blank > 0 && <span className="stat"><span>ללא מזהה</span><b className="num">{blank}</b></span>}
        {index != null && (
          <span className="stat" title="שורות שנמצא להן מסמך חי (עם קובץ) באותה חברה, לפי 5 הספרות האחרונות">
            <span>נמצאו במערכת</span><b className="num">{matched}/{n}</b>
          </span>
        )}
        {index != null && placeholders > 0 && (
          <span className="stat" title="שורות שנפתחה להן שורת placeholder — המסמך עצמו עדיין לא נמצא">
            <span>ממתינים למסמך</span><b className="num">{placeholders}</b>
          </span>
        )}
        {docTotal != null && (
          <span className="stat"><span>סכום הדוח</span><b className="num">{fmtAmount(docTotal)}</b></span>
        )}
        {calcSum != null && (
          <span className="stat" title="סכום השורות כפי שחושב על ידי המחלץ">
            <span>סכום שורות</span><b className="num">{fmtAmount(calcSum)}</b>
          </span>
        )}
        {totalsDiff != null && (
          <span
            className={`pill ${totalsMatch ? 'ok' : 'warn'}`}
            title={`documentTotal − calculatedAmountSum = ${fmtAmount(totalsDiff)} · דגל המחלץ totalsMatch=${String(sum.totalsMatch)}`}
          >
            {totalsMatch ? 'הסכומים מתאימים' : `הפרש ${fmtAmount(Math.abs(totalsDiff))} מסכום הדוח`}
          </span>
        )}
        {parsed.documentDate && (
          <span className="stat"><span>תאריך הדוח</span><b className="num">{parsed.documentDate}</b></span>
        )}
      </div>

      {junkShape && (
        <div className="callout warn" style={{ marginTop: 0 }}>
          <b>חילוץ המזהים חשוד:</b>{' '}
          {blank >= n / 2
            ? `רוב השורות (${blank}/${n}) בלי מזהה מסמך — כנראה עמודת המזהה לא זוהתה בפורמט של הספק הזה.`
            : `רק ${distinct} מזהים שונים על פני ${n} שורות — אותו ערך חוזר לאורך העמודה, כנראה עוגן שגוי.`}{' '}
          הסכומים וההערות בדרך כלל נכונים; המזהים הם שדורשים תיקון מיפוי.
        </div>
      )}

      {n > 0 && (
        <div className="bslines">
          <table>
            <thead>
              <tr>
                <th className="num">#</th>
                <th>מזהה מסמך</th>
                <th>תאריך</th>
                <th>סכום</th>
                <th>יתרה</th>
                <th>הערות</th>
                <th title="האם קיים במערכת מסמך חי עם המזהה הזה באותה חברה">במערכת?</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l, i) => {
                const idv = rawVal(l?.id);
                const junkRow = !idv || repeatedIds.has(idv);
                const m = matchFor(l);
                return (
                  <tr key={i} className={junkRow ? 'junk' : undefined}>
                    <td className="num muted">{i + 1}</td>
                    <td className="lid">
                      {idv || <span className="muted">—</span>}
                      {idv && repeatedIds.has(idv) && (
                        <span className="pill warn" style={{ marginInlineStart: 6 }} title="אותו מזהה חוזר בכמה שורות">
                          חוזר
                        </span>
                      )}
                    </td>
                    <td className="num">{rawVal(l?.date) || <span className="muted">—</span>}</td>
                    <td className="num">{fmtAmount(l?.amount)}</td>
                    <td className="num">
                      {normAmt(l?.balanceAmount) != null ? fmtAmount(l?.balanceAmount) : <span className="muted">—</span>}
                    </td>
                    <td>{rawVal(l?.notes) || <span className="muted">—</span>}</td>
                    <td>
                      {index == null ? (
                        <span className="muted small">בודק…</span>
                      ) : m && m.hasFile && m.status !== 'MERGED' ? (
                        <Link className="link" to={docRoute(instance, m.id)} title={m.status}>
                          <span className="dot ok" style={{ marginInlineEnd: 4 }} />
                          {statusLabel(m.status)}
                        </Link>
                      ) : m && !m.hasFile ? (
                        <Link
                          className="link"
                          to={docRoute(instance, m.id)}
                          title="נפתחה שורת placeholder — המסמך עצמו עדיין לא נמצא"
                          style={{ color: 'var(--muted)' }}
                        >
                          ממתין למסמך
                        </Link>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="muted small" style={{ marginTop: 8 }}>
        «במערכת?» = מסמך באותה חברה שחמש הספרות האחרונות של המזהה שלו זהות — אותו כלל שבו מנוע
        הקישור עובד.{capped ? ' (לחברה הזו יותר מ-3,000 מסמכים — הבדיקה חלקית.)' : ''}
        {parsed.processedAt ? ` · חולץ ${fmtMaybeDate(parsed.processedAt)}` : ''}
      </div>
    </div>
  );
}

/* ── AI ⇆ LOCAL ⇆ FINAL, ONE ROW PER FIELD ────────────────────────────────────────────────────
   The extraction runs twice (AI + the local engine) and a selection step chooses. Today the
   only way to see that story was to open three collapsible groups and cross-reference ~20 raw
   inputs. One table: the field, what each engine read, and what the document ended up with —
   agreement painted green, disagreement amber, absence grey. The census rules (last-5 ids,
   strict amounts, digits-only dates) decide the colour, so this panel and the DQ SQL agree. */
/* [selection split 2026-08-25] The third column used to be SELECTED_*, the retired parallel value
   set. Nothing writes those columns any more, so the card showed a frozen value beside a live one.
   It is now the LEDGER: BS_LINE_* is the supplier's own record of this document, written onto the
   row when an aging report links to it, and it is a genuine third reading of the date and the
   amount — the selector uses it to break a tie between the two engines. Absent for every other
   field, and absent entirely until a report links, which the empty cell says plainly. */
interface EngineRow {
  label: string; ai: string; local: string; bs: string; fin: string;
  cmp: 'id' | 'amt' | 'date' | 'text';
}
const ENGINE_ROWS: EngineRow[] = [
  { label: 'מספר מסמך', ai: 'AI_DOC_ID', local: 'LOCAL_DOC_ID', bs: '', fin: 'DOC_ID', cmp: 'id' },
  { label: 'תאריך', ai: 'AI_DOC_DATE', local: 'LOCAL_DOC_DATE', bs: 'BS_LINE_DATE', fin: 'DOC_DATE', cmp: 'date' },
  { label: 'סכום', ai: 'AI_DOC_AMOUNT', local: 'LOCAL_DOC_AMOUNT', bs: 'BS_LINE_AMOUNT', fin: 'DOC_TOTAL_AMOUNT', cmp: 'amt' },
  { label: 'סוג', ai: 'AI_TYPE', local: 'LOCAL_TYPE', bs: '', fin: 'TYPE', cmp: 'text' },
  { label: 'חברה', ai: 'AI_COMPANY_ID', local: 'LOCAL_COMPANY_ID', bs: '', fin: 'COMPANY_ID', cmp: 'id' },
  { label: 'תעודות משלוח', ai: 'AI_SHIPMENT_IDS', local: 'LOCAL_SHIPMENT_IDS', bs: '', fin: 'SHIPMENT_DOC_ID', cmp: 'text' },
  { label: 'הזמנות', ai: 'AI_ORDER_IDS', local: 'LOCAL_ORDER_IDS', bs: '', fin: 'PURCHASE_ID', cmp: 'text' },
];

function enginesAgree(a: string, b: string, cmp: EngineRow['cmp']): boolean | null {
  if (!a || !b) return null; // nothing to compare
  if (cmp === 'id') return normId5(a) === normId5(b);
  if (cmp === 'amt') {
    const na = normAmt(a), nb = normAmt(b);
    if (na == null || nb == null) return String(a) === String(b);
    return Math.abs(na - nb) < 0.005;
  }
  if (cmp === 'date') {
    const da = onlyDigits(a), db = onlyDigits(b);
    if (!da || !db) return null;
    return da.includes(db) || db.includes(da);
  }
  /* CASE-INSENSITIVE, deliberately. The two legs spell the same answer differently — the local
     engine returns `q_v3_type`'s lowercase `returns` values ('invoice'), the AI leg returns
     'INVOICE' — so every typed document reported a disagreement the selectors never saw, because
     they all fold case before comparing. The writer is normalized now (BaseDocEx01), but ~26k
     rows were written before that and this screen is how they are read, so the comparison folds
     case too rather than waiting for a backfill that may never be worth running. */
  return showVal(a).trim().toLowerCase() === showVal(b).trim().toLowerCase();
}

function EngineMatrix({ row }: { row: Record<string, unknown> }) {
  const rows = ENGINE_ROWS.map((r) => {
    const ai = showVal(row[r.ai]);
    const local = showVal(row[r.local]);
    const bs = r.bs ? showVal(row[r.bs]) : '';
    const fin = showVal(row[r.fin]);
    return { ...r, aiV: ai, localV: local, bsV: bs, finV: fin, agree: enginesAgree(ai, local, r.cmp) };
  }).filter((r) => r.aiV || r.localV || r.bsV || r.finV);

  // engine attempt state, from the selection debug the pipeline itself wrote
  let aiStatus = '', localStatus = '';
  try {
    const dbg = JSON.parse(String(row.SELECTION_DEBUG_PERTYPE ?? ''));
    aiStatus = String(dbg?.AI_STATUS ?? '');
    localStatus = String(dbg?.LOCAL_STATUS ?? '');
  } catch { /* absent is fine */ }

  if (!rows.length) {
    return (
      <div className="card">
        <h3>נתוני המסמך</h3>
        <div className="muted small">אין עדיין נתוני חילוץ למסמך הזה.</div>
      </div>
    );
  }

  const disagreements = rows.filter((r) => r.agree === false).length;

  return (
    <div className="card">
      <h3>
        נתוני המסמך{' '}
        {disagreements > 0 ? (
          <span className="pill warn">{disagreements} אי-הסכמות</span>
        ) : (
          <span className="pill ok">המנועים מסכימים</span>
        )}
      </h3>
      {(aiStatus || localStatus) && (
        <div className="bschips">
          {aiStatus && (
            <span className="stat" title="AI_STATUS מתוך SELECTION_DEBUG_PERTYPE">
              <span>מנוע AI</span><b>{aiStatus}</b>
            </span>
          )}
          {localStatus && (
            <span className="stat" title="LOCAL_STATUS מתוך SELECTION_DEBUG_PERTYPE">
              <span>מנוע מקומי</span><b>{localStatus}</b>
            </span>
          )}
        </div>
      )}
      <div style={{ overflowX: 'auto' }}>
        <table className="exm">
          <thead>
            <tr>
              <th>שדה</th>
              <th>AI</th>
              <th>מקומי</th>
              <th>כרטסת</th>
              <th>סופי</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.fin}>
                <th title={[r.ai, r.local, r.bs, r.fin].filter(Boolean).join(' · ')}>{r.label}</th>
                <td className={`val ${r.agree === false ? 'diff' : r.agree === true ? 'same' : r.aiV ? '' : 'none'}`}>
                  {r.aiV || '—'}
                </td>
                <td className={`val ${r.agree === false ? 'diff' : r.agree === true ? 'same' : r.localV ? '' : 'none'}`}>
                  {r.localV || '—'}
                </td>
                <td className={`val ${r.bsV ? '' : 'none'}`}>{r.bsV || '—'}</td>
                <td className={`val final ${r.finV ? '' : 'none'}`}>{r.finV || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="muted small" style={{ marginTop: 8 }}>
        ירוק = המנועים מסכימים (מזהים לפי 5 ספרות אחרונות, סכומים אחרי נירמול) · כתום = אי-הסכמה ·
        «כרטסת» = השורה כפי שהספק עצמו רשם אותה (מדוח גיול מקושר) · «סופי» = מה שנבחר לשורה עצמה.
      </div>
    </div>
  );
}

export default function DocumentDetailPage() {
  /* Links that must not leave the instance behind — see useInstanceLink. */
  const link = useInstanceLink();

  /* the path names the INSTANCE; the repo is the BFF's business, not the URL's */
  const { instance, id } = useParams<{ instance: string; id: string }>();
  // same split as the browser page: the URL names the instance, the API path needs the repo
  const { active: repo } = useContext(InstancesContext);
  const [cfg, setCfg] = useState<RepoConfig | null>(null);
  const [row, setRow] = useState<Record<string, unknown> | null>(null);
  const [history, setHistory] = useState<Record<string, unknown>[]>([]);
  const [extractionHistory, setExtractionHistory] = useState<ExtractionHistoryEntry[] | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [statusBusy, setStatusBusy] = useState(false);
  const [retryBusy, setRetryBusy] = useState(false);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const { push } = useToasts();
  /** the document's own dispatch ledger — what the pipeline actually RAN on it, in order. Read
   *  once on mount so the panel beside the state card is never empty, and re-read after a
   *  restart so the follow's timeline and this card agree. */
  const [acts, setActs] = useState<ActionDocResult | null>(null);
  /** the follow, armed by the retry button with the newest stamp that existed before it */
  const [follow, setFollow] = useState<{ since: number; at: number } | null>(null);
  const { ask, confirmUI } = useConfirm();
  /* hooks run unconditionally, so the LINKED_BS resolution lives above the early returns —
     it quietly no-ops (empty name) until the row arrives */
  const linkedBsId = useLinkedBsId(repo ?? undefined, showVal(row?.LINKED_BS));

  const refreshActs = useCallback(() => {
    if (!id) return;
    api.dashboardActionsDocument(id).then(setActs).catch(() => setActs(null));
  }, [id]);

  const refreshRow = useCallback(() => {
    if (!repo || !id) return;
    api.getDocument(repo, id).then((r) => setRow(r.row)).catch(() => {});
    api.documentHistory(repo, id).then((r) => setHistory(r.events)).catch(() => {});
    refreshActs();
  }, [repo, id, refreshActs]);

  useEffect(() => {
    if (!repo || !id) return;
    setLoadErr(null);
    setFollow(null);
    api.getRepo(repo).then((r) => setCfg(r.repo)).catch((e: Error) => setLoadErr(`טעינת המאגר נכשלה: ${e.message}`));
    api.getDocument(repo, id).then((r) => setRow(r.row)).catch((e: Error) => setLoadErr(`טעינת המסמך נכשלה: ${e.message}`));
    api.documentHistory(repo, id).then((r) => setHistory(r.events)).catch(() => {});
    refreshActs();
    // best-effort: extraction runs may not exist for every document, and this
    // endpoint is specific to the extraction-testing subsystem — never let its
    // absence block the rest of the page.
    api.getExtractionDocHistory(id).then((r) => setExtractionHistory(r.history)).catch(() => setExtractionHistory([]));
  }, [repo, id, refreshActs]);

  /* the operator's split. ABOVE the early returns, deliberately: a hook that runs only on the
     loaded path changes the hook order between renders, which React fails on. */
  const {
    ratio, splitRef, onPointerDown: onGutterDown, onKeyDown: onGutterKey,
  } = useSplitRatio();
  /* THE DOCUMENT ON THE WHOLE WIDTH. Reading a dense aging report at half a screen is a squint;
     this hands the paper the full page and gives it back with the same key. The split ratio is
     untouched underneath, so leaving expanded returns to the operator's own layout. */
  const [expanded, setExpanded] = useState(false);

  if (!repo || !id) return <div className="callout bad">מסמך לא תקין. <Link to="/">חזרה</Link></div>;
  if (loadErr && !row) return <div className="callout bad">{loadErr} <Link to={docsRoute(instance)}>חזרה למסמכים</Link></div>;
  if (!cfg || !row) return <div className="spin">טוען…</div>;

  async function save() {
    const patch: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(edits)) {
      if (v !== String(row?.[k] ?? '')) patch[k] = v;
    }
    if (Object.keys(patch).length === 0) {
      push('warn', 'אין שינויים לשמירה');
      return;
    }
    setSaving(true);
    try {
      await api.patchDocument(repo!, id!, patch);
      push('ok', `נשמרו ${Object.keys(patch).length} שדות`);
      setEdits({});
      refreshRow();
    } catch (e) {
      push('bad', `השמירה נכשלה: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  }

  /* THE STATUS SELECT IS A WRITE INTO THE STATE MACHINE'S OWN COLUMN, so it confirms with the
     facts (from what, to what, what that status means for the pipeline) before the PATCH — it
     used to write on the change event alone, one slip of the wheel from re-parking a document. */
  async function changeStatus(next: string) {
    if (!row || next === String(row.STATUS ?? '')) return;
    const prev = String(row.STATUS ?? '');
    const ok = await ask({
      title: 'שינוי סטטוס המסמך',
      danger: next === 'ACTION_RESTART' || next === 'GARBAGE' || next === 'MERGED' || next === 'TRASH',
      consequence: (
        <>
          הסטטוס ישונה מ־<b>{prev ? statusLabel(prev) : '—'}</b> ל־<b>{statusLabel(next)}</b>{' '}
          (<span className="mono">{next}</span>), דרך אותו נתיב PATCH של כל עריכה.{' '}
          {next === 'ACTION_RESTART'
            ? 'מכונת המצבים תיקח את המסמך במחזור הניקוז הבא ותריץ אותו מחדש.'
            : next === 'PAUSE'
              ? 'המסמך יוקפא — הצינור לא ייגע בו עד לשינוי סטטוס נוסף.'
              : next === 'COMPLETED'
                ? 'סימון ידני כהושלם — הצינור יפסיק לטפל בו גם אם לא סיים.'
                : 'מכונת המצבים תקרא את הסטטוס החדש בפעם הבאה שתגיע למסמך.'}
        </>
      ),
      facts: [
        { label: 'מסמך', value: String(row.NAME ?? id) },
        { label: 'סטטוס נוכחי', value: prev ? statusLabel(prev) : '—', kind: prev ? statusKind(prev) : 'muted' },
        { label: 'סטטוס יעד', value: statusLabel(next), kind: statusKind(next) },
      ],
      confirmLabel: 'שנה סטטוס',
    });
    if (!ok) return; // the select is controlled by `row.STATUS`, so a cancel leaves it where it was
    setStatusBusy(true);
    setRow((r) => (r ? { ...r, STATUS: next } : r)); // optimistic
    try {
      await api.patchDocument(repo!, id!, { STATUS: next });
      push('ok', `הסטטוס עודכן ל-${statusLabel(next)}`);
      api.documentHistory(repo!, id!).then((r) => setHistory(r.events)).catch(() => {});
    } catch (e) {
      setRow((r) => (r ? { ...r, STATUS: prev } : r)); // rollback — never show a value the DB rejected
      push('bad', `עדכון הסטטוס נכשל: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setStatusBusy(false);
    }
  }

  /* "Retry" reuses the SAME lifecycle vocabulary the sync engine already understands
     rather than inventing a new endpoint: STATUS=ACTION_RESTART is one of the eleven
     enum values this table already carries, written through the same PATCH endpoint
     every other edit on this page uses. There is no separate /retry route — the
     STATUS column IS the retry signal. */
  async function retryPipeline() {
    const cur = String(row?.STATUS ?? '');
    const lastTs = acts?.last_ts ?? 0;
    const ok = await ask({
      title: 'בקשת עיבוד מחדש',
      consequence: (
        <>
          הסטטוס של המסמך ישונה מ־<b>{cur ? statusLabel(cur) : '—'}</b> ל־
          <b className="mono">ACTION_RESTART</b>, ומכונת המצבים תיקח אותו במחזור הניקוז הבא. שום
          פעולה לא משוגרת מכאן ישירות — זו הבקשה היחידה המאושרת להרצה חוזרת, והמכונה נשארת הכותב
          היחיד של השורה.
        </>
      ),
      facts: [
        { label: 'מסמך', value: String(row?.NAME ?? id) },
        { label: 'מזהה שורה', value: <span className="mono">{id}</span> },
        {
          label: 'סטטוס נוכחי',
          value: cur ? statusLabel(cur) : '—',
          kind: cur ? statusKind(cur) : 'muted',
        },
        {
          label: 'שיגורים שכבר רצו על המסמך',
          value: acts?.total != null ? acts.total.toLocaleString('he-IL') : '—',
          title: 'מתוך יומן השיגורים של הראוטר',
        },
        ...(lastTs
          ? [{ label: 'שיגור אחרון', value: new Date(lastTs).toLocaleString('he-IL') }]
          : []),
      ],
      unknown:
        'מתי הבקשה תילקח תלוי במחזור הניקוז ובתקרות הראוטר, ולא ניתן להבטיח זאת מכאן. אחרי האישור המסך יעקוב אחריה כשתי דקות ויראה מה שוגר בפועל.',
      confirmLabel: 'בקש עיבוד מחדש',
    });
    if (!ok) return;
    setRetryBusy(true);
    try {
      await api.patchDocument(repo!, id!, { STATUS: 'ACTION_RESTART' });
      push('ok', 'הועבר לעיבוד מחדש — המסך עוקב אחרי ההרצה');
      // arm the follow against the ledger as it stood BEFORE the request — that baseline is what
      // makes "a dispatch happened" a fact rather than a re-reading of history that was already there
      setFollow({ since: lastTs, at: Date.now() });
      refreshRow();
    } catch (e) {
      push('bad', `הבקשה נכשלה: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setRetryBusy(false);
    }
  }

  /* THE DOCUMENT ITSELF (indox-final-plan phase 8).
     This page used to be a field editor and an event list — for a screen whose whole purpose is
     looking at one document, and which showed the document nowhere. Anyone who actually needed to
     SEE the file had to leave and find the extraction tester, which is the same as this view not
     existing. It now renders the extraction UI's viewer, the shared component, rather than a second
     thinner copy: the plan is explicit that a second implementation is how the two drift, and that
     the extraction one is already the better view.

     `id` here is the document's primary key — which turns out NOT to be what the extraction
     endpoints key on. Verified live (2026-08-05) against doc_msdd8aijxokav4: `/extraction/file`,
     `/extraction/draw` and `/extraction/tokens` all 404 with `{"error":"not found"}` for every real
     incoming_documents row. Root cause, confirmed by reading extraction.py: those routes resolve
     files inside the extraction-TESTING dataset by `type/filename` (`_doc_path`, ids shaped like
     "invoice/arkhh-3.pdf" — see `_load_dataset`), a namespace that never overlaps with this table's
     `ID` column (`doc_<hash>`). `/extraction/rerun/<id>` ("הרץ חילוץ") hits the same wall — it looks
     the id up in that same dataset and 404s "unknown document" for every production document, so the
     button was removed rather than shipped permanently broken.
     RESOLVED for the two OVERLAY panes (2026-08-06). apitools never needed the dataset path: both
     overlay endpoints key on the OCR file hash alone, and the production row already carries that
     hash in API_TOOLS_ID (measured live: 5775/6318 = 91% populated). extraction.py now exposes
     `/documents/<id>/{draw,tokens}` off that column — the SAME two apitools calls and the SAME disk
     cache as the dataset routes, keyed on this table's namespace instead. Verified live against
     gdx_shp5 and doc_msgdlx2zbko1rg: tokens 200 image, draw 200 image.
     The ORIGINAL pane is served the same way, via apitools' own rasterised page
     (`.storage/ocr_pdf_images/<hash>.jpg`, the base image both overlays draw onto) through the new
     `/documentImage`, proxied as `/documents/<id>/file`. LINK cannot serve this pane: for
     Google-sourced rows it is an external drive.google.com URL the browser cannot embed, and the
     drive app rejects Google file ids (verified 400).

     HOW MUCH THIS ACTUALLY LIGHTS UP — measure before believing it. API_TOOLS_ID is present on
     5775/6318 rows (91%), but that is a HISTORICAL hash and apitools' caches have since been
     evicted: 6 entries in .storage/ocr_cache, 1150 in .storage/files, 26 page images. Across a
     25-document RANDOM sample, /tokens and /file both failed on 25 of 25 — apitools answers
     `404 file_not_found` for the hash. The documents that do work are the recently-processed tail.
     My first samples were all `order by ID desc`, which is exactly that tail — a biased sample that
     read as a 91% fix.
     So what is fixed here is the NAMESPACE bug (these routes key on the right id at last) and the
     honest failure shape; what is NOT fixed is data availability in apitools. Restoring a document
     needs its bytes re-fetched from LINK and re-OCR'd — the same missing ingredient the THUMBNAIL
     backfill needs, which is why the two should be solved by one mechanism, not two.
     THUMBNAIL (17/6318) remains the fallback, and the external link remains the one action that
     reaches the true source file rather than apitools' rasterisation of it. */
  const name = String(row.NAME ?? row.name ?? id);
  const status = String(row.STATUS ?? '');
  const docType = String(row.TYPE ?? '').toUpperCase();
  const originalLink = (row.LINK || row.SOURCE_LINK) ? String(row.LINK || row.SOURCE_LINK) : null;
  /* the thumbnail ENDPOINT (the THUMBNAIL column is retired): a 404 walks the viewer's ladder
     to the explained empty state — "no preview yet", never an error */
  const thumbnailUrl = api.documentThumbnailUrl(id);
  const apiToolsId = row.API_TOOLS_ID ? String(row.API_TOOLS_ID) : null;
  const errorText = row.ERROR ? String(row.ERROR) : null;
  const extractionUnavailableNote = apiToolsId
    ? 'אין נתוני חילוץ מוצגים למסמך זה במסך זה.'
    : 'המסמך לא הועלה ל-apitools עדיין — לא ניתן להריץ עליו חילוץ.';

  // group + order the schema's columns (excluding pk/STATUS, which have their
  // own dedicated controls above the grouped editor)
  const groups = new Map<string, typeof cfg.columns>();
  for (const c of cfg.columns) {
    if (c.name === cfg.primary_key || c.name.toUpperCase() === 'STATUS') continue;
    const g = fieldGroup(c.name);
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g)!.push(c);
  }

  /* ── the hero facts, per TYPE ──────────────────────────────────────────────
     what a bookkeeper asks first, answered without opening anything: who, what,
     when, how much — and the type-specific links (shipments for an invoice, the
     invoice for a shipment, the linked aging report for both). `missing` marks
     only fields this TYPE is supposed to carry, so an absent amount on a
     shipment (legitimate) stays quiet while an absent amount on an invoice is
     painted as the gap it is. */
  const companyName = showVal(row.COMPANY_NAME);
  const companyId = showVal(row.COMPANY_ID);
  const finalDocId = showVal(row.DOC_ID) || showVal(row.SHORT_DOC_ID);
  const docDate = showVal(row.DOC_DATE) || showVal(row.doc_date_norm);
  const amount = showVal(row.DOC_TOTAL_AMOUNT);
  const shipments = showVal(row.SHIPMENT_DOC_ID);
  const purchase = showVal(row.PURCHASE_ID);
  const linkedBs = showVal(row.LINKED_BS);
  const invForShip = showVal(row.INV_ID_FOR_SHIP);
  const isInvoice = docType === 'INVOICE';
  const isShipment = docType === 'SHIPMENT';
  const isBs = docType === 'BALANCE_SHEET';
  const prioritySkipped = isTrue(row.PRIORITY_SKIP);
  const prioritySynced = isTrue(row.PRIORITY_SYNC_COMPLETED);
  const bsForHero = isBs ? parseBsLines(row.BS_EXTRACTED_LINES) : null;

  /* `page-fill`: this screen takes the height the shell hands it and hands it on, exactly as the
     documents grid does — so the two columns below scroll independently and the PAGE never does.
     `doc-page` declares the container the split's own layout query reads. */
  return (
    <div className={`page-fill doc-page${expanded ? ' is-expanded' : ''}`}>
      {confirmUI}
      <div className="toolbar">
        <Link to={docsRoute(instance)} className="link" title="חזרה לטבלת המסמכים"><Ic p={IC.arrowRight} /> מסמכים</Link>
        <h1 className="mono" style={{ fontSize: 18, fontWeight: 800, margin: 0, letterSpacing: '-.01em' }}>{id}</h1>
        {name !== id && <span className="muted" style={{ maxWidth: 340, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={name}>{name}</span>}
        {docType && <span className="tag" title={docType}>{typeLabel(docType)}</span>}
        <span className={`pill ${statusKind(status)}`} title={status || ''}>{status ? statusLabel(status) : '—'}</span>
        <span style={{ marginInlineStart: 'auto' }} />
        {originalLink && (
          <a className="btn sm ghost" href={originalLink} target="_blank" rel="noreferrer" title="פתיחת קובץ המקור (דרייב / מייל) בלשונית חדשה">
            פתח מקור <Ic p={IC.external} />
          </a>
        )}
        <button className="btn sm" disabled={retryBusy} onClick={retryPipeline}
                title="מבקש עיבוד מחדש: הסטטוס יעבור ל-ACTION_RESTART אחרי אישור, והמסך יעקוב אחרי ההרצה">
          {retryBusy ? <><span className="spinner" /> שולח…</> : <><Ic p={IC.refresh} /> בקש עיבוד מחדש</>}
        </button>
      </div>

      {/* ── THE SPLIT: data on the right, the document itself on the left ──────────────────
          (RTL: the first grid column renders on the RIGHT.) Each column scrolls on its own and
          the page does not scroll at all, so however deep the data column goes the document
          stays where it is — the operator reads a fact and checks it against the paper in the
          same glance. The gutter between them belongs to the operator; see useSplitRatio. */}
      <div
        className="doc-split"
        ref={splitRef}
        style={{ '--doc-a': `${ratio}fr`, '--doc-b': `${1 - ratio}fr` } as React.CSSProperties}
      >
        <div className="doc-data">
          {follow && (
            /* keyed by the request instant: a SECOND restart gets a fresh follow (new baseline,
               full budget) instead of resuming the first one's clock */
            <RestartFollow
              key={follow.at}
              id={id}
              since={follow.since}
              onClose={() => setFollow(null)}
            />
          )}

          {errorText && (
            <div className="callout bad" style={{ margin: 0 }}>
              <b>שגיאה:</b> {errorText}
            </div>
          )}

          {/* the first glance: who/what/when/how much, and this TYPE's own links */}
          <div className="doc-hero">
            <Fact k="חברה" col="COMPANY_NAME · COMPANY_ID" sub={companyName ? companyId : undefined} missing>
              {(companyName || companyId) ? (
                <Link
                  className="link"
                  style={{ fontSize: 14 }}
                  to={`${docsRoute(instance)}?company=${encodeURIComponent(companyId)}`}
                  title="לכל המסמכים של החברה"
                >
                  {companyName || companyId}
                </Link>
              ) : undefined}
            </Fact>
            <Fact k="מספר מסמך" col="DOC_ID" v={finalDocId} missing={!isBs} />
            <Fact k="תאריך מסמך" col="DOC_DATE" v={fmtDocDate(isBs && !docDate ? (bsForHero?.documentDate || '') : docDate)} missing />
            {!isShipment && (
              <Fact
                k="סכום"
                col="DOC_TOTAL_AMOUNT"
                v={isBs && !amount
                  ? (bsForHero?.summary && normAmt(bsForHero.summary.documentTotal) != null ? `${fmtAmount(bsForHero.summary.documentTotal)} ₪` : '')
                  : (amount ? `${fmtAmount(amount)} ₪` : '')}
                missing={isInvoice}
              />
            )}
            {isInvoice && (
              <Fact k="תעודות משלוח" col="SHIPMENT_DOC_ID" v={shipments} />
            )}
            {isShipment && (
              <Fact k="חשבונית משויכת" col="INV_ID_FOR_SHIP" v={invForShip} />
            )}
            {(isInvoice || isShipment) && (
              <Fact k="הזמנה" col="PURCHASE_ID" v={purchase} />
            )}
            {(isInvoice || isShipment) && (
              <Fact k="דוח גיול מקושר" col="LINKED_BS">
                {linkedBs ? (
                  linkedBsId ? (
                    /* LINKED_BS is the report's NAME; linkedBsId is its resolved row id */
                    <Link className="link" to={docRoute(instance, linkedBsId)} style={{ fontSize: 13 }} title={`פתיחת דוח הגיול המקושר · ${linkedBs}`}>
                      {showVal(row.BS_LINE_AMOUNT) ? `${fmtAmount(row.BS_LINE_AMOUNT)} ₪ · ` : ''}לדוח <Ic p={IC.arrowLeft} />
                    </Link>
                  ) : (
                    <span
                      style={{ fontSize: 12.5, fontWeight: 600 }}
                      title={linkedBsId === '' ? 'לא נמצא מסמך גיול בשם הזה בטבלה' : 'מאתר את הדוח…'}
                    >
                      {showVal(row.BS_LINE_AMOUNT) ? `${fmtAmount(row.BS_LINE_AMOUNT)} ₪ · ` : ''}{linkedBs.slice(0, 22)}
                    </span>
                  )
                ) : (
                  '—'
                )}
              </Fact>
            )}
            {isBs && (
              <Fact k="שורות שחולצו" col="BS_EXTRACTED_LINES" v={bsForHero ? String(bsForHero.lines.length) : ''} missing />
            )}
            <Fact k="סונכרן לפריוריטי" col="PRIORITY_SYNC_COMPLETED · PRIORITY_SKIP">
              {prioritySkipped ? (
                <span className="pill muted" title={showVal(row.PRIORITY_SKIP_REASON) || 'PRIORITY_SKIP=true'}>
                  מדולג{showVal(row.PRIORITY_SKIP_REASON) ? ' ·  ' + showVal(row.PRIORITY_SKIP_REASON).slice(0, 22) : ''}
                </span>
              ) : prioritySynced ? (
                <span className="pill ok">סונכרן{showVal(row.PRIORITY_SYNC_COUNT) ? ` · ${showVal(row.PRIORITY_SYNC_COUNT)}` : ''}</span>
              ) : isBs ? (
                <span className="muted small">לא רלוונטי לדוח גיול</span>
              ) : (
                <span className="pill warn">עדיין לא</span>
              )}
            </Fact>
            <Fact k="מקור" col="SOURCE_TYPE" v={sourceLabel(row.SOURCE_TYPE)} sub={showVal(row.SYNC_NAME) || undefined} />
            <Fact k="עודכן" col="updated_at" v={fmtMaybeDate(row.updated_at)} />
          </div>

          {/* the per-TYPE extraction story */}
          {isBs ? (
            <BsLinesPanel repo={repo} instance={instance ?? undefined} row={row} />
          ) : (
            <EngineMatrix row={row} />
          )}

          {/* processing state + the dispatch ledger, side by side when there is room */}
          <div className="doc-duo">
            <div className="card">
              <h3>מצב עיבוד</h3>
              <div className="kv">
                <dt title="REQUIRED_ACTION — מה מכונת המצבים מתכוונת לעשות הלאה">פעולה נדרשת</dt>
                {/* machine vocabulary (and, on older rows, repair-sweep annotations) — mono LTR,
                    verbatim; the column's history census lives in the DQ report, not here */}
                <dd className="mono" style={{ direction: 'ltr', unicodeBidi: 'isolate', fontSize: 12, textAlign: 'start', overflowWrap: 'anywhere' }}>
                  {showVal(row.REQUIRED_ACTION) || '—'}
                </dd>
              </div>
              {/* RETRY_COUNT / NEXT_RETRY_AT are written by exactly one node — errorHandler01's
                  "Backoff + Dead-letter". That node only runs when `Get Lock Map` resolves the
                  failing execution's Redis doc-map key, and only indoxV2Driver01 writes that key,
                  under its OWN execution id — so a failure inside a sub-workflow (which is nearly
                  all of them) never reaches it. Measured 2026-08-06: 1 row of 6,341 carries the
                  writer's stamp, against 6,047 errorHandler01 executions.

                  So these fields are REAL but almost never populated. Rendering "ניסיונות 0" and
                  "ניסיון חוזר הבא —" on every document reads as "this document has never needed a
                  retry", when the truth is "nothing wrote this". Show the pair only when there is
                  genuine retry state; otherwise say nothing rather than something false.

                  RETRY_COUNT is also NOT interchangeable with ITERATION_COUNT (the old `?? `
                  fallback conflated them): ITERATION_COUNT counts state-machine passes, RETRY_COUNT
                  counts post-failure backoff attempts. Only 6 rows have an ITERATION_COUNT at all. */}
              {(Number(row.RETRY_COUNT ?? 0) > 0 || Boolean(row.NEXT_RETRY_AT)) && (
                <>
                  <div className="kv"><dt>ניסיונות</dt><dd className="num">{String(row.RETRY_COUNT ?? 0)}</dd></div>
                  {row.NEXT_RETRY_AT
                    ? <div className="kv"><dt>ניסיון חוזר הבא</dt><dd className="num">{fmtMaybeDate(row.NEXT_RETRY_AT)}</dd></div>
                    : null}
                </>
              )}
              {Number(row.ITERATION_COUNT ?? 0) > 0 && (
                <div className="kv">
                  <dt title="ITERATION_COUNT — כמה פעמים מכונת המצבים עברה על המסמך">מעברי מכונת מצבים</dt>
                  <dd className="num">{String(row.ITERATION_COUNT)}</dd>
                </div>
              )}
              <div className="kv">
                <dt title="TIMESTAMP — מתי המסמך נקלט">נקלט</dt>
                <dd className="num">{fmtMaybeDate(row.TIMESTAMP ?? row.created_at)}</dd>
              </div>
              <div className="setrow" style={{ borderBottom: 'none', paddingTop: 12 }}>
                <span className="key" style={{ minWidth: 'auto' }}>שינוי סטטוס</span>
                <span className="ctl">
                  <select value={status} disabled={statusBusy} onChange={(e) => changeStatus(e.target.value)} style={{ width: 'auto' }}
                          aria-label="שינוי סטטוס המסמך" title="בחירה פותחת אישור עם הסטטוס הנוכחי והיעד לפני הכתיבה">
                    {!DOCUMENT_STATUS_VALUES.includes(status as (typeof DOCUMENT_STATUS_VALUES)[number]) && status && (
                      <option value={status}>{status} (לא ברשימה)</option>
                    )}
                    {DOCUMENT_STATUS_VALUES.map((s) => (
                      <option key={s} value={s}>{statusLabel(s)}</option>
                    ))}
                  </select>
                  {statusBusy && <span className="spinner" />}
                </span>
              </div>
            </div>

            <div className="card">
              <h3>
                שיגורים אחרונים{' '}
                {acts?.total != null && <span className="muted small num">({acts.total})</span>}
              </h3>
              {acts == null && <div className="muted small">טוען…</div>}
              {acts && acts.reachable === false && (
                <div className="callout bad" style={{ marginTop: 0 }}>
                  {acts.error || 'יומן השיגורים אינו זמין'}
                </div>
              )}
              {acts && acts.reachable !== false && (acts.rows?.length ?? 0) === 0 && (
                <div className="muted small">
                  הראוטר עדיין לא שיגר אף פעולה על המסמך הזה. אם הוא אמור להיות בעיבוד, זו עצמה
                  תשובה.
                </div>
              )}
              {!!acts?.rows?.length && (
                <ol className="atl-list">
                  {acts.rows
                    .slice(-6)
                    .reverse()
                    .map((r, i) => (
                      <li key={`${r.ts}:${i}`} className={`atl-step cls-${r.cls}`}>
                        <span className="atl-dot" aria-hidden="true" />
                        <div className="atl-step-body">
                          <div className="atl-step-top">
                            <span
                              className="mono num atl-step-time"
                              title={new Date(r.ts).toLocaleString('he-IL')}
                            >
                              {new Date(r.ts).toLocaleString('he-IL', {
                                day: '2-digit',
                                month: '2-digit',
                                hour: '2-digit',
                                minute: '2-digit',
                              })}
                            </span>
                            {r.exec && (
                              <span className="muted small mono num" title="מזהה הרצה ב-n8n">
                                #{r.exec}
                              </span>
                            )}
                          </div>
                          <ActionName name={r.label} />
                        </div>
                      </li>
                    ))}
                </ol>
              )}
              <div className="muted small" style={{ marginTop: 8 }}>
                מקור: יומן השיגורים של הראוטר.{' '}
                <Link className="link" to={link('/actions')} title="יומן הפעולות של המופע">
                  ליומן הפעולות <Ic p={IC.arrowLeft} />
                </Link>
              </div>
            </div>
          </div>

          {/* everything the page always had, foldable — nothing was removed, it just no longer
              stands between the operator and the first glance */}
          <details className="card doc-fold">
            <summary>
              <h3>שדות המסמך <span className="muted small">({cfg.columns.length} עמודות · עריכה)</span></h3>
            </summary>
            <div style={{ marginTop: 6 }}>
              {GROUP_ORDER.filter((g) => groups.has(g)).map((g) => {
                const cols = groups.get(g)!;
                return (
                  <details key={g} className="rosetting">
                    <summary>{g} <span className="len">{cols.length}</span></summary>
                    <div style={{ marginTop: 10 }}>
                      {cols.map((c) => {
                        const current = String(row[c.name] ?? '');
                        return (
                          <div key={c.name} className="field">
                            {/* Hebrew label, raw column name kept beside it (the people triaging a
                                document here also read SQL and n8n node names). */}
                            <label>
                              {fieldLabelFrom(cfg.columns, c.name)}{' '}
                              <span className="muted mono" style={{ fontWeight: 400 }}>
                                {c.name}
                              </span>
                            </label>
                            <input
                              type="text"
                              defaultValue={current}
                              onChange={(e) => setEdits((s) => ({ ...s, [c.name]: e.target.value }))}
                              className="mono"
                            />
                          </div>
                        );
                      })}
                    </div>
                  </details>
                );
              })}
              <button onClick={save} className="btn" style={{ marginTop: 8 }} disabled={saving}
                      title="כותב את השדות ששונו דרך נתיב ה-PATCH של השרת">
                {saving ? <><span className="spinner" /> שומר…</> : 'שמירה'}
              </button>
            </div>
          </details>

          <details className="card doc-fold">
            <summary>
              <h3>היסטוריית שינויים <span className="muted small num">({history.length})</span></h3>
            </summary>
            <div className="space-y-2" style={{ maxHeight: 320, overflowY: 'auto', marginTop: 6 }}>
              {history.length === 0 && <div className="muted small">אין אירועים עדיין</div>}
              {history.map((e, i) => (
                <div key={i} style={{ borderBottom: '1px solid var(--line)', paddingBottom: 8, marginBottom: 8 }}>
                  <div className="flex justify-between">
                    <span style={{ fontWeight: 600 }}>{String(e.event_type)}</span>
                    <span className="muted small">{String(e.occurred_at)}</span>
                  </div>
                  <pre className="codeblock" style={{ fontSize: 10, marginTop: 4 }}>
                    {JSON.stringify(e.row, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          </details>

          <details className="card doc-fold">
            <summary>
              <h3>ניסיונות חילוץ <span className="muted small num">{extractionHistory != null ? `(${extractionHistory.length})` : ''}</span></h3>
            </summary>
            <div style={{ marginTop: 6 }}>
              {extractionHistory == null && <div className="muted small">טוען…</div>}
              {extractionHistory != null && extractionHistory.length === 0 && (
                <div className="muted small">לא נמצאו ניסיונות חילוץ עבור מסמך זה</div>
              )}
              <div className="space-y-2" style={{ maxHeight: 320, overflowY: 'auto' }}>
                {extractionHistory?.map((h, i) => (
                  <div key={i} style={{ borderBottom: '1px solid var(--line)', paddingBottom: 8, marginBottom: 8 }}>
                    <div className="flex justify-between">
                      <span style={{ fontWeight: 600 }}>
                        {h.result.error ? <span style={{ color: 'var(--red)' }}>נכשל</span> : `${h.result.ok}/${h.result.total} תואמים`}
                      </span>
                      <span className="muted small num">{fmtEpochSeconds(h.started)}</span>
                    </div>
                    {h.result.error && <div className="small" style={{ color: 'var(--red)', marginTop: 2 }}>{h.result.error}</div>}
                  </div>
                ))}
              </div>
            </div>
          </details>
        </div>

        {/* the gutter: how much room the document gets is the operator's call, and it sticks */}
        <div
          className="doc-gutter"
          role="separator"
          aria-orientation="vertical"
          aria-label="רוחב תצוגת המסמך"
          aria-valuenow={Math.round((1 - ratio) * 100)}
          aria-valuemin={Math.round((1 - SPLIT_MAX) * 100)}
          aria-valuemax={Math.round((1 - SPLIT_MIN) * 100)}
          tabIndex={0}
          title="גררו כדי לשנות את חלוקת המסך — או חצים במקלדת"
          onPointerDown={onGutterDown}
          onKeyDown={onGutterKey}
        />

        {/* the document — original / drawn extraction / OCR tokens, with zoom, fit and rotate.
            It takes the height this column hands it and never names a viewport unit. */}
        <div className="doc-stagecol">
          <DocumentStage
            fileUrl={apiToolsId ? api.documentFileUrl(id) : null}
            drawUrl={apiToolsId ? api.documentDrawUrl(id) : null}
            tokensUrl={apiToolsId ? api.documentTokensUrl(id) : null}
            thumbnailUrl={thumbnailUrl}
            name={name}
            docKey={id}
            expanded={expanded}
            onExpandToggle={() => setExpanded((v) => !v)}
            /* Every source here is an IMAGE. `/documents/<id>/file` serves apitools' rasterised
               page — a JPG, not a PDF — and rendering that in an <iframe> meant a 404 painted the
               raw JSON error body into the frame (observed live on doc_msm34qg8wsnrxk:
               `{"error":"no stored page image..."}`). As an image it walks the stage's honest
               ladder instead: preview → an explained absence with the פתח-מקור escape hatch. */
            /* extraction-first: when apitools holds the drawn overlay, open on it — this screen's
               job is understanding what was extracted, and the overlay IS that answer. The
               original stays one click away; docs with no overlay open on the original. */
            initialSource={apiToolsId ? 'draw' : 'doc'}
            emptyDocNote="אין עדיין תצוגה מקדימה של המסמך במערכת."
            emptyDrawNote={extractionUnavailableNote}
            emptyTokensNote={extractionUnavailableNote}
            externalLink={originalLink}
            externalLinkLabel="פתח מקור"
          />
        </div>
      </div>
    </div>
  );
}
