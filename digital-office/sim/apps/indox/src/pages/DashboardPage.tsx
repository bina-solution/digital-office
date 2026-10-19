import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, DashboardStats } from '../api';
import { IC, Ic } from '../icons';
import { columnOf, useColumns, wordOf } from '../words';

const POLL_MS = 15000;

/* The classes are the sync page's state names, borrowed for their colour in the office's legend
   (as the real INDOX's vocab.ts): what needs attention WAITS (lime, `to_sync`), and «other» only
   informs (the sky, `in_progress`). The dashboard names a colour only through this map. */
const GROUP_CLASS: Record<string, string> = {
  done: 'synced',
  attention: 'to_sync',
  failed: 'failed',
  other: 'in_progress',
};

const nn = (v: unknown) => (Number.isFinite(Number(v)) ? Number(v) : 0);
const he = (n: number) => n.toLocaleString('he-IL');

function BigStat({
  k,
  v,
  sub,
  cls,
}: {
  k: string;
  v: number | string;
  sub?: string;
  cls?: string;
}) {
  return (
    <div className={`bigstat${cls ? ` ${cls}` : ''}`}>
      <div className="k">{k}</div>
      <div className="v num">{v}</div>
      {sub && <div className="bs-sub">{sub}</div>}
    </div>
  );
}

/** One labelled horizontal bar (label · track · value). */
function BarRow({
  label,
  value,
  max,
  cls,
  hint,
}: {
  label: string;
  value: number;
  max: number;
  cls?: string;
  hint?: string;
}) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  return (
    <div className="barrow">
      <div className="bar-label" title={hint || label}>
        <bdi>{label}</bdi>
      </div>
      <div className="bar-track">
        <div className={`bar-fill${cls ? ` ${cls}` : ''}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="bar-val num">{he(value)}</div>
    </div>
  );
}

export default function DashboardPage() {
  // A status and a type READ as the service says of the documents table's own columns (words.tsx). This page
  // kept two maps of its own, and what they missed — «RECEIPT», a status the pipeline gained since — stood as
  // the database holds it beside the Hebrew.
  const cols = useColumns();
  const statusLabel = (s: string) => wordOf(columnOf(cols, 'STATUS'), s);
  const typeLabel = (t: string) => wordOf(columnOf(cols, 'TYPE'), t);
  const [d, setD] = useState<DashboardStats | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updated, setUpdated] = useState<Date | null>(null);
  const inFlight = useRef(false);

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const r = await api.dashboardStats();
      setD(r);
      setErr(r.reachable === false ? r.error || 'מקור הנתונים אינו זמין' : null);
      setUpdated(new Date());
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }, []);

  // The visibility guard belongs to the POLL, never to `load` itself — it used to sit at the top of
  // `load`, before `finally { setLoading(false) }`, so a mount while the document reported hidden
  // left this page on "טוען לוח בקרה…" forever with a healthy API behind it. Skip the TICK while
  // hidden, never the first load, and re-load on becoming visible.
  useEffect(() => {
    load();
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
  }, [load]);

  const statusMax = useMemo(
    () => Math.max(1, ...(d?.by_status || []).map((s) => s.count)),
    [d],
  );
  const typeMax = useMemo(
    () => Math.max(1, ...(d?.by_type || []).map((t) => t.count)),
    [d],
  );
  const compMax = useMemo(
    () => Math.max(1, ...(d?.top_companies || []).map((c) => c.count)),
    [d],
  );

  if (loading && !d) return <div className="spin">טוען לוח בקרה…</div>;

  const g = d?.groups || { done: 0, attention: 0, failed: 0, other: 0 };
  const total = nn(d?.total);
  const donePct = total ? Math.round((g.done / total) * 100) : 0;

  return (
    <div>
      <div className="app-header">
        <div>
          <h1>לוח בקרה</h1>
          <div className="sub">
            תמונת מצב חיה של המסמכים הנכנסים — סטטוס, סוגים, חברות וציון חילוץ.
          </div>
        </div>
        <div className="actions">
          {updated && (
            <span className="muted small">
              עודכן {updated.toLocaleTimeString('he-IL')}
            </span>
          )}
          {/* «חי» beat on beside «שגיאת רענון» — the sync screen's chip says what this one now says too */}
          <span className={`live${err ? ' paused' : ''}`}>
            <span className="beat" />
            {err ? 'לא מעודכן' : 'חי'}
          </span>
        </div>
      </div>

      {err && (
        <div className="callout warn">
          <b>שגיאת רענון.</b> {err}
          {d ? '. מוצג הנתון האחרון.' : ''}
        </div>
      )}

      {d && d.reachable !== false && (
        <>
          {/* KPI strip */}
          <div className="hud">
            <BigStat k="סה״כ מסמכים" v={he(total)} />
            <BigStat
              k="הושלמו"
              v={he(g.done)}
              sub={`${donePct}% מהמסמכים`}
              cls="ok"
            />
            <BigStat
              k="דורשים טיפול"
              v={he(g.attention)}
              cls={g.attention ? 'wait' : undefined}
            />
            <BigStat k="נכשלו" v={he(g.failed)} cls={g.failed ? 'err' : undefined} />
            <BigStat k="חברות" v={he(nn(d.companies))} cls="run" />
            <BigStat
              k="ציון חילוץ"
              v={`${nn(d.extraction?.overall)}%`}
              cls={nn(d.extraction?.overall) >= 60 ? 'ok' : 'wait'}
            />
          </div>

          {/* status health + extraction scoring — side by side on desktop,
              stacks on narrow screens (responsive auto-fit, see .dash-grid) */}
          <div className="dash-grid dash-grid-wide">
            <div className="card">
              <h3>בריאות הצינור — לפי סטטוס</h3>
              <div className="statebar" role="img" aria-label="סטטוס">
                {(['done', 'attention', 'failed', 'other'] as const).map((k) =>
                  g[k] > 0 ? (
                    <div
                      key={k}
                      className={`seg ${GROUP_CLASS[k]}`}
                      style={{ width: `${(g[k] / Math.max(1, total)) * 100}%` }}
                      title={he(g[k])}
                    />
                  ) : null,
                )}
              </div>
              {/* (a number reads one way on one screen: the legend said «13243» under a tile that said «13,243») */}
              <div className="statelegend" style={{ marginBottom: 6 }}>
                <span className="li">
                  <span className={`sw ${GROUP_CLASS.done}`} />
                  הושלמו<b className="num">{he(g.done)}</b>
                </span>
                <span className="li">
                  <span className={`sw ${GROUP_CLASS.attention}`} />
                  דורשים טיפול<b className="num">{he(g.attention)}</b>
                </span>
                <span className="li">
                  <span className={`sw ${GROUP_CLASS.failed}`} />
                  נכשלו<b className="num">{he(g.failed)}</b>
                </span>
                <span className="li">
                  <span className={`sw ${GROUP_CLASS.other}`} />
                  אחר<b className="num">{he(g.other)}</b>
                </span>
              </div>
              <div className="barlist">
                {(d.by_status || []).map((s) => (
                  <BarRow
                    key={s.status}
                    label={statusLabel(s.status)}
                    hint={s.status}
                    value={s.count}
                    max={statusMax}
                    cls={GROUP_CLASS[s.group] || GROUP_CLASS.other}
                  />
                ))}
              </div>
            </div>

            <div className="card">
              <h3>ציון חילוץ — לפי שדה</h3>
              <div className="scorehero">
                <div className="score-big num">{nn(d.extraction?.overall)}%</div>
                <div className="score-sub">חילוץ ממוצע על פני השדות</div>
              </div>
              <div className="barlist">
                {(d.extraction?.fields || []).map((f) => (
                  <BarRow
                    key={f.key}
                    label={f.label}
                    value={f.pct}
                    max={100}
                    cls={GROUP_CLASS[f.pct >= 60 ? 'done' : f.pct >= 30 ? 'attention' : 'failed']}
                  />
                ))}
              </div>
            </div>
          </div>

          {/* type distribution + top companies */}
          <div className="dash-grid">
            <div className="card">
              <h3>לפי סוג מסמך</h3>
              <div className="barlist">
                {(d.by_type || []).map((t) => (
                  <BarRow
                    key={t.type}
                    label={typeLabel(t.type)}
                    value={t.count}
                    max={typeMax}
                    cls={GROUP_CLASS.done}
                  />
                ))}
              </div>
            </div>
            <div className="card">
              <h3>חברות מובילות</h3>
              {(d.top_companies || []).length === 0 ? (
                <div className="muted small" style={{ padding: '8px 2px' }}>
                  אין חברות מזוהות עדיין.
                </div>
              ) : (
                <div className="barlist">
                  {(d.top_companies || []).map((c) => (
                    <BarRow
                      key={c.name}
                      label={c.name}
                      value={c.count}
                      max={compMax}
                      cls="run"
                    />
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* recent documents */}
          <div className="card">
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <h3 style={{ margin: 0 }}>מסמכים אחרונים</h3>
              {/* /repos resolves to the ACTIVE instance's table (App.tsx). Never hardcode an
                  instance id here — it used to pin the dashboard to one company's table. */}
              <Link to="/repos" className="link">
                לכל המסמכים <Ic p={IC.arrowLeft} />
              </Link>
            </div>
            <div className="tbl-scroll" style={{ marginTop: 12 }}>
            <table className="table" style={{ minWidth: 440 }}>
              <thead>
                <tr>
                  <th>שם</th>
                  <th>חברה</th>
                  <th>סוג</th>
                  <th>סטטוס</th>
                  <th>תאריך</th>
                </tr>
              </thead>
              <tbody>
                {(d.recent || []).length === 0 && (
                  <tr>
                    <td colSpan={5} className="empty">
                      אין מסמכים עדיין.
                    </td>
                  </tr>
                )}
                {(d.recent || []).map((r, i) => (
                  <tr key={`${r.id}:${i}`}>
                    <td className="mono small">{r.name || r.id || '—'}</td>
                    <td>{r.company || <span className="muted">—</span>}</td>
                    <td>{r.type ? typeLabel(r.type) : <span className="muted">—</span>}</td>
                    <td>
                      <span className={`pill ${statusPill(r.status)}`}>
                        {statusLabel((r.status || '').toUpperCase())}
                      </span>
                    </td>
                    <td className="muted small num">{r.date || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function statusPill(status?: string | null): string {
  const s = (status || '').toUpperCase();
  if (s === 'COMPLETED') return 'ok';
  if (s === 'EXTRACTION_FAILED' || s === 'MAX_ITERATIONS') return 'bad';
  if (s === 'DOUBLE' || s === 'OLD' || s === 'TRASH' || s === 'IN_PROGRESS') return 'muted';
  return 'warn';
}
