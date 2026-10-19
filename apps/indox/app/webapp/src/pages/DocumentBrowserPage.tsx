import { useEffect, useMemo, useRef, useState, useCallback, type ReactNode, useContext } from 'react';
/* [url-view-state 2026-08-24, owner order] THE VIEW LIVES IN THE URL — the ActionLogPage
   contract ("THE WINDOW LIVES IN THE URL"), extended to this page: q / sort / page / size /
   view are read ONCE on mount and written back (replace:true, debounced) whenever the view
   changes, so the address bar is always a shareable snapshot of what is on screen. Entry
   drill-down params derive from the URL alone; the grid's own column filters round-trip
   through it (ai/context/console-url-state.md rule 7). */
import { Link, useHref, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { InstancesContext } from '../instancesContext';
import {
  ApiError,
  BASE_PATH,
  ColumnDef,
  DISPATCH_ACTIONS,
  DOCUMENT_STATUS_VALUES,
  DispatchAction,
  DocumentStatus,
  RepoConfig,
  RepoView,
  api,
  repoSource,
} from '../api';
import { EMBEDDED } from '../App';
import { DRILL_PARAM, SOURCE_BLANK } from '../urlVocab';
import {
  sourceLabel,
  statusKind,
  statusLabel,
  statusTitle,
  typeLabel,
} from '../vocab';
import DataGrid, {
  GRID_MONTH_NONE,
  GridColumn,
  GridFilterValue,
  GridRow,
  GridState,
  gridMonthLabel,
  Ic,
  useToasts,
} from '../components/DataGrid';
import { IC } from '../icons';

/* feather link-2 — the copy-view-link control, in the same stroke-icon language as the pager */
const IC_LINK = IC.link;

/** THE THUMBNAIL, from the endpoint — the THUMBNAIL column is retired (no thumbnail files are
 *  generated any more). `GET /documents/<id>/thumbnail` answers image bytes, or 404 when apitools
 *  holds no raster for the document yet; a 404 is "no preview yet", drawn as a quiet file icon,
 *  never a broken-image glyph and never an error. */
function Thumb({ id }: { id: string }) {
  const [gone, setGone] = useState(false);
  if (!id || gone) {
    return (
      <span className="dg-null" title="אין תצוגה מקדימה עדיין — apitools טרם הפיק תמונת עמוד למסמך" aria-label="אין תצוגה מקדימה">
        <Ic p={IC.file} />
      </span>
    );
  }
  return (
    <img
      src={api.documentThumbnailUrl(id)}
      alt=""
      loading="lazy"
      style={{
        width: 34, height: 34, objectFit: 'cover', borderRadius: 6,
        border: '1px solid var(--line)', display: 'block',
      }}
      onError={() => setGone(true)}
    />
  );
}

/** The URL worth sharing. Inside the console iframe that is the SHELL's deep-link form
 *  (#/m/<id>/inner?query — the shell mirrors our route there), so a pasted link opens the
 *  screen WITH the console chrome; standalone it is simply the address bar.
 *  The module id is read from the SHELL's own hash (same-origin) — never derived from the
 *  /a/<alias> mount, because alias ≠ module id for 4 of the 10 live modules (mailview→mail,
 *  chat→whatsapp, …) and a guessed id is a dead link. */
function shareUrl(): string {
  if (!EMBEDDED) return window.location.href;
  try {
    const mod = /^#\/m\/([^/?#]+)/.exec(window.parent.location.hash)?.[1];
    if (mod) {
      const base = BASE_PATH.replace(/\/+$/, '');
      const inner = window.location.pathname.slice(base.length) + window.location.search;
      return `${window.location.origin}/#/m/${mod}${inner}`;
    }
  } catch {
    /* cross-origin parent — the direct address is the only honest link */
  }
  return window.location.href;
}

/* ── LAYER 3: RENDERERS ARE KEYED BY TYPE, NEVER BY COLUMN NAME ────────────────────────────
   This file used to ask `u === 'STATUS'`, `u === 'THUMBNAIL'`, `u === 'ERROR'`, `u === 'TYPE'`
   and carry its own COLUMN_LABEL map, DEFAULT_VISIBLE list, COL_WIDTH table and align regex. All
   of that was knowledge about SPECIFIC COLUMNS living in a component, which is why a column added
   to the pipeline reached the operator as an English shout and why `ERROR` — named in
   DEFAULT_VISIBLE but absent from the registry — silently never rendered at all.

   Now the server sends what a column IS (`display.json`: label, logical type, value domain,
   ui_type) and WHERE it shows (`views.json`), and this component only knows how to draw a TYPE.
   It could render a table it has never heard of. Adding a column, relabelling one, or giving one
   a pill is a JSON edit with no frontend change — which is the whole point of the split.

   The kind is resolved in one place, in this order:
     ui_type (bespoke cells: image, link, error) -> enum (a value domain) -> logical type. */
type CellKind = 'image' | 'link' | 'error' | 'enum' | 'bool' | 'date' | 'number' | 'json' | 'text';

function cellKind(c: ColumnDef): CellKind {
  const ui = String(c.ui_type ?? '');
  if (ui === 'image' || ui === 'link' || ui === 'error') return ui;
  if (c.enum) return 'enum';
  switch (String(c.type ?? 'string')) {
    case 'bool': return 'bool';
    case 'date':
    case 'timestamp': return 'date';
    case 'int':
    case 'numeric': return 'number';
    case 'json': return 'json';
    default: return 'text';
  }
}

/** The enum's own words and colour, from the catalog — not from a map in this file. A domain
 *  whose values carry `kind` renders as a pill (STATUS); one that does not renders as plain
 *  Hebrew (TYPE, SOURCE_TYPE). Neither case needs the column's name. */
function enumRenderer(c: ColumnDef) {
  const dom = c.enum_values ?? {};
  const hasKind = Object.values(dom).some((v) => v && v.kind);
  const wordFor = (v: unknown) => String(dom[String(v)]?.label ?? v ?? '');
  return {
    render: (v: unknown) => {
      if (v == null || v === '') return '';
      const word = wordFor(v);
      if (!hasKind) return word;
      const kind = dom[String(v)]?.kind ?? 'muted';
      return (
        <span className={`pill ${kind}`} title={`${word} · ${String(v)}`}>
          {word}
        </span>
      );
    },
    text: (v: unknown) => (v == null || v === '' ? '' : wordFor(v)),
    options: Object.entries(dom).map(([value, meta]) => ({
      value,
      label: meta?.label ?? value,
    })),
  };
}

const RENDERERS: Record<
  Exclude<CellKind, 'enum'>,
  (c: ColumnDef, pk: string) => Partial<GridColumn>
> = {
  /* A REAL PREVIEW WHERE THERE IS ONE, a quiet file icon where there is not. The cell reads the
     thumbnail ENDPOINT by the row's id — the column's own value is ignored (the THUMBNAIL column
     is retired; nothing writes it). */
  image: (_c, pk) => ({
    align: 'center',
    sortable: false,
    filter: false as const,
    render: (_v, row) => <Thumb id={String(row[pk] ?? '')} />,
    text: () => '',
  }),

  /* A DOT, NOT A WALL OF STACK TRACE. The message is the title; a failing row is visible
     without opening it, and the column costs 58px. */
  error: () => ({
    align: 'center',
    render: (v) =>
      v == null || v === '' ? (
        ''
      ) : (
        <span className="dg-errdot" role="img" aria-label="שגיאה" title={String(v)} />
      ),
    text: (v) => (v == null ? '' : String(v)),
  }),

  link: () => ({
    render: (v) =>
      v == null || v === '' ? '' : (
        <a
          href={String(v)}
          target="_blank"
          rel="noopener noreferrer"
          className="link"
          onClick={(e) => e.stopPropagation()}
          title={`פתיחת המקור בלשונית חדשה · ${String(v)}`}
        >
          פתח <Ic p={IC.external} />
        </a>
      ),
    text: (v) => (v == null ? '' : String(v)),
  }),

  /* THE TEXT-BOOLEAN. 15 of this table's 16 logical booleans are physically TEXT, so the value
     arriving here is "true"/"false"/""/null, and `if (value)` on the string "false" is TRUE —
     a live defect class in this product. The catalog's logical type is what makes this cell
     correct; Postgres could never have told us. */
  bool: () => ({
    align: 'center',
    render: (v) => {
      const s = String(v ?? '').trim().toLowerCase();
      if (s === '' || s === 'null') return '';
      return s === 'true' || s === 't' || s === '1'
        ? <span title="כן" aria-label="כן" style={{ color: 'var(--accent-d)', display: 'inline-flex' }}><Ic p={IC.check} /></span>
        : <span className="dg-null" title="לא">—</span>;
    },
    text: (v) => {
      const s = String(v ?? '').trim().toLowerCase();
      return s === 'true' || s === 't' || s === '1' ? 'כן' : s ? 'לא' : '';
    },
  }),

  date: () => ({ align: 'start' }),
  number: () => ({ align: 'end' }),
  json: () => ({
    render: (v) =>
      v == null || v === '' ? '' : (
        <span className="mono small" title={typeof v === 'string' ? v : JSON.stringify(v)}>
          {typeof v === 'string' ? v.slice(0, 60) : JSON.stringify(v).slice(0, 60)}
        </span>
      ),
  }),
  text: () => ({}),
};

/** The named view's placement, or — when the catalog has no view for this table — everything
 *  hidden but the first few, so a table nobody has authored a view for is still readable. */
function placementOf(view: RepoView | null, cols: ColumnDef[]) {
  if (!view || !view.columns?.length) {
    const fallback = cols.slice(0, 6).map((c) => c.name);
    return {
      order: fallback,
      width: {} as Record<string, number>,
      shown: new Set(fallback),
      curated: cols.length > 6,
    };
  }
  const width: Record<string, number> = {};
  const order: string[] = [];
  for (const c of view.columns) {
    order.push(c.key);
    if (c.width) width[c.key] = c.width;
  }
  return { order, width, shown: new Set(order), curated: true };
}

function buildColumns(cfg: RepoConfig, view: RepoView | null): GridColumn[] {
  const pk = cfg.primary_key;
  const cols: ColumnDef[] = cfg.columns;
  const place = placementOf(view, cols);

  const built = cols
    .map((c) => {
      const kind = cellKind(c);
      const base: GridColumn = {
        key: c.name,
        // The schema names its own columns. An unlabelled column renders as its raw name —
        // visible and usable the day it appears, never blank and never absent.
        header: c.label || c.name,
        headerTitle: c.label ? `${c.label} · ${c.name}` : c.name,
        editable: c.name !== pk,
        width: place.width[c.name] ?? (c.name.length > 18 ? 200 : 160),
        /* `deprecated` HIDES, IT DOES NOT REMOVE — that is the catalog's own rule, and the
           reason it exists: a column that is real but undeclared is the failure display.json was
           written to end, and dropping a deprecated column from the picker would recreate it by
           omission. It is off the default view and one click away, never gone. */
        hidden: !!c.deprecated || (place.curated && !place.shown.has(c.name)),
        align: (c.align as 'start' | 'end' | 'center' | undefined) ?? undefined,
      };
      const extra =
        kind === 'enum' ? enumRenderer(c) : RENDERERS[kind](c, pk);
      const col: GridColumn = { ...base, ...extra };
      // an explicit catalog alignment always outranks the renderer's default
      if (c.align) col.align = c.align as 'start' | 'end' | 'center';
      if (kind === 'enum' && (extra as { options?: unknown }).options) {
        col.type = 'select';
      }
      return col;
    });

  /* THE VIEW'S ORDER IS THE SCREEN'S ORDER. Columns it names come first, in its sequence;
     everything else keeps schema order behind them, hidden but one click away in the picker. */
  const rank = new Map(place.order.map((k, i) => [k, i]));
  const sorted = built.sort((a, b) => {
    const ra = rank.has(a.key) ? (rank.get(a.key) as number) : Number.MAX_SAFE_INTEGER;
    const rb = rank.has(b.key) ? (rank.get(b.key) as number) : Number.MAX_SAFE_INTEGER;
    return ra - rb;
  });
  /* A schema that no longer carries the retired THUMBNAIL column still gets a preview column:
     synthetic, first, reading the thumbnail endpoint by the row's id. Not sortable, not
     filterable, not editable — it is a picture of the row, not a value of it. */
  if (!cols.some((c) => String(c.ui_type ?? '') === 'image')) {
    sorted.unshift({
      key: '_thumb',
      header: 'תצוגה',
      headerTitle: 'תצוגה מקדימה — תמונת העמוד הראשון מ-apitools; אייקון = טרם הופקה',
      width: 58,
      editable: false,
      sortable: false,
      filter: false,
      align: 'center',
      render: (_v, row) => <Thumb id={String(row[pk] ?? '')} />,
      text: () => '',
    });
  }
  return sorted;
}

// ── add/upsert drawer (unchanged behaviour — kept for the grid's ＋ שורה) ─────
function UpsertDrawer({
  cfg,
  onDone,
  onClose,
}: {
  cfg: RepoConfig;
  onDone: () => void;
  onClose: () => void;
}) {
  const [fields, setFields] = useState<Record<string, string>>(() =>
    Object.fromEntries(cfg.columns.map((c) => [c.name, ''])),
  );
  const [jsonMode, setJsonMode] = useState(false);
  const [jsonText, setJsonText] = useState(
    JSON.stringify([Object.fromEntries(cfg.columns.map((c) => [c.name, '']))], null, 2),
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const { push } = useToasts();

  async function submit() {
    setErr(null);
    setBusy(true);
    try {
      let payload: Record<string, unknown>[];
      if (jsonMode) {
        payload = JSON.parse(jsonText);
        if (!Array.isArray(payload)) payload = [payload as Record<string, unknown>];
      } else {
        const row: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(fields)) {
          if (v !== '') row[k] = v;
        }
        payload = [row];
      }
      const res = await api.upsertRows(cfg.name, payload);
      push('ok', `${res.stats.created} נוצרו, ${res.stats.updated} עודכנו, ${res.stats.noop} ללא שינוי`);
      onDone();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      const body = (e as { body?: unknown })?.body;
      setErr(body ? `${msg}\n${JSON.stringify(body, null, 2)}` : msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="drawer-ov">
      <div className="scrim" onClick={onClose} />
      <div className="drawer">
        <div className="drawer-h">
          <h3>הוספה / עדכון שורות</h3>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1 small muted" style={{ cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={jsonMode}
                onChange={(e) => setJsonMode(e.target.checked)}
                style={{ width: 'auto', cursor: 'pointer' }}
              />
              אצווה JSON
            </label>
            <button onClick={onClose} className="icbtn" aria-label="סגירה" title="סגירת החלון בלי לשמור"><Ic p={IC.x} /></button>
          </div>
        </div>
        <div className="drawer-body">
          {jsonMode ? (
            <div>
              <p className="small muted" style={{ marginTop: 0 }}>
                הדביקו מערך JSON של אובייקטי שורה. שורה עם מפתח ראשי קיים תעודכן; אחרת תיווצר.
              </p>
              <textarea
                className="mono"
                style={{ height: 288 }}
                value={jsonText}
                onChange={(e) => setJsonText(e.target.value)}
                spellCheck={false}
              />
            </div>
          ) : (
            <div className="space-y-3">
              <p className="small muted" style={{ marginTop: 0 }}>
                מלאו את השדות למטה. אם <span className="mono">{cfg.primary_key}</span> כבר קיים השורה <strong>תעודכן</strong>; אחרת <strong>תיווצר</strong>.
              </p>
              {cfg.columns.map((c) => (
                <div key={c.name} className="field">
                  <label>
                    <span className="mono">{c.name}</span>
                    {c.name === cfg.primary_key && (
                      <span className="tag pk" style={{ marginInlineStart: 4 }}>pk</span>
                    )}
                    <span className="muted" style={{ marginInlineStart: 4 }}>({c.type})</span>
                    {!c.nullable && c.name !== cfg.primary_key && (
                      <span style={{ marginInlineStart: 4, color: 'var(--red)' }}>*</span>
                    )}
                  </label>
                  <input
                    type="text"
                    value={fields[c.name]}
                    onChange={(e) => setFields((s) => ({ ...s, [c.name]: e.target.value }))}
                    placeholder={c.name === cfg.primary_key ? 'השאירו ריק להקצאה אוטומטית' : ''}
                    className="mono"
                  />
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="drawer-foot">
          {err && <pre className="codeblock callout bad" style={{ maxHeight: 128, overflowY: 'auto' }}>{err}</pre>}
          <button onClick={submit} disabled={busy} className="btn" style={{ width: '100%', justifyContent: 'center' }}>
            {busy ? 'שומר…' : 'הוסף / עדכן'}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── BLAST-RADIUS CONFIRMATION ────────────────────────────────────────────────
   A bulk write is the one action on this screen that cannot be undone by clicking
   something else, so it is the one action that has to state what it is about to do in
   numbers before it does it: how many documents, which statuses they are in RIGHT NOW,
   and what the target status will cause. Never a native confirm() — a confirm() cannot
   show the breakdown, cannot be read in Hebrew RTL, and cannot carry the sentence about
   completion flags being cleared, which is the part an operator needs to have read.

   The doctrine this dialog serves: only the state machine changes a row, ACTION_RESTART
   is the only sanctioned re-run, and every write goes through the BFF's PATCH path
   (api.bulkPatchDocuments → POST /repos/<repo>/documents/bulk), never direct SQL. */
const RESTART_NOTE =
  'הפעולה מנקה את דגלי ההשלמה ומריצה מחדש את הצינור עבורם.';

function bulkNote(status: DocumentStatus): string {
  if (status === 'ACTION_RESTART') return RESTART_NOTE;
  if (status === 'PAUSE') return 'המסמכים יוקפאו — הצינור לא ייגע בהם עד לשינוי סטטוס נוסף.';
  if (status === 'GARBAGE' || status === 'MERGED') return 'סטטוס סופי — המסמכים לא ימשיכו בצינור.';
  if (status === 'COMPLETED') return 'סימון ידני כהושלם — הצינור יפסיק לטפל בהם גם אם לא סיים.';
  return 'הסטטוס נכתב דרך אותו נתיב PATCH של כל עריכה אחרת; מכונת המצבים ממשיכה להיות הכותב היחיד.';
}

function BulkStatusModal({
  ids,
  rows,
  pk,
  fixed,
  count,
  onCancel,
  onConfirm,
}: {
  ids: string[];
  rows: GridRow[];
  pk: string;
  /** ACTION_RESTART for the restart button; undefined = let the operator pick */
  fixed?: DocumentStatus;
  /** the REAL selection size when it exceeds `ids` (all-matching selector mode) */
  count?: number;
  onCancel: () => void;
  onConfirm: (status: DocumentStatus) => Promise<void>;
}) {
  const [status, setStatus] = useState<DocumentStatus | ''>(fixed ?? '');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) onCancel();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onCancel, busy]);

  // the real numbers: what the selection is in now, counted, not estimated
  const breakdown = useMemo(() => {
    const idSet = new Set(ids);
    const counts = new Map<string, number>();
    for (const r of rows) {
      if (!idSet.has(String(r[pk] ?? ''))) continue;
      const s = String(r.STATUS ?? '') || '(ריק)';
      counts.set(s, (counts.get(s) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [ids, rows, pk]);

  const n = count ?? ids.length;
  return (
    <div className="modal-ov" role="dialog" aria-modal="true" aria-label="אישור פעולה על המסמכים שנבחרו">
      <div className="modal" style={{ width: 'min(520px, 94vw)' }}>
        <div className="modal-h">
          <h3>{fixed === 'ACTION_RESTART' ? 'בקשת עיבוד מחדש' : 'שינוי סטטוס לנבחרים'}</h3>
          <button className="icbtn" onClick={onCancel} disabled={busy} aria-label="סגור" title="ביטול (Esc)">
            <Ic p={IC.x} />
          </button>
        </div>

        {!fixed && (
          <div className="field" style={{ marginBottom: 12 }}>
            <label htmlFor="bulk-status">סטטוס יעד</label>
            <select
              id="bulk-status"
              value={status}
              onChange={(e) => setStatus(e.target.value as DocumentStatus | '')}
            >
              <option value="">בחרו סטטוס…</option>
              {DOCUMENT_STATUS_VALUES.map((s) => (
                <option key={s} value={s}>
                  {statusLabel(s)} — {s}
                </option>
              ))}
            </select>
          </div>
        )}

        <p style={{ margin: '0 0 10px', fontSize: 14, lineHeight: 1.6 }}>
          להעביר <strong className="num">{n.toLocaleString('he-IL')}</strong> מסמכים ל-
          <span className="mono">{status || '…'}</span>
          {status ? <> ({statusLabel(status)})</> : null}? {status ? bulkNote(status) : ''}
        </p>

        {breakdown.length > 0 && (
          <div className="callout" style={{ marginBottom: 12 }}>
            <div className="small muted" style={{ marginBottom: 6 }}>הסטטוס הנוכחי של הנבחרים:</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {breakdown.map(([s, c]) => (
                <span key={s} className={`pill ${statusKind(s)}`} title={statusTitle(s)}>
                  {statusLabel(s)} · <span className="num">{c.toLocaleString('he-IL')}</span>
                </span>
              ))}
            </div>
          </div>
        )}

        {err && <div className="callout bad" style={{ marginBottom: 12, whiteSpace: 'pre-wrap' }}>{err}</div>}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button ref={cancelRef} className="btn ghost sm" onClick={onCancel} disabled={busy}>
            ביטול
          </button>
          <button
            className="btn sm"
            disabled={busy || !status}
            onClick={async () => {
              if (!status) return;
              setBusy(true);
              setErr(null);
              try {
                await onConfirm(status);
              } catch (e) {
                setErr(e instanceof Error ? e.message : String(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? 'מבצע…' : `אישור · ${n.toLocaleString('he-IL')} מסמכים`}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── BULK COMMAND MODALS [2026-08-24, owner order] ────────────────────────────
   "אני חייב דרך לעשות את כל העבודה הזאת מהתצוגה": drain a selection, fire a router
   action directly, edit any field for the whole group. Same modal skeleton as
   BulkStatusModal; every confirm states the count and what will actually happen. */

const DISPATCH_LABEL: Record<DispatchAction, string> = {
  extract_base_doc: 'חילוץ בסיס (זיהוי חברה/סוג/תאריך) — עוקף את decide',
  extract_per_type: 'חילוץ לפי סוג (מספר/סכום/משלוחים)',
  link_documents: 'קישור מסמכים לדוח גיול',
  find_link: 'איתור קובץ המקור בדרייב',
  action_priority_sync: 'סנכרון לפריוריטי',
  select_base: 'בחירה מחדש — חברה/סוג/תאריך (ללא חילוץ)',
  select_type: 'בחירה מחדש — מספר/תאריך/סכום/משלוח + ציון (ללא חילוץ)',
};

function BulkOpModal({
  title, n, children, confirmLabel, disabled, onCancel, onConfirm,
}: {
  title: string; n: number; children?: ReactNode; confirmLabel: string;
  disabled?: boolean; onCancel: () => void; onConfirm: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onCancel(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onCancel, busy]);
  return (
    <div className="modal-ov" role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal" style={{ width: 'min(540px, 94vw)' }}>
        <div className="modal-h">
          <h3>{title}</h3>
          <button className="icbtn" onClick={onCancel} disabled={busy} aria-label="סגור" title="ביטול (Esc)"><Ic p={IC.x} /></button>
        </div>
        {children}
        {err && <div className="callout bad" style={{ marginBottom: 12, whiteSpace: 'pre-wrap' }}>{err}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="btn ghost sm" onClick={onCancel} disabled={busy}>ביטול</button>
          <button
            className="btn sm"
            disabled={busy || disabled}
            onClick={async () => {
              setBusy(true); setErr(null);
              try { await onConfirm(); }
              catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
              finally { setBusy(false); }
            }}
          >
            {busy ? 'מבצע…' : `${confirmLabel} · ${n.toLocaleString('he-IL')} מסמכים`}
          </button>
        </div>
      </div>
    </div>
  );
}

function DispatchModal({ n, onCancel, onConfirm }: {
  n: number; onCancel: () => void; onConfirm: (action: DispatchAction) => Promise<void>;
}) {
  const [action, setAction] = useState<DispatchAction | ''>('');
  return (
    <BulkOpModal
      title="הרצת פעולה ישירה (Action Router)"
      n={n}
      confirmLabel="שגר"
      disabled={!action}
      onCancel={onCancel}
      onConfirm={() => onConfirm(action as DispatchAction)}
    >
      <div className="field" style={{ marginBottom: 12 }}>
        <label htmlFor="disp-action">פעולה</label>
        <select id="disp-action" value={action} onChange={(e) => setAction(e.target.value as DispatchAction | '')}>
          <option value="">בחרו פעולה…</option>
          {DISPATCH_ACTIONS.map((a) => (
            <option key={a} value={a}>{DISPATCH_LABEL[a]} — {a}</option>
          ))}
        </select>
      </div>
      <p className="small" style={{ margin: '0 0 10px', lineHeight: 1.6 }}>
        שיגור ישיר לראוטר, בלי decide באמצע — במנות של 5 (תקרת החילוץ), עם חותם{' '}
        <span className="mono">console_manual</span> ביומן השיגורים. קריאה ארוכה: על קבוצה גדולה
        זה ירוץ דקות; אל תסגרו את הלשונית.
      </p>
    </BulkOpModal>
  );
}

function FieldEditModal({ n, cfg, onCancel, onConfirm }: {
  n: number; cfg: RepoConfig; onCancel: () => void;
  onConfirm: (col: string, value: string) => Promise<void>;
}) {
  const [col, setCol] = useState('');
  const [value, setValue] = useState('');
  const [clear, setClear] = useState(false);
  // sorted by the CATALOG's Hebrew label — the same words the grid headers use, so the picker
  // and the table cannot disagree about what a column is called
  const labelOf = (name: string) =>
    cfg.columns.find((c) => c.name === name)?.label || name;
  const cols = cfg.columns
    .map((c) => c.name)
    .filter((name) => name !== cfg.primary_key && name !== 'created_at' && name !== 'updated_at')
    .sort((a, b) => labelOf(a).localeCompare(labelOf(b), 'he'));
  return (
    <BulkOpModal
      title="עריכת שדה לכל הנבחרים"
      n={n}
      confirmLabel="כתוב"
      disabled={!col}
      onCancel={onCancel}
      onConfirm={() => onConfirm(col, clear ? '' : value)}
    >
      <div className="field" style={{ marginBottom: 10 }}>
        <label htmlFor="fe-col">עמודה</label>
        <select id="fe-col" value={col} onChange={(e) => setCol(e.target.value)}>
          <option value="">בחרו עמודה…</option>
          {cols.map((name) => (
            <option key={name} value={name}>{labelOf(name)} — {name}</option>
          ))}
        </select>
      </div>
      <div className="field" style={{ marginBottom: 8 }}>
        <label htmlFor="fe-val">ערך</label>
        <input id="fe-val" type="text" className="mono" value={value} disabled={clear}
               onChange={(e) => setValue(e.target.value)} placeholder="הערך שייכתב לכולם" />
      </div>
      <label className="small" style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 10 }}>
        <input type="checkbox" checked={clear} onChange={(e) => setClear(e.target.checked)} />
        רוקן את השדה (כתוב ערך ריק)
      </label>
      <p className="small muted" style={{ margin: '0 0 10px' }}>
        נכתב דרך אותו נתיב PATCH של כל עריכה — מכונת המצבים נשארת הכותב היחיד. STATUS נבדק מול
        רשימת הסטטוסים; שאר העמודות נכתבות כפי שהוקלדו.
      </p>
    </BulkOpModal>
  );
}

/* ── MONTH NAVIGATION ─────────────────────────────────────────────────────────
   The headline feature. There are THREE date-ish columns on this table and they
   disagree: DOC_DATE (the document's own date), TIMESTAMP, and created_at (when
   the row was WRITTEN — thousands of rows share one bulk-import timestamp, so
   created_at is useless for business navigation, but it's still offered because
   an operator investigating a specific import batch legitimately wants it).

   The per-month COUNT on each pill's badge comes from a REAL server-side
   aggregate — `POST /repos/<repo>/documents/month-index` — not a client-side
   scan. An earlier version of this page paged through queryDocuments(mode:'all',
   select:[dateCol]) itself and bucketed in the browser, gated by the query
   endpoint's `truncated` flag to know when to stop. That flag compared the
   returned row count against the CLIENT's requested page size (2000), but
   PostgREST silently clamps every response to its own server-side cap (1000 on
   this stack) regardless of what's asked for — so the loop always read
   "1000 returned, 2000 asked for, must be everything" and stopped after the
   FIRST page. Every badge undercounted by however much of the table lived past
   row ~1000 (observed 6-9x on the real corpus; confirmed via direct psql
   monthly counts vs. the pill). The backend aggregate doesn't have this problem
   — it pages internally with `_paged_select`, which compares each chunk against
   the FIXED page size IT requested, not a caller-supplied number — so it reads
   the whole table (bounded, `sampled: true` if truly capped) every time.

   FILTERING a chosen month still reuses the SAME backend filter mechanism the
   drill-down chips already use (`mode:'filter'`), with the `month` operator —
   which exists precisely so the filter and the aggregate above are ONE rule
   (backends/../core/month_key.py) rather than two that agree by assumption.

   They did not agree. This used to send `{op:'startswith', value:'YYYY-MM'}`,
   i.e. a raw string prefix, on the premise quoted in the previous revision of
   this comment: "DOC_DATE/TIMESTAMP/created_at are TEXT/timestamptz columns read
   back as ISO strings". DOC_DATE is not. It is TEXT holding whatever the OCR/AI
   extractor printed, and on the live corpus that is overwhelmingly `D/M/YYYY` or
   `D/M/YY` — which the month INDEX buckets correctly (it parses both shapes) and
   an ISO prefix cannot match at all. Measured 2026-08-11: the chip for
   אוקטובר 2026 advertised 38 documents and clicking it rendered 3, and 17,296 of
   the table's 22,641 rows were countable but unopenable. A month you cannot open
   is not month navigation. */

const DATE_COL_CANDIDATES: { col: string; label: string }[] = [
  { col: 'DOC_DATE', label: 'תאריך מסמך (DOC_DATE)' },
  { col: 'TIMESTAMP', label: 'חותמת זמן (TIMESTAMP)' },
  { col: 'created_at', label: 'נוצר בתאריך (created_at)' },
];
interface MonthBucket { key: string; label: string; count: number }
interface MonthIndex {
  buckets: MonthBucket[];
  /** empty dates — what the "ללא תאריך" bucket's `is_null` drill-down actually returns */
  noDate: number;
  /** present-but-unreadable dates; no operator selects them, so they are stated, not linked */
  badDate: number;
  total: number;
  loading: boolean;
  err: string | null;
  sampled: boolean;
}

function useMonthIndex(repoName: string | null, dateCol: string): MonthIndex {
  const [state, setState] = useState<MonthIndex>({
    buckets: [], noDate: 0, badDate: 0, total: 0, loading: false, err: null, sampled: false,
  });
  const reqRef = useRef(0);

  const run = useCallback(() => {
    if (!repoName || !dateCol) {
      setState({ buckets: [], noDate: 0, badDate: 0, total: 0, loading: false, err: null, sampled: false });
      return;
    }
    const myReq = ++reqRef.current;
    setState((s) => ({ ...s, loading: true, err: null }));
    api
      .monthIndex(repoName, dateCol)
      .then((res) => {
        if (myReq !== reqRef.current) return; // superseded by a newer run
        const buckets = res.buckets
          .map(({ key, count }) => ({ key, label: gridMonthLabel(key), count }))
          .sort((a, b) => (a.key < b.key ? 1 : -1)); // newest first
        setState({
          buckets, noDate: res.no_date, badDate: res.bad_date ?? 0, total: res.total,
          loading: false, err: null, sampled: res.sampled,
        });
      })
      .catch((e: Error) => {
        if (myReq !== reqRef.current) return;
        setState((s) => ({ ...s, loading: false, err: e.message }));
      });
  }, [repoName, dateCol]);

  useEffect(() => { run(); }, [run]);
  return state;
}

export default function DocumentBrowserPage() {
  /* THE PATH CARRIES THE INSTANCE, NOT A REPO. `:repo` here used to put
     `incoming-documents-main` in front of the operator on the app's main screen — a name from
     the model where an "instance" was a registered repo. The repo is now an implementation
     detail of the BFF route, resolved server-side; the URL names the instance and the table. */
  const { instance: instanceRouteParam } = useParams<{ instance: string }>();
  /* The BFF is still repo-scoped (`/repos/<repo>/documents/query`), and that is fine — it is an
     API path, not a URL a person reads. The repo name comes from the registry the app already
     loaded, never from a constant in a component and never from the address bar. */
  const { active: repo } = useContext(InstancesContext);
  const navigate = useNavigate();
  const [cfg, setCfg] = useState<RepoConfig | null>(null);
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [total, setTotal] = useState(0);
  /* Starts TRUE. The first fetch is queued in an effect, so a `false` here gives the grid
     one frame in which it has no rows and nothing in flight — and it correctly renders
     "no documents match" over a table that is about to have 39,222. */
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [showUpsert, setShowUpsert] = useState(false);

  const repoName = repo && repo !== 'undefined' ? repo : null;

  /* The detail route as a real URL, resolved through the router so it carries whatever
     basename the app is mounted under (standalone, or `/a/incoming/` inside the console).
     The grid puts this on an <a href>, which is why middle-click, ctrl-click and "copy
     link address" work on a document id — and why the id is a link to a screen reader
     rather than a styled span that happens to be clickable. */
  const docHrefBase = useHref(`/i/${encodeURIComponent(instanceRouteParam ?? '')}/documents`);
  /** THE one constructor of a document route on this page — every click, card and href
   *  goes through it, so repo and id are encoded exactly once, identically, everywhere
   *  (the audit found the same path built 8 ways with 3 encoding rules across the app). */
  const docHref = useCallback(
    (id: string) => `/i/${encodeURIComponent(instanceRouteParam ?? '')}/documents/${encodeURIComponent(id)}`,
    [repo],
  );

  /* DRILL-DOWN (indox-final-plan phase 8). The dashboard's observations are the only place most
     operators look, and until now every one of them was a dead end: a number saying 23 documents
     failed, and no way to reach those 23. `?status=`, `?type=` and `?company=` land here as a
     server-side filter, so an observation opens the table showing EXACTLY the rows it counted —
     not the whole table with the number repeated at the top.

     Read once, into initial state, rather than watched: the table is interactive from the moment it
     loads, and re-imposing the URL's filter on every render would silently undo the operator's own
     next click. The URL is where you ARRIVED, not a lock on where you can go. */
  const [params, setParams] = useSearchParams();

  /* ── WHICH INSTANCE YOU ARE LOOKING AT — IN THE URL, PER USER ─────────────────────────────────
     `?instance=` names a row in public.indox_instances. It is READ HERE and sent with every
     read, so the schema, the columns and the rows all come from that instance.

     Deliberately NOT `active_instance.json`: that file is a single global pointer on the host, so
     one operator switching instance changes what a colleague sees AND what the CLI on that box
     targets. It is a multi-instance bug and is slated for deletion; nothing on this screen reads
     it. The URL is per-user by construction, it is shareable, and it restores the exact screen —
     which is already this console's contract for every other piece of view state. */
  /* ONE PLACE NAMES THE INSTANCE: the path. `?instance=` is accepted as a LEGACY INPUT — old
     links and the redirect carry it — but it is normalised into the path below and then removed,
     so the address bar never shows the same fact twice. Two spellings of one thing in a URL is
     the duplication this whole change exists to remove. */
  const instanceParam = instanceRouteParam || params.get('instance') || null;
  useEffect(() => {
    if (!params.get('instance')) return;
    setParams(
      (prev) => {
        const n = new URLSearchParams(prev);
        n.delete('instance');
        return n;
      },
      { replace: true },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instanceRouteParam]);
  /* WHICH TABLE of that instance the grid is showing. The in-toolbar selector below lists every
     table the instance has — not the two repo entries it used to offer — so this screen browses the
     instance rather than one repo, and the columns, the view and the rows all follow. */
  const tableParam = params.get('table') || null;
  const [instanceTables, setInstanceTables] = useState<{ name: string; rows?: number | null }[]>([]);
  const [instances, setInstances] = useState<
    { id: string; schema_name: string; label?: string; enabled?: boolean }[]
  >([]);
  useEffect(() => {
    let alive = true;
    const inst = instanceParam;
    api
      .instanceTables(inst || (instances.find((x) => x.enabled)?.id ?? ''), true)
      .then((r) => {
        if (alive) setInstanceTables(r.tables || []);
      })
      .catch(() => {
        if (alive) setInstanceTables([]);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instanceParam, instances.length]);

  useEffect(() => {
    let alive = true;
    api
      .listInstances()
      .then((r) => {
        if (alive) setInstances(r.instances || []);
      })
      .catch(() => {
        /* the registry is additive — a BFF that does not serve it simply shows no switcher */
      });
    return () => {
      alive = false;
    };
  }, []);
  /* url-view-state: seed the view from the address ONCE */
  const urlInit = useRef({
    q: params.get('q') ?? '',
    sort: params.get('sort') ?? '',
    page: Math.max(0, parseInt(params.get('page') ?? '1', 10) - 1 || 0),
    size: parseInt(params.get('size') ?? '', 10) || 50,
    view: params.get('view') === 'cards' ? ('cards' as const) : ('table' as const),
  }).current;
  const initialSorting = useMemo(() => {
    const [id, dir] = urlInit.sort.split(':');
    return id ? [{ id, desc: dir === 'desc' }] : [];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  /* [one-selector 2026-08-24, owner order] THE URL IS THE SELECTOR — the single source for
     what the table shows, what a shared link restores, and what every bulk action acts on.
     Drill chips are therefore DERIVED from the params on a stable key (never copied into
     state), and the grid's own column filters are serialized back into the same URL below.
     The stable key keeps the derivation from re-running (and refetching) when the writer
     touches unrelated params like `page`. */
  const drillKey = [
    params.get(DRILL_PARAM.STATUS), params.get(DRILL_PARAM.TYPE), params.get(DRILL_PARAM.COMPANY_ID), params.get(DRILL_PARAM.SOURCE_TYPE),
    ...[...params.entries()].filter(([k]) => k.startsWith('ne_')).map(([k, v]) => `${k}=${v}`),
  ].join('|');
  const drillFilters = useMemo(() => {
    const f: Record<string, { value: unknown; label: string }> = {};
    const st = params.get(DRILL_PARAM.STATUS);
    const ty = params.get(DRILL_PARAM.TYPE);
    const co = params.get(DRILL_PARAM.COMPANY_ID);
    const so = params.get(DRILL_PARAM.SOURCE_TYPE);
    /* The chip is the sentence that explains why this table is narrowed, so it speaks the
       operator's language — the same words the bar they clicked used. The raw enum is kept in
       the chip's `title` so the underlying value is still one hover away. */
    if (st) f.STATUS = { value: st, label: `סטטוס: ${statusLabel(st)}` };
    if (ty) f.TYPE = { value: ty, label: `סוג: ${typeLabel(ty)}` };
    if (co) f.COMPANY_ID = { value: co, label: `חברה: ${co}` };
    /* '__blank__' is the dashboard's sentinel for the no-SOURCE_TYPE bucket (see
       DashboardPage's SOURCE_BLANK): an empty column value cannot round-trip through a
       query parameter, so it arrives as this token and becomes a real is-null clause.
       Sending it through as a literal would filter for the string '__blank__' and open
       an empty table under a chip claiming 159 rows. */
    if (so)
      f.SOURCE_TYPE =
        so === SOURCE_BLANK
          ? { value: { op: 'is_null' }, label: 'מקור: ללא' }
          : { value: so, label: `מקור: ${sourceLabel(so)}` };
    /* `?ne_<COL>=<value>` — subtraction the grid's filters cannot express. A DQ drill like
       "live aging reports" is TYPE=BALANCE_SHEET minus STATUS=OLD. */
    for (const [k, v] of params.entries()) {
      if (!k.startsWith('ne_') || k.length <= 3 || v === '') continue;
      const col = k.slice(3);
      f[col] = { value: { op: 'neq', value: v }, label: `${colLabel(col)} ≠ ${v}` };
    }
    return f;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drillKey]);

  /* Grid-owned URL params — the SAME filters the column popovers edit, round-tripped:
     `f_COL` equals · `has_COL` contains · `in_COL=a,b` enum · `m_COL` month ·
     `empty`/`notempty` column lists. Parsed READ-ONCE into the grid's initial filters
     (the popovers then own them; the writer below re-serializes every change), so a DQ
     link, the visible chips, and the bulk selector are one fact. */
  const initialGridFilters = useRef<Record<string, GridFilterValue> | null>(null);
  if (initialGridFilters.current === null) {
    const g: Record<string, GridFilterValue> = {};
    for (const col of (params.get('empty') || '').split(',').map((s) => s.trim()).filter(Boolean))
      g[col] = { kind: 'text', op: 'empty' };
    for (const col of (params.get('notempty') || '').split(',').map((s) => s.trim()).filter(Boolean))
      g[col] = { kind: 'text', op: 'notEmpty' };
    for (const [k, v] of params.entries()) {
      if (v === '') continue;
      if (k.startsWith('f_') && k.length > 2) g[k.slice(2)] = { kind: 'text', op: 'equals', value: v };
      else if (k.startsWith('has_') && k.length > 4) g[k.slice(4)] = { kind: 'text', op: 'contains', value: v };
      else if (k.startsWith('in_') && k.length > 3)
        g[k.slice(3)] = { kind: 'enum', values: v.split(',').map((s) => s.trim()).filter(Boolean) };
      else if (k.startsWith('m_') && k.length > 2) g[k.slice(2)] = { kind: 'month', key: v };
      /* `gte_COL` / `lte_COL` — range bounds, the DQ-link vocabulary for "everything up to
         the old-document cutoff". One op per column reaches the server (gte wins when both
         appear — same truncation rule the popover's range editor already applies). */
      else if ((k.startsWith('gte_') || k.startsWith('lte_')) && k.length > 4) {
        const col = k.slice(4);
        const prev = g[col];
        const base = prev?.kind === 'range' ? prev : ({ kind: 'range' } as const);
        g[col] = k.startsWith('gte_') ? { ...base, min: v } : { ...base, max: v };
      }
    }
    initialGridFilters.current = g;
  }

  // ── month navigation state ──────────────────────────────────────────────
  /* WHICH date column's month index is loaded. Set by the grid's `onFilterOpen`, i.e. the
     moment a date column's header filter is opened — the column you clicked IS the answer
     to "by which date?", so the separate basis dropdown the old month panel carried has no
     reason to exist. Empty until then, which is the point: the index is a server-side
     aggregate over the whole table and used to run on EVERY page load. */
  const [monthIdxCol, setMonthIdxCol] = useState('');
  const monthIndex = useMonthIndex(repoName, monthIdxCol);

  // combined server filter: URL drill-down chips + the active month + the grid's own column
  // filters, merged into ONE request so e.g. "COMPLETED docs in March whose name contains X"
  // works in a single round trip.
  // The grid's column filters arrive on its state (`onStateChange`). Held separately from `gs`
  // so the memo below can depend on them without depending on page/sort churn.
  const [gridFilters, setGridFilters] = useState<Record<string, GridFilterValue>>(
    initialGridFilters.current ?? {},
  );

  const combinedFilter = useMemo(() => {
    const f: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(drillFilters)) f[k] = v.value;
    // Column filters from the grid. In server mode the grid deliberately does NOT narrow `rows`
    // itself — the server owns filtering — so without this translation the popover would apply,
    // show its chip, and change nothing: the operator would be looking at an unfiltered 6,203 rows
    // believing they had filtered. Every operator below is one the backend already implements
    // (core/models.py QueryOp; supabase_transport._encode_op), so no backend change is needed.
    for (const [k, v] of Object.entries(gridFilters)) {
      if (!v) continue;
      if (v.kind === 'text') {
        if (v.op === 'empty') f[k] = { op: 'is_null' };
        else if (v.op === 'notEmpty') f[k] = { op: 'not_null' };
        else if ((v.value ?? '') !== '') {
          f[k] = v.op === 'equals' ? { op: 'eq', value: v.value } : { op: 'contains', value: v.value };
        }
      } else if (v.kind === 'enum') {
        if (v.values.length === 1) f[k] = { op: 'eq', value: v.values[0] };
        else if (v.values.length > 1) f[k] = { op: 'in', value: v.values };
      } else if (v.kind === 'month') {
        // The month bucket the header picker wrote. `month` is a real backend operator
        // (core/models.py QueryOp), so this stays ONE exact clause — which is exactly why
        // the picker is a first-class kind and not two range bounds: see the range branch.
        f[k] = v.key === GRID_MONTH_NONE ? { op: 'is_null' } : { op: 'month', value: v.key };
      } else if (v.kind === 'range') {
        // PostgREST takes one operator per column per request, so a two-sided range cannot be
        // expressed here. Apply the lower bound (the common "from this date/amount onward" case)
        // and surface the truncation rather than silently dropping half the constraint.
        if (v.min) f[k] = { op: 'gte', value: v.min };
        else if (v.max) f[k] = { op: 'lte', value: v.max };
      }
    }
    return Object.keys(f).length ? f : null;
  }, [drillFilters, gridFilters]);

  // grid query state, driven by DataGrid.onStateChange (server mode)
  const [gs, setGs] = useState<GridState>({
    sorting: [], pageIndex: 0, pageSize: 50, search: '', filters: {},
  });
  const reqIdRef = useRef(0);

  useEffect(() => {
    if (!repoName) return;
    api
      .getRepo(repoName, instanceParam, tableParam)
      .then((r) => setCfg(r.repo))
      .catch((e: Error) => setErr(`Failed to load repo: ${e.message}`));
  }, [repoName]);

  /* the instance's repos, for the in-toolbar selector. A failure just leaves the selector
     with the current repo — navigation degrades, nothing else does. */
  const [repoList, setRepoList] = useState<string[]>([]);
  useEffect(() => {
    let dead = false;
    api.listRepos()
      .then((r) => { if (!dead) setRepoList(r.repos.map((x) => x.name)); })
      .catch(() => {});
    return () => { dead = true; };
  }, []);

  const availableCols = useMemo(
    () => (cfg ? new Set(cfg.columns.map((c) => c.name)) : new Set<string>()),
    [cfg],
  );

  /** Which columns get a month picker in their header filter — every date column this
   *  schema actually has. There is no "default" any more: whichever header you open is
   *  the date you are asking about. */
  const monthCols = useMemo(
    () => new Set(DATE_COL_CANDIDATES.filter((c) => availableCols.has(c.col)).map((c) => c.col)),
    [availableCols],
  );
  // A repo switch invalidates the loaded index — it belongs to the previous table.
  useEffect(() => { setMonthIdxCol(''); }, [repoName]);

  // loadRows reads query state through a ref: late invocations (e.g. the
  // refresh after a slow PATCH) must not refetch with a stale search/sort/page
  // and overwrite a newer view.
  const gsRef = useRef(gs);
  gsRef.current = gs;
  // same stale-closure reasoning as gsRef, but here correctness comes from the
  // effect below depending on `combinedFilter` directly (React runs effects
  // AFTER render, so by the time loadRows fires the ref is already current —
  // no manual re-trigger call needed at the filter-change call sites).
  const filterRef = useRef(combinedFilter);
  filterRef.current = combinedFilter;
  const loadRows = useCallback(() => {
    if (!repoName) return;
    const q = gsRef.current;
    const myReq = ++reqIdRef.current;
    setLoading(true);
    // WHICH COLUMNS THE FREE-TEXT SEARCH SPANS is a property of the columns, declared in the
    // catalog — not a list this component keeps and forgets to update when a column is added.
    const searchCols = (cfg?.columns ?? [])
      .filter((c) => c.searchable && availableCols.has(c.name))
      .map((c) => c.name);
    /* [table timeouts 2026-09-02] PROJECTION. A grid page used to be `select *` — every one of
       ~150 columns per row, the multi-kilobyte selection/debug JSON columns included — for a
       screen that renders the active view's dozen. The page now asks for the view's columns plus
       the fixed set the renderers, the card view and the row actions read regardless of view.
       Every name is checked against the catalog first: the server refuses an unknown identifier
       rather than guessing, and a refused page is worse than a wide one. */
    let select: string[] | undefined;
    if (cfg) {
      const vName = params.get('view') || cfg.view_catalog?.default_view || '';
      const view = cfg.view_catalog?.views?.[vName] ?? null;
      const shown = placementOf(view, cfg.columns).shown;
      const ALWAYS = [cfg.primary_key, 'ID', 'STATUS', 'TYPE', 'NAME', 'LINK', 'THUMBNAIL', 'ERROR',
        'REQUIRED_ACTION', 'COMPANY_ID', 'COMPANY_NAME', 'HASH', 'API_TOOLS_ID', 'SOURCE_TYPE',
        'SYNC_NAME', 'DOC_DATE', 'SHORT_DOC_ID', 'created_at', 'updated_at'];
      select = Array.from(new Set([...ALWAYS, ...shown])).filter((c) => availableCols.has(c));
      if (!select.length) select = undefined;
    }
    api
      .queryDocuments(repoName, {
        select,
        /* mode MUST switch with the filter. The backend applies `filter` only when
           `mode === 'filter'` (backends/supabase.py: `filter=q.filter if q.mode == "filter"`), so
           sending a filter under mode 'all' drops it SILENTLY — the table would return every row
           while the chip above it claimed to be narrowed to 23, and the row count would agree with
           the table rather than with the chip. A screen asserting something the server did not do
           is the precise failure this whole plan exists to remove; it would have been embarrassing
           to reintroduce it in the phase about making the dashboard trustworthy. */
        mode: filterRef.current ? 'filter' : 'all',
        filter: filterRef.current || undefined,
        limit: q.pageSize || 50,
        offset: (q.pageIndex || 0) * (q.pageSize || 50),
        order: q.sorting.map((s) => ({ col: s.key, dir: s.dir })),
        search: q.search || undefined,
        search_columns: q.search ? searchCols : undefined,
        with_count: true,
      }, instanceParam, tableParam)
      .then((res) => {
        if (myReq !== reqIdRef.current) return; // stale response — ignore
        setRows(res.rows as Record<string, unknown>[]);
        setTotal(res.total ?? res.count);
        setErr(null);
      })
      .catch((e: Error) => {
        if (myReq !== reqIdRef.current) return;
        setErr(`Failed to load documents: ${e.message}`);
      })
      .finally(() => {
        if (myReq === reqIdRef.current) setLoading(false);
      });
  }, [repoName, availableCols, instanceParam, tableParam, cfg, params]);

  useEffect(() => {
    if (cfg) loadRows();
  }, [cfg, loadRows, gs, combinedFilter]);

  /* Date columns carry their month buckets into the header filter. Only the column whose
     index is currently loaded gets real buckets; the others advertise the affordance and
     load on open (`onFilterOpen` below), so opening a second date column swaps the index
     rather than holding several expensive aggregates at once. */
  /** A column's Hebrew word, from the schema the BFF already sent. One resolver for the whole
   *  screen, so a header, a filter chip and a bulk-edit verb cannot disagree about a column's
   *  name — which is exactly what two label maps used to allow. */
  const colLabel = useCallback(
    (name: string) => cfg?.columns.find((c) => c.name === name)?.label || name,
    [cfg],
  );

  /* LAYER 2 IN THE URL. `?view=` names one of the catalog's shipped views; absent, the table's
     declared default. The view supplies the column set, their order and their widths — the grid
     itself has no opinion about which columns matter. */
  const viewName = params.get('view') || cfg?.view_catalog?.default_view || '';
  const activeView = useMemo(
    () => (cfg?.view_catalog?.views?.[viewName] ?? null),
    [cfg, viewName],
  );

  const columns = useMemo(() => {
    const base = cfg ? buildColumns(cfg, activeView) : [];
    if (monthCols.size === 0) return base;
    return base.map((c) => {
      if (!monthCols.has(c.key)) return c;
      const loaded = monthIdxCol === c.key;
      return {
        ...c,
        type: 'date' as const,
        filter: 'month' as const,
        months: loaded ? monthIndex.buckets : undefined,
        monthsLoading: loaded ? monthIndex.loading : true,
        monthsNoneCount: loaded ? monthIndex.noDate : 0,
        monthsBadCount: loaded ? monthIndex.badDate : 0,
        monthsSampled: loaded && monthIndex.sampled,
      };
    });
  }, [cfg, monthCols, monthIdxCol, monthIndex.buckets, monthIndex.loading,
      monthIndex.noDate, monthIndex.badDate, monthIndex.sampled]);

  const onCellEdit = useCallback(
    async (rowId: string, key: string, value: unknown) => {
      if (!repoName) throw new Error('no repo');
      await api.patchDocument(repoName, rowId, { [key]: value });
      loadRows(); // refresh so the grid's optimistic overlay reconciles
    },
    [repoName, loadRows],
  );

  // ── selection + pipeline commands ─────────────────────────────────────────
  const [bulkAsk, setBulkAsk] = useState<{ fixed?: DocumentStatus } | null>(null);
  /* [one-selector 2026-08-24, owner order] ONE state datum. The selection is a SELECTOR:
     explicit ids ('ids'), or THE VIEW ITSELF ('filter' — the same combinedFilter that drives
     the grid and lives in the URL) minus explicit exceptions. "בחר את כל התואמים" is
     therefore instant (no id fetching, no client cap, no stale copy); every bulk operation
     sends the selector and the SERVER resolves it once, at execution time. Minimal, clean,
     no leftovers. */
  const [sel, setSel] = useState<
    { kind: 'ids'; ids: string[] } | { kind: 'filter'; except: string[] }
  >({ kind: 'ids', ids: [] });
  const selCount = sel.kind === 'ids' ? sel.ids.length : Math.max(0, total - sel.except.length);
  const selPayload = useCallback((): import('../api').SelectionPayload => {
    if (sel.kind === 'ids') return { ids: sel.ids };
    return {
      filter: (combinedFilter ?? {}) as Record<string, unknown>,
      search: gs.search || undefined,
      search_columns: gs.search
        ? (cfg?.columns ?? []).filter((c) => c.searchable).map((c) => c.name)
        : undefined,
      except: sel.except.length ? sel.except : undefined,
    };
  }, [sel, combinedFilter, gs.search]);
  const [dispatchAsk, setDispatchAsk] = useState(false);
  const [fieldAsk, setFieldAsk] = useState(false);
  const [drainAsk, setDrainAsk] = useState(false);
  /* [archive 2026-08-24, owner order] the `-archive` twin repo: same table + archived_at.
     Inside it the pipeline verbs disappear (a dispatch/drain from the archive would write
     its results straight back into the LIVE table and resurrect rows) and the move button
     points the other way. */
  const [archiveAsk, setArchiveAsk] = useState(false);
  const isArchiveRepo = !!repoName?.endsWith('-archive');
  const [view, setView] = useState<'table' | 'cards'>(urlInit.view);

  /* url-view-state write-back: the address bar mirrors the live view (replace, debounced —
     history stays one entry; back leaves the page, not the keystrokes) */
  const urlSyncTimer = useRef<number | undefined>(undefined);
  useEffect(() => {
    window.clearTimeout(urlSyncTimer.current);
    urlSyncTimer.current = window.setTimeout(() => {
      setParams((p) => {
        const next = new URLSearchParams(p);
        const put = (k: string, v: string, dflt: string) => {
          if (v && v !== dflt) next.set(k, v); else next.delete(k);
        };
        put('q', gs.search ?? '', '');
        const s = gs.sorting?.[0];
        put('sort', s ? `${s.key}:${s.dir}` : '', '');
        put('page', String((gs.pageIndex ?? 0) + 1), '1');
        put('size', String(gs.pageSize ?? 50), '50');
        put('view', view, 'table');
        /* the grid's column filters — wiped and rewritten as a set, so the URL always
           equals the live filters and never accumulates ghosts of removed ones */
        for (const k of [...next.keys()])
          if (/^(f_|has_|in_|m_|gte_|lte_)/.test(k)) next.delete(k);
        next.delete('empty');
        next.delete('notempty');
        const emptyCols: string[] = [];
        const notEmptyCols: string[] = [];
        for (const [k, v] of Object.entries(gridFilters)) {
          if (!v) continue;
          if (v.kind === 'text') {
            if (v.op === 'empty') emptyCols.push(k);
            else if (v.op === 'notEmpty') notEmptyCols.push(k);
            else if ((v.value ?? '') !== '')
              next.set(v.op === 'equals' ? `f_${k}` : `has_${k}`, String(v.value));
          } else if (v.kind === 'enum' && v.values.length) {
            next.set(`in_${k}`, v.values.join(','));
          } else if (v.kind === 'month' && v.key) {
            next.set(`m_${k}`, v.key);
          } else if (v.kind === 'range') {
            if (v.min) next.set(`gte_${k}`, v.min);
            if (v.max) next.set(`lte_${k}`, v.max);
          }
        }
        if (emptyCols.length) next.set('empty', emptyCols.join(','));
        if (notEmptyCols.length) next.set('notempty', notEmptyCols.join(','));
        return next;
      }, { replace: true });
    }, 350);
    return () => window.clearTimeout(urlSyncTimer.current);
  }, [gs.search, gs.sorting, gs.pageIndex, gs.pageSize, view, gridFilters, setParams]);
  const resetSel = useCallback(() => {
    setSel({ kind: 'ids', ids: [] });
  }, []);
  /* A 404/501 from the bulk path means the server predates it — the buttons go quiet with
     a reason rather than a raw error on every selection. Any other failure is a real one. */
  const [bulkUnavailable, setBulkUnavailable] = useState<string | null>(null);
  /* every bulk result goes to the ONE notice channel — and a partial failure is amber, never
     the green callout it used to be painted in */
  const { push } = useToasts();

  const runBulk = useCallback(
    async (status: DocumentStatus) => {
      if (!repoName) throw new Error('no repo');
      try {
        const res = await api.bulkPatchDocuments(repoName, selPayload(), { STATUS: status });
        setBulkAsk(null);
        resetSel();
        if (res.failed.length) {
          push(res.ok ? 'warn' : 'bad',
            `עודכנו ${res.ok.toLocaleString('he-IL')} מסמכים · ${res.failed.length.toLocaleString('he-IL')} נכשלו (${res.failed[0]?.message ?? res.failed[0]?.status})`);
        } else {
          push('ok', `עודכנו ${res.ok.toLocaleString('he-IL')} מסמכים ל-${statusLabel(status)}.`);
        }
        loadRows();
      } catch (e) {
        if (e instanceof ApiError && (e.status === 404 || e.status === 501)) {
          setBulkUnavailable(
            'פעולות אצווה עדיין לא זמינות בשרת הזה (הנתיב documents/bulk אינו קיים). הכפתורים ייפתחו מאליהם כשהשרת יעודכן.',
          );
          setBulkAsk(null);
          return;
        }
        throw e;
      }
    },
    [repoName, loadRows, selPayload, resetSel, push],
  );

  const runDrain = useCallback(async () => {
    const n = selCount;
    try {
      const res = await api.startDrain({ mode: 'ids', repo: repoName ?? undefined, ...selPayload() });
      setDrainAsk(false);
      resetSel();
      /* the accepted drain's OWN fields (`execution_id` / `n8n_url`) — the old read of a
         `drain_execution` key that the server never sent is why the link was never shown */
      push('ok',
        `הניקוז הוצת על ${n.toLocaleString('he-IL')} מסמכים${res.execution_id ? ` · הרצה ${res.execution_id}` : ''}.`,
        res.n8n_url
          ? { label: 'פתח ב-n8n', run: () => { window.open(res.n8n_url as string, '_blank', 'noopener'); } }
          : undefined);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        throw new Error('דריינר כבר רץ (כלל הדריינר היחיד) — המתינו לסיומו ונסו שוב.');
      }
      throw e;
    }
  }, [repoName, selPayload, resetSel, selCount, push]);

  const runDispatch = useCallback(async (action: DispatchAction) => {
    if (!repoName) throw new Error('no repo');
    const res = await api.dispatchDocuments(repoName, selPayload(), action);
    setDispatchAsk(false);
    resetSel();
    const failN = res.failed.reduce((s, f) => s + f.ids.length, 0);
    const text =
      `שוגרו ${res.dispatched.toLocaleString('he-IL')} מסמכים לפעולה ${action}` +
      (failN ? ` · ${failN} נכשלו (${res.failed[0]?.message})` : '') +
      (res.missing.length ? ` · ${res.missing.length} לא נמצאו` : '') +
      ' — עקבו ביומן הפעולות (חותם console_manual).';
    push(failN || res.missing.length ? (res.dispatched ? 'warn' : 'bad') : 'ok', text);
    loadRows();
  }, [repoName, loadRows, selPayload, resetSel, push]);

  const runFieldPatch = useCallback(async (col: string, value: string) => {
    if (!repoName) throw new Error('no repo');
    const res = await api.bulkPatchDocuments(repoName, selPayload(), { [col]: value });
    setFieldAsk(false);
    resetSel();
    // an emptied field says so — "written" for both write and clear hides which one happened
    const verb = value === '' ? `רוקן ${colLabel(col)} עבור` : `נכתב ${colLabel(col)} ל-`;
    if (res.failed.length) {
      push(res.ok ? 'warn' : 'bad',
        `${verb}${res.ok.toLocaleString('he-IL')} מסמכים · ${res.failed.length} נכשלו (${res.failed[0]?.message ?? res.failed[0]?.status})`);
    } else {
      push('ok', `${verb}${res.ok.toLocaleString('he-IL')} מסמכים.`);
    }
    loadRows();
  }, [repoName, loadRows, selPayload, resetSel, push, colLabel]);

  /* [archive 2026-08-24] ONE move, both directions: on the live repo the selection goes
     INTO the twin; on the -archive repo it comes BACK. One server transaction either way;
     conflicts (id already at the destination) are skipped and reported, never overwritten. */
  const runArchiveMove = useCallback(async () => {
    if (!repoName) throw new Error('no repo');
    const res = isArchiveRepo
      ? await api.unarchiveDocuments(repoName, selPayload())
      : await api.archiveDocuments(repoName, selPayload());
    setArchiveAsk(false);
    resetSel();
    const verb = res.direction === 'archive' ? 'הועברו לארכיון' : 'שוחזרו מהארכיון';
    const text =
      `${verb} ${res.moved.toLocaleString('he-IL')} מסמכים` +
      (res.conflicts.length ? ` · ${res.conflicts.length.toLocaleString('he-IL')} דולגו (כבר קיימים ביעד)` : '') +
      (res.missing.length ? ` · ${res.missing.length.toLocaleString('he-IL')} לא נמצאו במקור` : '') +
      ` — היעד: ${res.destination}.`;
    push(res.conflicts.length || res.missing.length ? 'warn' : 'ok', text);
    loadRows();
  }, [repoName, isArchiveRepo, selPayload, resetSel, loadRows, push]);

  /* SERVER-SIDE export: the whole selection, not the visible page. The server walks the
     same selector the bulk endpoints receive and streams the CSV, so 39,283 selected rows
     produce 39,283 data rows — the page's 50 loaded rows are irrelevant to the file. */
  const [exporting, setExporting] = useState(false);
  const exportSelection = useCallback(async () => {
    if (!repoName || exporting) return;
    setExporting(true);
    try {
      const n = selCount;
      const res = await api.exportDocumentsCsv(repoName, selPayload());
      const url = URL.createObjectURL(res.blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = res.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      if (res.truncated) push('warn', `הקובץ נקטע בתקרת הייצוא — הורדו פחות מ-${n.toLocaleString('he-IL')} השורות שנבחרו.`);
      else push('ok', `יוצאו ${n.toLocaleString('he-IL')} מסמכים לקובץ ${res.filename}.`);
    } catch (e) {
      push('bad', `הייצוא נכשל: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setExporting(false);
    }
  }, [repoName, exporting, selCount, selPayload, push]);

  /* url-view-state: removing a chip also removes its URL param — a copied link never
     claims a filter the operator already dismissed. */
  const dropChipParams = useCallback((key: string, value: unknown) => {
    setParams((p) => {
      const next = new URLSearchParams(p);
      if (DRILL_PARAM[key]) next.delete(DRILL_PARAM[key]);
      next.delete(`f_${key}`);
      next.delete(`ne_${key}`);
      const op = (value as { op?: string } | null | undefined)?.op;
      for (const listParam of op === 'is_null' ? ['empty'] : op === 'not_null' ? ['notempty'] : []) {
        const left = (next.get(listParam) || '').split(',').map((s) => s.trim())
          .filter((c) => c && c !== key);
        if (left.length) next.set(listParam, left.join(',')); else next.delete(listParam);
      }
      return next;
    }, { replace: true });
  }, [setParams]);

  /* Chips derive from the URL, so removing one IS a URL edit — nothing else to keep in sync. */
  const removeDrillFilter = useCallback((key: string) => {
    dropChipParams(key, drillFilters[key]?.value);
  }, [dropChipParams, drillFilters]);
  const clearAllFilters = useCallback(() => {
    for (const [k, v] of Object.entries(drillFilters)) dropChipParams(k, v.value);
  }, [dropChipParams, drillFilters]);

  if (!repoName)
    return (
      <div className="callout bad">
        מאגר לא תקין. <Link to="/">חזרה ללוח הבקרה</Link>.
      </div>
    );
  if (err && !cfg)
    return (
      <div className="callout bad">
        <div style={{ fontWeight: 700, marginBottom: 4 }}>{err}</div>
        <Link to="/">חזרה ללוח הבקרה</Link>
      </div>
    );
  if (!cfg) return <div className="spin">טוען…</div>;
  const src = repoSource(cfg);
  const pk = cfg.primary_key;

  return (
    /* page-fill: this page hands the grid the leftover height instead of stacking a fixed-height
       grid under a header and hoping the sum fits the viewport. */
    <div className="page-fill">
      {showUpsert && (
        <UpsertDrawer
          cfg={cfg}
          onDone={() => loadRows()}
          onClose={() => setShowUpsert(false)}
        />
      )}
      {bulkAsk && (
        <BulkStatusModal
          ids={sel.kind === 'ids' ? sel.ids : []}
          count={selCount}
          rows={rows}
          pk={pk}
          fixed={bulkAsk.fixed}
          onCancel={() => setBulkAsk(null)}
          onConfirm={(status) => runBulk(status)}
        />
      )}
      {dispatchAsk && (
        <DispatchModal n={selCount} onCancel={() => setDispatchAsk(false)}
          onConfirm={(action) => runDispatch(action)} />
      )}
      {fieldAsk && (
        <FieldEditModal n={selCount} cfg={cfg} onCancel={() => setFieldAsk(false)}
          onConfirm={(col, value) => runFieldPatch(col, value)} />
      )}
      {drainAsk && (
        <BulkOpModal
          title="הרצת Drain על הבחירה"
          n={selCount}
          confirmLabel="הצת ניקוז"
          onCancel={() => setDrainAsk(false)}
          onConfirm={() => runDrain()}
        >
          <p className="small" style={{ margin: '0 0 10px', lineHeight: 1.6 }}>
            ‏drain במצב ids: כל מסמך נבחר עובר decide ומקבל את הפעולה הבאה שלו, ב-4 ליינים
            במקביל לצד הטיקים (קבלה גלובלית משותפת). כלל הדריינר-היחיד נאכף בשרת.
          </p>
        </BulkOpModal>
      )}
      {archiveAsk && (
        <BulkOpModal
          title={isArchiveRepo ? 'שחזור מהארכיון' : 'העברה לארכיון'}
          n={selCount}
          confirmLabel={isArchiveRepo ? 'שחזר לטבלה החיה' : 'העבר לארכיון'}
          onCancel={() => setArchiveAsk(false)}
          onConfirm={() => runArchiveMove()}
        >
          <p className="small" style={{ margin: '0 0 10px', lineHeight: 1.6 }}>
            {isArchiveRepo
              ? 'השורות יחזרו לטבלה החיה בדיוק כפי שהן (בלי archived_at). מזהה שכבר קיים בטבלה החיה ידולג וידווח — לעולם לא נדרס.'
              : 'השורות יעברו לטבלת הארכיון וייצאו מהטבלה החיה ומכל העיבודים. טרנזקציה אחת — כל שורה או עוברת בשלמותה או נשארת; שחזור זמין בכל רגע מתצוגת הארכיון.'}
          </p>
        </BulkOpModal>
      )}
      {/* [2026-08-24, owner order] No strip above the table — the table IS the screen.
          Repo identity became the selector in the grid's own toolbar (backend/table/key
          one hover away on it), drill-downs became grid chips, and the link/view controls
          moved into the toolbar's end. */}
      {err && <div className="callout bad">{err}</div>}
      {monthIndex.err && (
        <div className="callout bad">נכשל חישוב חלוקת החודשים: {monthIndex.err}</div>
      )}
      {bulkUnavailable && (
        <div className="callout warn" style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
          <span>{bulkUnavailable}</span>
          <button className="link" onClick={() => setBulkUnavailable(null)}>נסו שוב</button>
        </div>
      )}
      <DataGrid
        mode="server"
        label="מסמכים"
        columns={columns}
        rows={rows}
        rowCount={total}
        loading={loading}
        getRowId={(r) => String(r[pk] ?? '')}
        rowHeaderKey={pk}
        /* ROW OPEN. Both halves are wired: a real <a href> the browser can activate on its
           own (and Enter on the focused row), and this SPA navigation for the plain click. */
        getRowHref={(r) => `${docHrefBase}/${encodeURIComponent(String(r[pk] ?? ''))}`}
        onRowOpen={(r) => {
          const id = String(r[pk] ?? '');
          if (id) navigate(docHref(id));
        }}
        selectable
        /* ONE SELECTOR: the grid's checkboxes read/write the page's `sel` directly. The
           header checkbox selects ALL rows matching the current filter (kind 'filter'),
           and the same object is what every bulk endpoint receives. */
        selection={sel}
        onSelectionModelChange={setSel}
        /* THE TABLE SWITCHER. It used to offer the two REPO entries (main and its archive),
           which is why the console could only ever see two of the instance's seventeen tables.
           It now lists every table the selected instance has, with its real row count, and
           switching writes `?table=` — the columns, the view and the rows all follow from the
           catalog, so a table this screen has never heard of still renders. */
        toolbarStart={
          <select
            className="reposel"
            value={tableParam ?? (cfg.supabase?.table || '')}
            onChange={(e) => {
              const next = e.target.value;
              setParams(
                (prev) => {
                  const n = new URLSearchParams(prev);
                  if (next) n.set('table', next);
                  else n.delete('table');
                  n.delete('page');
                  n.delete('view');
                  return n;
                },
                { replace: false },
              );
            }}
            title={`${cfg.backend} · ${src.label} · מפתח ${pk}`}
            aria-label="בחירת טבלה"
          >
            {(instanceTables.length
              ? instanceTables
              : [{ name: cfg.supabase?.table || repoName || '', rows: null }]
            ).map((tb) => (
              <option key={tb.name} value={tb.name}>
                {tb.name}
                {typeof tb.rows === 'number' ? ` · ${tb.rows.toLocaleString('he-IL')}` : ''}
              </option>
            ))}
          </select>
        }
        extraChips={[
          ...Object.entries(drillFilters).map(([k, v]) => ({
            label: v.label,
            title: `${k} = ${JSON.stringify(v.value)}`,
            onClear: () => removeDrillFilter(k),
          })),
          ...(Object.keys(drillFilters).length > 1
            ? [{ label: 'נקה את כל הסינונים', onClear: clearAllFilters }]
            : []),
        ]}
        toolbarEnd={
          <>
            <button
              className="btn ghost sm dg-pgbtn"
              title="העתקת קישור שמשחזר בדיוק את התצוגה הזו — סינון, חיפוש, מיון, עמוד ומצב תצוגה"
              aria-label="העתק קישור לתצוגה"
              onClick={() => {
                const url = shareUrl();
                if (!navigator.clipboard) { push('warn', `הלוח אינו זמין בדפדפן הזה — הקישור: ${url}`); return; }
                navigator.clipboard.writeText(url)
                  .then(() => push('ok', 'קישור לתצוגה הנוכחית הועתק ללוח.'))
                  .catch(() => push('warn', `ההעתקה ללוח נדחתה — הקישור: ${url}`));
              }}
            >
              <Ic p={IC_LINK} />
            </button>
            <div className="winseg" role="tablist" aria-label="מצב תצוגה">
              <button className={view === 'table' ? 'on' : ''} onClick={() => setView('table')}>טבלה</button>
              <button className={view === 'cards' ? 'on' : ''} onClick={() => setView('cards')}>כרטיסים</button>
            </div>
          </>
        }
        selectionActions={() => {
          const n = selCount;
          return (
            <>
              {!isArchiveRepo && (
                <>
                  <button
                    className="btn sm"
                    disabled={!!bulkUnavailable}
                    title={
                      bulkUnavailable ??
                      `שינוי STATUS ל-ACTION_RESTART עבור ${n} מסמכים — ${RESTART_NOTE}`
                    }
                    onClick={() => setBulkAsk({ fixed: 'ACTION_RESTART' })}
                  >
                    בקש עיבוד מחדש
                  </button>
                  <button
                    className="btn ghost sm"
                    title={`decide + הפעולה הבאה לכל אחד מ-${n} הנבחרים, ב-4 ליינים`}
                    onClick={() => setDrainAsk(true)}
                  >
                    הרץ ב-Drain
                  </button>
                  <button
                    className="btn ghost sm"
                    title="שיגור פעולה ספציפית ישירות לראוטר, בלי decide"
                    onClick={() => setDispatchAsk(true)}
                  >
                    הרץ פעולה…
                  </button>
                </>
              )}
              <button
                className="btn ghost sm"
                title={isArchiveRepo
                  ? 'החזרת הנבחרים לטבלה החיה — טרנזקציה אחת, קונפליקטים מדולגים ומדווחים'
                  : 'העברת הנבחרים לטבלת הארכיון — יוצאים מהטבלה החיה ומכל העיבודים; שחזור זמין תמיד'}
                onClick={() => setArchiveAsk(true)}
              >
                {isArchiveRepo ? 'שחזר מהארכיון' : 'העבר לארכיון'}
              </button>
              <button
                className="btn ghost sm"
                disabled={!!bulkUnavailable}
                title={bulkUnavailable ?? 'כתיבת STATUS אחד לכל הנבחרים דרך נתיב ה-PATCH של השרת'}
                onClick={() => setBulkAsk({})}
              >
                שנה סטטוס…
              </button>
              <button
                className="btn ghost sm"
                disabled={!!bulkUnavailable}
                title={bulkUnavailable ?? 'כתיבת ערך לעמודה כלשהי עבור כל הנבחרים'}
                onClick={() => setFieldAsk(true)}
              >
                ערוך שדה…
              </button>
              <button
                className="btn ghost sm"
                disabled={exporting}
                title="הורדת כל הנבחרים כקובץ CSV מהשרת (כל העמודות) — כולל שורות שאינן בעמוד הנוכחי"
                onClick={() => exportSelection()}
              >
                {exporting ? 'מייצא…' : 'ייצוא CSV'}
              </button>
            </>
          );
        }}
        /* Load a date column's month index the first time its filter is opened. Idempotent:
           re-opening the same column is a no-op, so the aggregate runs once per column per
           visit rather than on every mount the way the old always-on panel did. */
        onFilterOpen={(k) => { if (monthCols.has(k)) setMonthIdxCol(k); }}
        onStateChange={(s) => {
          setGs((prev) =>
            prev.pageIndex === s.pageIndex &&
            prev.pageSize === s.pageSize &&
            prev.search === s.search &&
            JSON.stringify(prev.sorting) === JSON.stringify(s.sorting)
              ? prev
              : s,
          );
          // Pull the grid's column filters out into their own state so `combinedFilter` can
          // translate them into backend FilterClauses. Without this the popover applies and
          // shows a chip while the server keeps returning every row.
          setGridFilters((prev) =>
            JSON.stringify(prev) === JSON.stringify(s.filters) ? prev : s.filters,
          );
        }}
        onCellEdit={onCellEdit}
        onAddRow={() => setShowUpsert(true)}
        addRowLabel="הוסף / עדכן שורה"
        searchPlaceholder="חיפוש חופשי בשם, חברה, סוג, סטטוס…"
        emptyMessage="אין מסמכים התואמים לסינון הנוכחי."
        initialPageSize={urlInit.size}
        initialSearch={urlInit.q}
        initialSorting={initialSorting}
        initialPageIndex={urlInit.page}
        initialFilters={initialGridFilters.current ?? undefined}
        height={view === 'cards' ? 0 : 620}
      />
      {view === 'cards' && (
        <>
          {/* [2026-08-24, owner order] CARD VIEW with a REAL thumbnail: apitools' rasterised
              page (the same image the document screen shows), THUMBNAIL as fallback, an icon
              when neither exists. Same server page, same selection — the grid above still owns
              search/filters/paging; its table body is collapsed (height 0) while cards render. */}
          {/* the cards' own selection bar — same one-selector semantics as the table header:
              the checkbox always means the WHOLE matching set. */}
          <div className="toolbar" style={{ margin: '10px 0' }}>
            <label className="small" style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={sel.kind === 'filter' && sel.except.length === 0 && total > 0}
                ref={(el) => {
                  if (el) el.indeterminate = selCount > 0 && !(sel.kind === 'filter' && sel.except.length === 0);
                }}
                onChange={(e) =>
                  setSel(e.target.checked ? { kind: 'filter', except: [] } : { kind: 'ids', ids: [] })
                }
              />
              בחר את כל {total.toLocaleString('he-IL')} התואמים
            </label>
          {selCount > 0 && (
            <>
              <span className="pill ok num">{selCount.toLocaleString('he-IL')} נבחרו</span>
              {!isArchiveRepo && (
                <>
                  <button className="btn sm" onClick={() => setBulkAsk({ fixed: 'ACTION_RESTART' })}>בקש עיבוד מחדש</button>
                  <button className="btn ghost sm" onClick={() => setDrainAsk(true)}>הרץ ב-Drain</button>
                  <button className="btn ghost sm" onClick={() => setDispatchAsk(true)}>הרץ פעולה…</button>
                </>
              )}
              <button className="btn ghost sm" onClick={() => setArchiveAsk(true)}>
                {isArchiveRepo ? 'שחזר מהארכיון' : 'העבר לארכיון'}
              </button>
              <button className="btn ghost sm" onClick={() => setBulkAsk({})}>שנה סטטוס…</button>
              <button className="btn ghost sm" onClick={() => setFieldAsk(true)}>ערוך שדה…</button>
              <button className="btn ghost sm" disabled={exporting} onClick={() => exportSelection()}>
                {exporting ? 'מייצא…' : 'ייצוא CSV'}
              </button>
              <button className="link" onClick={resetSel}>נקה</button>
            </>
          )}
          </div>
          <div className="doccards">
            {rows.map((r) => {
              const id = String(r[pk] ?? '');
              const selected = sel.kind === 'filter' ? !sel.except.includes(id) : sel.ids.includes(id);
              const st = String(r.STATUS ?? '');
              return (
                <div key={id} className={`doccard${selected ? ' sel' : ''}`}>
                  <label className="doccard-check">
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={(e) => {
                        setSel((prev) => {
                          if (prev.kind === 'filter') {
                            // in all-matching mode a card toggle edits the EXCEPT list
                            const except = e.target.checked
                              ? prev.except.filter((x) => x !== id)
                              : [...new Set([...prev.except, id])];
                            return { kind: 'filter', except };
                          }
                          return {
                            kind: 'ids',
                            ids: e.target.checked
                              ? [...new Set([...prev.ids, id])]
                              : prev.ids.filter((x) => x !== id),
                          };
                        });
                      }}
                    />
                  </label>
                  <button
                    className="doccard-img"
                    onClick={() => navigate(docHref(id))}
                    title={`פתיחת המסמך · ${String(r.NAME ?? id)}`}
                  >
                    {/* the thumbnail ENDPOINT (small raster); a 404 = no preview yet, drawn as
                        the explained fallback — the THUMBNAIL column is retired */}
                    <img
                      src={api.documentThumbnailUrl(id)}
                      alt=""
                      loading="lazy"
                      onError={(e) => {
                        const img = e.currentTarget;
                        img.style.display = 'none';
                        img.parentElement?.classList.add('noimg');
                      }}
                    />
                    <span className="doccard-fallback">
                      <span aria-hidden="true" style={{ display: 'inline-flex', width: 28, height: 28 }}><Ic p={IC.file} /></span>
                      <span className="small muted">אין תצוגה מקדימה עדיין</span>
                    </span>
                  </button>
                  <div className="doccard-body">
                    <div className="doccard-name">{String(r.NAME ?? id)}</div>
                    <div className="doccard-meta">
                      <span className={`pill ${statusKind(st)}`} title={statusTitle(st)}>{statusLabel(st)}</span>
                      {r.TYPE ? <span className="tag">{typeLabel(r.TYPE)}</span> : null}
                    </div>
                    <div className="doccard-sub">
                      {String(r.COMPANY_NAME ?? '') || '—'}
                      {r.DOC_DATE ? ` · ${String(r.DOC_DATE)}` : ''}
                    </div>
                  </div>
                </div>
              );
            })}
            {!rows.length && !loading && (
              <div className="empty">אין מסמכים התואמים לסינון הנוכחי.</div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
