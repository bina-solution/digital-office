import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  api,
  ExtractionDataset,
  ExtractionDoc,
  ExtractionResult,
  ExtractionRun,
  ExtractionRunFull,
} from '../api';
import { ask } from '../ask';
import { IC, Ic } from '../icons';

// חילוץ מסמכים — dataset-based extraction over the live JsonQueryExV3 n8n
// workflows: one apitools /documentJsonQuery call per extracted value, queries
// loaded from the settings q_v3_* rows. This page lists the grounded demo
// dataset, runs extraction (selected / all), scores vs ground truth, and links
// into the per-document view (original ↔ drawn overlay).
const POLL_MS = 1500;

const TYPE_PILL: Record<string, string> = {
  invoice: 'ok',
  shipment: 'warn',
  balance_sheet: 'unset',
  upload: 'degraded',
};

export function typeLabel(d: { type: string; type_label?: string }): string {
  return d.type_label || d.type;
}

export const SCOPE_LABEL: Record<string, string> = {
  all: 'הכל',
  selected: 'נבחרים',
  single: 'מסמך יחיד',
  upload: 'העלאה',
};

export function fmtTime(ts?: number | null): string {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString('he-IL', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function fmtDuration(run: { started: number; finished: number | null }): string {
  if (!run.finished) return '—';
  const s = Math.max(0, run.finished - run.started);
  if (s < 90) return `${s.toFixed(0)}s`;
  return `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')} דק'`;
}

export function RunStatusPill({ run }: { run: ExtractionRun }) {
  if (run.status === 'running')
    return (
      <span className="pill warn">
        <span className="spinner" style={{ marginInlineEnd: 6 }} /> מריץ…
      </span>
    );
  if (run.status === 'done')
    return <span className={`pill ${run.errors === 0 ? 'ok' : 'warn'}`}>הסתיים</span>;
  if (run.status === 'cancelled') return <span className="pill muted">בוטל</span>;
  return <span className="pill muted">נקטע</span>;
}

/** score pill for one doc result (ok/total vs truth) */
export function ScorePill({ r }: { r: ExtractionResult | null | undefined }) {
  if (!r) return <span className="muted small">לא הורץ</span>;
  if (r.error) return <span className="pill bad">שגיאה</span>;
  if (r.total === 0) return <span className="pill muted">ללא אמת</span>;
  const all = r.ok === r.total;
  return (
    <span className={`pill ${all ? 'ok' : 'bad'}`}>
      <span className="num">
        {r.ok}/{r.total}
      </span>
    </span>
  );
}

/** compact got-vs-truth line for the list/cards */
export function ValueSummary({ r }: { r: ExtractionResult }) {
  const scored = r.values.filter((v) => v.ok !== null);
  return (
    <span className="small" style={{ display: 'inline-flex', gap: 10, flexWrap: 'wrap' }}>
      {scored.map((v) => (
        <span key={v.field} style={{ whiteSpace: 'nowrap' }}>
          <span style={{ color: v.ok ? 'var(--accent-d)' : 'var(--red)', fontWeight: 700, display: 'inline-flex', verticalAlign: '-2px' }}
                title={v.ok ? 'תואם לאמת-היסוד' : 'שונה מאמת-היסוד'} aria-label={v.ok ? 'תואם' : 'שונה'}>
            <Ic p={v.ok ? IC.check : IC.x} />
          </span>{' '}
          <span className="muted">{v.field}</span>{' '}
          <span className="num">{v.got ?? '—'}</span>
        </span>
      ))}
    </span>
  );
}

export default function ExtractionPage() {
  const [data, setData] = useState<ExtractionDataset | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [view, setView] = useState<'list' | 'cards'>('list');
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [run, setRun] = useState<ExtractionRun | null>(null);
  const [startErr, setStartErr] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [runs, setRuns] = useState<ExtractionRun[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [viewRun, setViewRun] = useState<ExtractionRunFull | null>(null);
  const navigate = useNavigate();

  const runIdRef = useRef<string | null>(null);
  const pollTimer = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
  const fileInput = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await api.getExtractionDataset();
      setData(d);
      setLoadErr(null);
    } catch (e: unknown) {
      setLoadErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const loadRuns = useCallback(async () => {
    try {
      const { runs: rs } = await api.listExtractionRuns();
      setRuns(rs);
      // resume the live panel after a page reload mid-run
      const active = rs.find((r) => r.status === 'running');
      if (active && !runIdRef.current) {
        runIdRef.current = active.run_id;
        setRun(active);
        stopPolling();
        pollTimer.current = setInterval(pollRun, POLL_MS);
      }
    } catch {
      /* history is auxiliary — never blocks the page */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
    loadRuns();
  }, [load, loadRuns]);

  const stopPolling = useCallback(() => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = undefined;
    }
  }, []);
  useEffect(() => () => stopPolling(), [stopPolling]);

  const pollRun = useCallback(async () => {
    const id = runIdRef.current;
    if (!id) return;
    try {
      const r = await api.getExtractionRun(id);
      setRun(r);
      load(); // refresh per-doc results as they land
      if (r.status !== 'running') {
        stopPolling();
        runIdRef.current = null;
        api.listExtractionRuns().then(({ runs: rs }) => setRuns(rs)).catch(() => {});
      }
    } catch {
      stopPolling();
      runIdRef.current = null;
    }
  }, [load, stopPolling]);

  const start = useCallback(
    async (ids?: string[]) => {
      if (runIdRef.current) return;
      setStartErr(null);
      setViewRun(null); // a new run always shows live results
      try {
        const { run_id, docs_total } = await api.startExtractionRun(ids);
        runIdRef.current = run_id;
        setRun({
          run_id,
          status: 'running',
          docs_total,
          done: 0,
          ok: 0,
          total: 0,
          errors: 0,
          current: null,
          started: Date.now() / 1000,
          finished: null,
        });
        stopPolling();
        pollTimer.current = setInterval(pollRun, POLL_MS);
      } catch (e: unknown) {
        setStartErr(e instanceof Error ? e.message : String(e));
      }
    },
    [pollRun, stopPolling],
  );

  const cancel = useCallback(async () => {
    const id = runIdRef.current;
    if (!id) return;
    try {
      await api.cancelExtractionRun(id);
    } catch {
      /* poll will surface state */
    }
  }, []);

  const onUpload = useCallback(
    async (f: File | null) => {
      if (!f) return;
      setUploading(true);
      setStartErr(null);
      try {
        const rec = await api.uploadExtractionDoc(f);
        await load();
        navigate(`/extraction/${rec.id}`);
      } catch (e: unknown) {
        setStartErr(e instanceof Error ? e.message : String(e));
      } finally {
        setUploading(false);
        if (fileInput.current) fileInput.current.value = '';
      }
    },
    [load, navigate],
  );

  const allDocs: ExtractionDoc[] = useMemo(() => {
    if (!data) return [];
    return [...data.docs, ...data.uploads];
  }, [data]);

  // the result shown per doc: a selected historical run's, or the latest
  const effResult = useCallback(
    (d: ExtractionDoc): ExtractionResult | null =>
      viewRun ? viewRun.results[d.id] ?? null : d.result,
    [viewRun],
  );

  const openRun = useCallback(async (runId: string) => {
    try {
      const full = await api.getExtractionRunFull(runId);
      setViewRun(full);
    } catch (e: unknown) {
      setStartErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  // (asked first, in the live app's own words for it — it was the one removal here that asked nothing)
  const deleteRun = useCallback(
    async (h: ExtractionRun) => {
      const runId = h.run_id;
      if (!(await ask({
        title: 'מחיקת הרצת חילוץ', ok: 'מחק את ההרצה', danger: true,
        body: `ההרצה מ-${fmtTime(h.started)} ותוצאותיה יימחקו — הן לא יופיעו עוד בהיסטוריית ההרצות. המסמכים עצמם אינם נוגעים. אין ביטול.`,
        facts: [['היקף', SCOPE_LABEL[h.scope || ''] || h.scope || '—'], ['מסמכים', `${h.done}/${h.docs_total}`],
                ['ציון', h.total > 0 ? `${h.ok}/${h.total}` : '—'], ['שגיאות', String(h.errors || 0)]],
      }))) return;
      try {
        await api.deleteExtractionRun(runId);
        setRuns((prev) => prev.filter((r) => r.run_id !== runId));
        setViewRun((prev) => (prev?.run_id === runId ? null : prev));
      } catch (e: unknown) {
        setStartErr(e instanceof Error ? e.message : String(e));
      }
    },
    [],
  );

  const filtered = useMemo(() => {
    let list = allDocs;
    if (typeFilter !== 'all') list = list.filter((d) => d.type === typeFilter);
    const q = search.trim().toLowerCase();
    if (q) list = list.filter((d) => d.file.toLowerCase().includes(q));
    return list;
  }, [allDocs, typeFilter, search]);

  // headline stats — over the latest results, or the selected historical run
  const stats = useMemo(() => {
    const results = allDocs
      .map((d) => effResult(d))
      .filter((r): r is ExtractionResult => !!r && !r.error);
    const ok = results.reduce((a, r) => a + (r.ok || 0), 0);
    const tot = results.reduce((a, r) => a + (r.total || 0), 0);
    const times = results
      .map((r) => r.elapsed_s)
      .filter((x): x is number => typeof x === 'number');
    const avg = times.length ? times.reduce((a, b) => a + b, 0) / times.length : null;
    return { docs: allDocs.length, ran: results.length, ok, tot, avg };
  }, [allDocs, effResult]);

  const toggleSel = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const allVisibleSelected =
    filtered.length > 0 && filtered.every((d) => selected.has(d.id));
  const toggleAllVisible = () =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (allVisibleSelected) filtered.forEach((d) => next.delete(d.id));
      else filtered.forEach((d) => d.type !== 'upload' && next.add(d.id));
      return next;
    });

  const running = run?.status === 'running';
  const typeCounts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const d of allDocs) c[d.type] = (c[d.type] || 0) + 1;
    return c;
  }, [allDocs]);

  const pct = run && run.docs_total > 0 ? Math.min((run.done / run.docs_total) * 100, 100) : 0;

  return (
    <div>
      <div className="app-header">
        <div>
          <h1>חילוץ מסמכים</h1>
          <div className="sub">
            הרצת חילוץ על מאגר הדגימה המקורקע (אמת־יסוד) דרך תהליכי ה-n8n —
            קריאת apitools אחת לכל ערך; השאילתות נטענות מההגדרות (q_v3_*).
          </div>
        </div>
        <div className="actions">
          <input
            ref={fileInput}
            type="file"
            accept=".pdf,.jpg,.jpeg,.png"
            style={{ display: 'none' }}
            onChange={(e) => onUpload(e.target.files?.[0] ?? null)}
          />
          <button
            className="btn ghost"
            onClick={() => fileInput.current?.click()}
            disabled={uploading}
          >
            {uploading ? <span className="spinner" /> : <Ic p={IC.upload} />} העלאת מסמך
          </button>
          {selected.size > 0 && (
            <button
              className="btn blue"
              onClick={() => start([...selected])}
              disabled={running}
            >
              <Ic p={IC.play} /> הרץ נבחרים ({selected.size})
            </button>
          )}
          <button className="btn" onClick={() => start()} disabled={running || !data?.available}>
            {running ? <span className="spinner" /> : <Ic p={IC.play} />} הרץ הכל
          </button>
        </div>
      </div>

      {loadErr && (
        <div className="callout bad">
          <b>שגיאה בטעינת המאגר.</b> {loadErr}
        </div>
      )}
      {data && !data.available && (
        <div className="callout warn">
          <b>מאגר הדגימה אינו זמין.</b> ודא שהתיקייה <code>{data.dataset_dir}</code> ממופה לשירות.
        </div>
      )}
      {startErr && (
        <div className="callout warn">
          <b>הפעולה נכשלה.</b> {startErr}
        </div>
      )}

      {/* headline stats */}
      <div className="hud">
        <div className="bigstat">
          <div className="k">מסמכים במאגר</div>
          <div className="v num">{stats.docs}</div>
        </div>
        <div className={`bigstat ${stats.tot > 0 && stats.ok === stats.tot ? 'ok' : ''}`}>
          <div className="k">ציון מול אמת־יסוד</div>
          <div className="v num">{stats.tot > 0 ? `${stats.ok}/${stats.tot}` : '—'}</div>
          {stats.tot > 0 && (
            <div className="bs-sub num">{((stats.ok / stats.tot) * 100).toFixed(1)}%</div>
          )}
        </div>
        <div className="bigstat">
          <div className="k">הורצו</div>
          <div className="v num">
            {stats.ran}/{stats.docs}
          </div>
        </div>
        <div className="bigstat">
          <div className="k">זמן ממוצע למסמך</div>
          <div className="v num">{stats.avg != null ? `${stats.avg.toFixed(1)}s` : '—'}</div>
          <div className="bs-sub">קריאת API אחת לכל ערך</div>
        </div>
      </div>

      {/* live run panel */}
      {run && (
        <div className="card runpanel">
          <div className="sync-meta">
            <span className="name">הרצת חילוץ</span>
            {running && (
              <span className="pill warn">
                <span className="spinner" style={{ marginInlineEnd: 6 }} /> מריץ…
              </span>
            )}
            {run.status === 'done' && (
              <span className={`pill ${run.errors === 0 ? 'ok' : 'warn'}`}>הסתיים</span>
            )}
            {run.status === 'cancelled' && <span className="pill muted">בוטל</span>}
            {running && (
              <button className="link danger" onClick={cancel} style={{ marginInlineStart: 'auto' }}>
                עצור
              </button>
            )}
          </div>
          <div className={`progress${running && run.done === 0 ? ' indet' : ''}`}>
            <div className="bar" style={{ width: running && run.done === 0 ? undefined : `${pct}%` }} />
          </div>
          <div className="statelegend" style={{ marginTop: 11 }}>
            <span className="li">
              מסמכים
              <b className="num">
                {run.done}/{run.docs_total}
              </b>
            </span>
            <span className="li">
              <span className="sw synced" />
              ערכים נכונים<b className="num">{run.ok}</b>
            </span>
            <span className="li">
              <span className="sw failed" />
              שגיאות<b className="num">{run.errors}</b>
            </span>
            {run.current && (
              <span className="li muted mono small" style={{ direction: 'ltr' }}>
                {run.current}
              </span>
            )}
          </div>
        </div>
      )}

      {/* run history — every extraction is persisted; browse any past run */}
      {runs.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="sync-meta" style={{ marginBottom: showHistory ? 10 : 0 }}>
            <span className="name">היסטוריית הרצות</span>
            <span className="pill muted">
              <span className="num">{runs.length}</span>
            </span>
            <button
              className="link"
              onClick={() => setShowHistory((s) => !s)}
              style={{ marginInlineStart: 'auto' }}
            >
              {showHistory ? 'הסתר' : 'הצג'}
            </button>
          </div>
          {showHistory && (
            <div className="tbl-scroll" style={{ maxHeight: 320, overflowY: 'auto' }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>זמן</th>
                    <th>היקף</th>
                    <th>מסמכים</th>
                    <th>ציון</th>
                    <th>שגיאות</th>
                    <th>משך</th>
                    <th>סטטוס</th>
                    <th style={{ width: 130 }}></th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((h) => {
                    const isViewed = viewRun?.run_id === h.run_id;
                    return (
                      <tr key={h.run_id} style={isViewed ? { background: 'var(--surface-2)' } : undefined}>
                        <td className="num small">{fmtTime(h.started)}</td>
                        <td>
                          <span className="tag">{SCOPE_LABEL[h.scope || ''] || h.scope || '—'}</span>
                        </td>
                        <td className="num small">
                          {h.done}/{h.docs_total}
                        </td>
                        <td>
                          {h.total > 0 ? (
                            <span className={`pill ${h.ok === h.total ? 'ok' : 'bad'}`}>
                              <span className="num">
                                {h.ok}/{h.total}
                              </span>
                            </span>
                          ) : (
                            <span className="muted small">—</span>
                          )}
                        </td>
                        <td className="num small">{h.errors || 0}</td>
                        <td className="num small muted">{fmtDuration(h)}</td>
                        <td>
                          <RunStatusPill run={h} />
                        </td>
                        <td style={{ textAlign: 'end' }}>
                          {h.status !== 'running' && (
                            <span style={{ display: 'inline-flex', gap: 12 }}>
                              {isViewed ? (
                                <button className="link" onClick={() => setViewRun(null)} title="חזרה לתוצאות האחרונות">
                                  <Ic p={IC.check} /> מוצג
                                </button>
                              ) : (
                                <button className="link" onClick={() => openRun(h.run_id)}>
                                  הצג
                                </button>
                              )}
                              <button className="link danger" onClick={() => deleteRun(h)} title="מחיקת ההרצה ותוצאותיה — אחרי אישור">
                                <Ic p={IC.trash} /> מחק
                              </button>
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* historical-view banner */}
      {viewRun && (
        <div className="callout" style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <b>מציג הרצה היסטורית</b>
          <span className="num small">{fmtTime(viewRun.started)}</span>
          <span className="tag">{SCOPE_LABEL[viewRun.scope || ''] || viewRun.scope || ''}</span>
          <span className="muted small">
            {Object.keys(viewRun.results).length} מסמכים בהרצה זו
          </span>
          <button className="link" onClick={() => setViewRun(null)} style={{ marginInlineStart: 'auto' }}>
            חזרה לתוצאות האחרונות
          </button>
        </div>
      )}

      {/* toolbar: search / type filter / view toggle */}
      <div className="toolbar">
        <input
          placeholder="חיפוש מסמך…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 220 }}
        />
        <div className="subnav" style={{ border: 'none', margin: 0 }}>
          {[
            ['all', `הכל`],
            ...Object.entries(data?.types || {}),
            ...(data && data.uploads.length ? [['upload', 'העלאות']] : []),
          ].map(([k, label]) => (
            <button
              key={k}
              className={`stab${typeFilter === k ? ' active' : ''}`}
              onClick={() => setTypeFilter(k)}
            >
              {label}
              <span className="n num">{k === 'all' ? allDocs.length : typeCounts[k] || 0}</span>
            </button>
          ))}
        </div>
        <div className="subnav" style={{ border: 'none', margin: 0, marginInlineStart: 'auto' }}>
          <button className={`stab${view === 'list' ? ' active' : ''}`} onClick={() => setView('list')}>
            <Ic p={IC.list} /> רשימה
          </button>
          <button className={`stab${view === 'cards' ? ' active' : ''}`} onClick={() => setView('cards')}>
            <Ic p={IC.grid} /> כרטיסים
          </button>
        </div>
      </div>

      {!data && !loadErr && <div className="spin">טוען מאגר…</div>}

      {/* list view */}
      {data && view === 'list' && (
        <div className="tbl-scroll">
          <table className="table clickable">
            <thead>
              <tr>
                <th style={{ width: 34 }}>
                  {/* (a 13px box is pressed through the label around it, which takes the cell's padding: what a finger hits) */}
                  <label className="dg-checkl">
                    <input
                      type="checkbox"
                      className="dg-check"
                      checked={allVisibleSelected}
                      onChange={toggleAllVisible}
                    />
                  </label>
                </th>
                <th>מסמך</th>
                <th>סוג</th>
                <th>זיהוי סוג</th>
                <th>ציון</th>
                <th>ערכים</th>
                <th style={{ textAlign: 'end' }}>משך</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && (
                <tr>
                  <td className="empty" colSpan={7}>
                    אין מסמכים להצגה
                  </td>
                </tr>
              )}
              {filtered.map((d) => {
                const r = effResult(d);
                const isCurrent = running && run?.current === d.id;
                return (
                  <tr key={d.id} onClick={() => navigate(`/extraction/${d.id}`)}>
                    <td onClick={(e) => e.stopPropagation()}>
                      {d.type !== 'upload' && (
                        <label className="dg-checkl">
                          <input
                            type="checkbox"
                            className="dg-check"
                            checked={selected.has(d.id)}
                            onChange={() => toggleSel(d.id)}
                          />
                        </label>
                      )}
                    </td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        {isCurrent && <span className="spinner" />}
                        <span className="mono small" style={{ fontWeight: 700, direction: 'ltr' }}>
                          {d.file}
                        </span>
                      </div>
                    </td>
                    <td>
                      <span className={`pill ${TYPE_PILL[d.type] || 'muted'}`}>{typeLabel(d)}</span>
                    </td>
                    <td>
                      {r ? (
                        r.type_ok == null ? (
                          <span className="tag">{r.detected_type || '—'}</span>
                        ) : (
                          <span className={`pill ${r.type_ok ? 'ok' : 'bad'}`}>
                            {r.detected_type || '—'}
                          </span>
                        )
                      ) : (
                        <span className="muted small">—</span>
                      )}
                    </td>
                    <td>
                      <ScorePill r={r} />
                    </td>
                    <td>{r && !r.error ? <ValueSummary r={r} /> : r?.error ? (
                      <span className="small" style={{ color: 'var(--red)' }}>{r.error}</span>
                    ) : (
                      <span className="muted small">—</span>
                    )}</td>
                    <td className="num muted small" style={{ textAlign: 'end' }}>
                      {r?.elapsed_s != null ? `${r.elapsed_s}s` : '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* card view — the drawn overlay as the thumbnail (lazy) */}
      {data && view === 'cards' && (
        <div className="card-grid" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(280px,1fr))' }}>
          {filtered.length === 0 && <div className="callout">אין מסמכים להצגה</div>}
          {filtered.map((d) => {
            const r = effResult(d);
            return (
              <Link
                key={d.id}
                to={`/extraction/${d.id}`}
                className="card"
                style={{ margin: 0, padding: 0, overflow: 'hidden', textDecoration: 'none', color: 'inherit' }}
              >
                <div
                  style={{
                    height: 190,
                    background: 'var(--surface-2)',
                    borderBottom: '1px solid var(--line)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    overflow: 'hidden',
                  }}
                >
                  {r && !r.error ? (
                    <img
                      loading="lazy"
                      src={api.extractionDrawUrl(d.id, r.draw_category)}
                      alt={d.file}
                      style={{ width: '100%', height: '100%', objectFit: 'cover', objectPosition: 'top' }}
                    />
                  ) : (
                    <span className="muted small">הרץ חילוץ להצגת הסימון</span>
                  )}
                </div>
                <div style={{ padding: '12px 14px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <span className="mono small" style={{ fontWeight: 700, direction: 'ltr', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 150 }}>
                      {d.file}
                    </span>
                    <span className={`pill ${TYPE_PILL[d.type] || 'muted'}`}>{typeLabel(d)}</span>
                    <span style={{ marginInlineStart: 'auto' }}>
                      <ScorePill r={r} />
                    </span>
                  </div>
                  {r && !r.error && (
                    <div style={{ marginTop: 8 }}>
                      <ValueSummary r={r} />
                    </div>
                  )}
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
