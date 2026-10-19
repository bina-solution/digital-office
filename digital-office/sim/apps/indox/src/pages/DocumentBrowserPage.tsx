import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, RepoConfig, repoSource, ColumnDef } from '../api';
import { IC, Ic, XIcon } from '../icons';
import { kindOf, wordOf } from '../words';
import BinaTable, {
  BinaColumn,
  BinaTableState,
  escapeHtml,
  pillHtml,
} from '../components/BinaTable';

// Curated default-visible columns (identity + lifecycle + key extraction
// fields). Any other column loads hidden and can be re-shown from the picker.
const DEFAULT_VISIBLE = [
  'ID', 'NAME', 'COMPANY_ID', 'COMPANY_NAME', 'SHORT_DOC_ID', 'TYPE', 'STATUS',
  'REQUIRED_ACTION', 'DOC_DATE', 'DOC_TOTAL_AMOUNT', 'SOURCE_TYPE', 'TIMESTAMP',
];
// Text columns the free-text server search ILIKEs across.
const SEARCH_COLS = [
  'ID', 'NAME', 'COMPANY_NAME', 'SHORT_DOC_ID', 'TYPE', 'STATUS',
  'SOURCE_TYPE', 'REQUIRED_ACTION',
];

// status → pill kind (same semantics as the dashboard)
function statusKind(v: unknown): 'ok' | 'warn' | 'bad' | 'muted' {
  const s = String(v ?? '').toUpperCase();
  if (s === 'COMPLETED') return 'ok';
  if (s === 'EXTRACTION_FAILED' || s === 'MAX_ITERATIONS') return 'bad';
  if (s === 'DOUBLE' || s === 'OLD') return 'muted';
  return 'warn';
}

function buildColumns(cfg: RepoConfig): BinaColumn[] {
  const pk = cfg.primary_key;
  const cols: ColumnDef[] = cfg.columns;
  const visUpper = new Set(DEFAULT_VISIBLE.map((s) => s.toUpperCase()));
  const matched = cols.filter((c) => visUpper.has(c.name.toUpperCase()));
  // If the schema doesn't overlap our curated set, don't hide anything.
  const curate = matched.length >= 3;
  return cols.map((c) => {
    const u = c.name.toUpperCase();
    const isPk = c.name === pk;
    const isStatus = u === 'STATUS';
    // how the column READS came with it (words.tsx): its heading and, for a value domain, the word and the colour
    // of each value. The value itself is untouched: editing, sorting and the search still see it.
    const domain = !!c.enum_values;
    return {
      key: c.name,
      label: c.label || c.name,
      editable: !isPk,
      width: isPk ? 170 : c.name.length > 18 ? 200 : 160,
      hidden: curate && !visUpper.has(u),
      align: /(AMOUNT|TOTAL|PRICE|SUM|QTY|QUANTITY|COUNT|VAT|_NUM$)/.test(u)
        ? ('end' as const)
        : undefined,
      // pk cell = the row-open affordance (link-styled; onRowClick fires on it)
      ...(isPk
        ? { html: (v: unknown) => `<span class="bt-link">${escapeHtml(v)}</span>` }
        : {}),
      ...(domain
        ? {
            html: (v: unknown) =>
              v == null || v === ''
                ? ''
                : isStatus || kindOf(c, v)
                  ? pillHtml(wordOf(c, v), kindOf(c, v) ?? statusKind(v))
                  : escapeHtml(wordOf(c, v)),
          }
        : isStatus
          ? { html: (v: unknown) => pillHtml(v, statusKind(v)) }
          : {}),
    };
  });
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
  const [result, setResult] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setErr(null);
    setResult(null);
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
      setResult(`${res.stats.created} נוצרו,${res.stats.updated} עודכנו, ${res.stats.noop} ללא שינוי`);
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
            <button onClick={onClose} className="icbtn" aria-label="סגירה" title="סגירת החלון בלי לשמור"><XIcon /></button>
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
                מלאו את השדות למטה. אם «{cfg.columns.find((c) => c.name === cfg.primary_key)?.label || cfg.primary_key}» כבר קיים השורה <strong>תעודכן</strong>; אחרת <strong>תיווצר</strong>.
              </p>
              {cfg.columns.map((c) => (
                <div key={c.name} className="field">
                  {/* headed as the table heads the column; its name in the database and its type are one hover away */}
                  <label title={`${c.name} · ${c.type}`}>
                    {c.label || <span className="mono">{c.name}</span>}
                    {c.name === cfg.primary_key && (
                      <span className="tag pk" style={{ marginInlineStart: 4 }}>מפתח</span>
                    )}
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
          {result && <div className="callout ok">{result}</div>}
          <button onClick={submit} disabled={busy} className="btn" style={{ width: '100%', justifyContent: 'center' }}>
            {busy ? 'שומר…' : 'הוסף / עדכן'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function DocumentBrowserPage() {
  const { repo } = useParams<{ repo: string }>();
  const navigate = useNavigate();
  const [cfg, setCfg] = useState<RepoConfig | null>(null);
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showUpsert, setShowUpsert] = useState(false);

  const repoName = repo && repo !== 'undefined' ? repo : null;

  // grid query state, driven by BinaTable.onState (server mode)
  const [gs, setGs] = useState<BinaTableState>({
    page: 1, pageSize: 50, search: '', sort: null,
  });
  const reqIdRef = useRef(0);

  useEffect(() => {
    if (!repoName) return;
    api
      .getRepo(repoName)
      .then((r) => setCfg(r.repo))
      .catch((e: Error) => setErr(`Failed to load repo: ${e.message}`));
  }, [repoName]);

  const availableCols = useMemo(
    () => (cfg ? new Set(cfg.columns.map((c) => c.name)) : new Set<string>()),
    [cfg],
  );

  // loadRows reads query state through a ref: late invocations (e.g. the
  // refresh after a slow PATCH) must not refetch with a stale search/sort/page
  // and overwrite a newer view.
  const gsRef = useRef(gs);
  gsRef.current = gs;
  const loadRows = useCallback(() => {
    if (!repoName) return;
    const q = gsRef.current;
    const myReq = ++reqIdRef.current;
    setLoading(true);
    const searchCols = SEARCH_COLS.filter((c) => availableCols.has(c));
    api
      .queryDocuments(repoName, {
        mode: 'all',
        limit: q.pageSize ?? 50,
        offset: ((q.page ?? 1) - 1) * (q.pageSize ?? 50),
        order: q.sort ? [{ col: q.sort.key, dir: q.sort.dir }] : [],
        search: q.search || undefined,
        search_columns: q.search ? searchCols : undefined,
        with_count: true,
      })
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
  }, [repoName, availableCols]);

  useEffect(() => {
    if (cfg) loadRows();
  }, [cfg, loadRows, gs]);

  const columns = useMemo(() => (cfg ? buildColumns(cfg) : []), [cfg]);

  const onCellEdit = useCallback(
    async (rowId: string, key: string, value: unknown) => {
      if (!repoName) throw new Error('no repo');
      await api.patchDocument(repoName, rowId, { [key]: value });
      loadRows(); // refresh so the grid's optimistic overlay reconciles
    },
    [repoName, loadRows],
  );

  if (!repoName)
    return (
      <div className="callout bad">
        מאגר לא תקין. <Link to="/">חזרה למאגרים</Link>.
      </div>
    );
  if (err && !cfg)
    return (
      <div className="callout bad">
        <div style={{ fontWeight: 700, marginBottom: 4 }}>{err}</div>
        <Link to="/">חזרה למאגרים</Link>
      </div>
    );
  if (!cfg) return <div className="spin">טוען…</div>;
  const src = repoSource(cfg);

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
      {/* This strip carries what the removed "repo detail" screen used to show one click away —
          backend, target table, primary key and row count. Promoting it here means
          the information is always visible instead of costing a navigation. */}
      <div className="toolbar">
        {/* The reading line says what a person reads: the screen's name and how many documents. Where they
            are kept — the backend, the table, its key — stood here as «supabase · public.incoming_documents ·
            מפתח: ID»; it is one hover away now, and the way to the source keeps its link. */}
        <h1 title={`${cfg.backend} · ${src.label} · מפתח ${cfg.primary_key}`}>מסמכים</h1>
        <span className="muted small">
          <span className="num">{total.toLocaleString('he-IL')}</span> מסמכים
        </span>
        {src.url && (
          <a href={src.url} target="_blank" rel="noreferrer" className="src small" title={src.label}>
            פתיחת המקור <Ic p={IC.external} />
          </a>
        )}
      </div>
      {err && <div className="callout bad">{err}</div>}
      <BinaTable
        fill
        mode="server"
        tableId={`docs:${repoName}`}
        columns={columns}
        data={rows}
        rowCount={total}
        loading={loading}
        rowKey={cfg.primary_key}
        pageSize={50}
        selectable
        columnPicker
        onState={setGs}
        onEdit={async (id, key, value) => onCellEdit(String(id), key, value)}
        onAddRow={() => setShowUpsert(true)}
        addLabel="הוסף / עדכן שורה"
        onRowClick={(r, colKey) => {
          // editable grid: open only from the ID (link-styled) column
          if (colKey !== cfg.primary_key) return;
          const id = String(r[cfg.primary_key] ?? '');
          if (id) navigate(`/repos/${repo}/documents/${encodeURIComponent(id)}`);
        }}
        searchPlaceholder="חיפוש במסמכים…"   /* (it listed four fields and was cut in the middle of the fourth: «…סוג, סטט») */
        height={620}
      />
    </div>
  );
}
